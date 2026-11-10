"""Translation job: run the per-chunk graph over every pending chunk.

Concurrency rules (ADR: one AsyncSession per unit of work):
- the job opens short sessions to list chunk ids and to update progress;
- each chunk task opens its own session to load neighbours, run the graph and
  persist, so nothing is shared across concurrently running tasks;
- a semaphore bounds how many chunks are in flight.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.checkpoint import open_checkpointer
from app.agents.chunk_graph import ChunkState, build_chunk_graph, forget_chunk, run_chunk
from app.core.config import settings
from app.core.database import session_scope
from app.llm.provider import LLMProvider
from app.models.base import BookStatus, ChunkStatus, TermCategory
from app.models.chunk import Chunk
from app.models.terminology_flag import TerminologyFlag
from app.models.verification_result import VerificationResult
from app.services import glossary as glossary_service
from app.services.books import get_book

logger = logging.getLogger(__name__)

ProgressCb = Callable[[float, str], Awaitable[None]]

PENDING_STATUSES = (ChunkStatus.pending, ChunkStatus.extracted, ChunkStatus.failed)


def parse_page_range(value: str | None) -> tuple[int, int] | None:
    """'10-13' → (9, 12) zero-based inclusive; '7' → (6, 6)."""
    if not value or not value.strip():
        return None
    text = value.strip().replace("–", "-")
    if "-" in text:
        a, b = text.split("-", 1)
        start, end = int(a), int(b)
    else:
        start = end = int(text)
    if start < 1 or end < start:
        raise ValueError("page_range must look like '10-13' with 1-based pages")
    return start - 1, end - 1


async def select_chunk_ids(
    session: AsyncSession,
    book_id: uuid.UUID,
    *,
    page_range: tuple[int, int] | None = None,
    only_failed: bool = False,
    chunk_indexes: list[int] | None = None,
) -> list[uuid.UUID]:
    stmt = select(Chunk.id).where(Chunk.book_id == book_id).order_by(Chunk.index.asc())
    if chunk_indexes:
        stmt = stmt.where(Chunk.index.in_(chunk_indexes))
    elif only_failed:
        stmt = stmt.where(Chunk.status == ChunkStatus.failed)
    else:
        stmt = stmt.where(Chunk.status.in_(PENDING_STATUSES))
    if page_range:
        stmt = stmt.where(Chunk.page_start >= page_range[0], Chunk.page_start <= page_range[1])
    return list((await session.execute(stmt)).scalars().all())


async def _neighbours(session: AsyncSession, book_id: uuid.UUID, index: int) -> tuple[str, str]:
    stmt = (
        select(Chunk.index, Chunk.raw_text)
        .where(
            Chunk.book_id == book_id, Chunk.index.in_([index - 2, index - 1, index + 1, index + 2])
        )
        .order_by(Chunk.index)
    )
    rows = (await session.execute(stmt)).all()
    before = "\n\n".join(t for i, t in rows if i < index)
    after = "\n\n".join(t for i, t in rows if i > index)
    # Neighbours are context only; cap them so prompts stay bounded.
    return before[-1500:], after[:1500]


async def _examples(
    session: AsyncSession, book_id: uuid.UUID, index: int, source: str, limit: int
) -> list[dict[str, str]]:
    """Translation memory: the approved chunks of this book most similar to
    the one being translated (pg_trgm), used as in-context examples."""
    if limit <= 0:
        return []
    stmt = (
        select(Chunk.raw_text, Chunk.translated_text)
        .where(
            Chunk.book_id == book_id,
            Chunk.status == ChunkStatus.approved,
            Chunk.index != index,
            Chunk.translated_text.isnot(None),
        )
        .order_by(
            func.similarity(func.left(Chunk.raw_text, 1000), func.left(text(":src"), 1000)).desc()
        )
        .limit(limit)
    )
    try:
        rows = (await session.execute(stmt, {"src": source})).all()
    except Exception as exc:  # pg_trgm missing or similar: examples are optional
        logger.debug("translation memory lookup failed: %s", exc)
        return []
    return [{"source": src, "translation": tgt} for src, tgt in rows if src and tgt and tgt.strip()]


async def translate_one(graph: Any, chunk_id: uuid.UUID, memory_examples: int = 3) -> bool:
    """Run the graph for one chunk inside its own session. Returns success."""
    async with session_scope() as session:
        chunk = await session.get(Chunk, chunk_id)
        if chunk is None:
            return False
        if chunk.status == ChunkStatus.approved:
            return True  # never overwrite human-approved work
        book = await get_book(session, chunk.book_id)
        before, after = await _neighbours(session, book.id, chunk.index)
        glossary = await glossary_service.load_for_prompt(session, book.id)
        examples = await _examples(session, book.id, chunk.index, chunk.raw_text, memory_examples)
        state: ChunkState = {
            "book_id": str(book.id),
            "chunk_index": chunk.index,
            "source_text": chunk.raw_text,
            "content_type": chunk.content_type.value,
            "source_language": book.source_language,
            "target_language": book.target_language,
            "context_before": before,
            "context_after": after,
            "glossary": glossary,
            "domain": book.domain or "",
            "instructions": book.instructions or "",
            "examples": examples,
            "ocr_quality": chunk.ocr_quality,
        }
        chunk_index = chunk.index

    try:
        result = await run_chunk(graph, state)
    except Exception as exc:
        logger.error("chunk %s failed: %s", chunk_index, exc)
        async with session_scope() as session:
            chunk = await session.get(Chunk, chunk_id)
            if chunk is not None:
                chunk.status = ChunkStatus.failed
                chunk.error = f"{type(exc).__name__}: {exc}"[:2000]
                chunk.retry_count = (chunk.retry_count or 0) + 1
                await session.commit()
        return False

    async with session_scope() as session:
        chunk = await session.get(Chunk, chunk_id)
        if chunk is None:
            return False
        ver = result.get("verification") or {}
        gate_report = result.get("gate_report") or {}
        chunk.translated_text = result.get("translation", "")
        if ver:
            chunk.quality_score = float(ver.get("score", 0.0))
        elif gate_report:
            chunk.quality_score = float(gate_report.get("score", 0.0))
        else:
            chunk.quality_score = None
        chunk.error = "; ".join(result.get("errors", [])) or None
        chunk.human_edited = False
        chunk.status = ChunkStatus.terminology_reviewed
        if result.get("source_cleaned"):
            chunk.source_clean = result.get("source_work")
        summary = ver.get("summary") or ""
        problems = gate_report.get("problems") or []
        if problems:
            names = ", ".join(sorted({p["name"] for p in problems}))
            summary = f"checks flagged: {names}" + (f" · {summary}" if summary else "")
        session.add(
            VerificationResult(
                chunk_id=chunk.id,
                suggestions=[{**s, "status": "pending"} for s in ver.get("suggestions", [])],
                score=float(
                    ver.get("score", gate_report.get("score", 0.0) if gate_report else 0.0)
                ),
                summary=summary or None,
                attempt=int(result.get("attempts", 1) or 1),
            )
        )
        for flag in result.get("flags", []):
            try:
                category = TermCategory(flag.get("category", "other"))
            except ValueError:
                category = TermCategory.other
            session.add(
                TerminologyFlag(
                    chunk_id=chunk.id,
                    term=str(flag.get("term", ""))[:300],
                    suggested_translation=str(flag.get("suggested_translation", ""))[:300],
                    category=category,
                    show_in_brackets=bool(flag.get("show_in_brackets", False)),
                    rationale=flag.get("rationale") or None,
                )
            )
        await session.commit()
    await forget_chunk(graph, state)
    logger.info(
        "chunk %s done (score=%.2f, flags=%d)",
        chunk_index,
        float(ver.get("score", 0.0)),
        len(result.get("flags", [])),
    )
    return True


async def run_translation(
    book_id: Any,
    provider: LLMProvider,
    progress: ProgressCb,
    *,
    page_range: str | None = None,
    only_failed: bool = False,
    chunk_indexes: list[int] | None = None,
) -> dict[str, Any]:
    async with session_scope() as session:
        book = await get_book(session, book_id)
        book_settings = dict(book.settings or {})
    async with open_checkpointer(settings) as checkpointer:
        graph = build_chunk_graph(
            provider, settings, checkpointer=checkpointer, book_settings=book_settings
        )
        return await _run_translation(
            graph,
            book_id,
            progress,
            page_range=page_range,
            only_failed=only_failed,
            chunk_indexes=chunk_indexes,
        )


async def _run_translation(
    graph: Any,
    book_id: Any,
    progress: ProgressCb,
    *,
    page_range: str | None,
    only_failed: bool,
    chunk_indexes: list[int] | None,
) -> dict[str, Any]:
    prange = parse_page_range(page_range)

    async with session_scope() as session:
        book = await get_book(session, book_id)
        if book.status in (BookStatus.uploaded, BookStatus.extracting):
            raise RuntimeError("book has not been extracted yet")
        ids = await select_chunk_ids(
            session,
            book.id,
            page_range=prange,
            only_failed=only_failed,
            chunk_indexes=chunk_indexes,
        )
        book.status = BookStatus.translating
        book.error = None
        await session.commit()
        bid = book.id

    total = len(ids)
    if total == 0:
        await _finish(bid)
        await progress(1.0, "nothing to translate")
        return {"translated": 0, "failed": 0}

    semaphore = asyncio.Semaphore(max(1, settings.translation_concurrency))
    done = 0
    failed = 0
    lock = asyncio.Lock()

    memory_examples = int(settings.translation_memory_examples)

    async def worker(cid: uuid.UUID) -> None:
        nonlocal done, failed
        async with semaphore:
            ok = await translate_one(graph, cid, memory_examples)
        async with lock:
            done += 1
            if not ok:
                failed += 1
            await progress(done / total, f"{done}/{total} chunks ({failed} failed)")

    await asyncio.gather(*(worker(cid) for cid in ids))
    await _finish(bid)
    return {"translated": done - failed, "failed": failed, "total": total}


async def _finish(book_id: uuid.UUID) -> None:
    async with session_scope() as session:
        book = await get_book(session, book_id)
        stmt = select(Chunk.status).where(Chunk.book_id == book.id)
        statuses = [s for (s,) in (await session.execute(stmt)).all()]
        total = len(statuses)
        approved = sum(1 for s in statuses if s == ChunkStatus.approved)
        book.completed_chunks = approved
        if total and approved == total:
            book.status = BookStatus.done
        elif all(s == ChunkStatus.failed for s in statuses) and total:
            book.status = BookStatus.failed
            book.error = "Every chunk failed; check the provider configuration and job error."
        else:
            book.status = BookStatus.review
        await session.commit()
