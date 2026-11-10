"""Human review use-cases: read chunks with their verification and flags,
edit, approve (idempotent), accept/reject suggestions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.base import ChunkStatus, HumanDecision
from app.models.book import Book
from app.models.chunk import Chunk
from app.models.terminology_flag import TerminologyFlag
from app.models.verification_result import VerificationResult
from app.services.books import NotFound


def _chunk_query():
    return select(Chunk).options(
        selectinload(Chunk.verification_results), selectinload(Chunk.terminology_flags)
    )


async def get_chunk(session: AsyncSession, book_id: uuid.UUID, index: int) -> Chunk:
    stmt = _chunk_query().where(Chunk.book_id == book_id, Chunk.index == index)
    chunk = (await session.execute(stmt)).scalars().first()
    if chunk is None:
        raise NotFound("Chunk not found")
    return chunk


async def list_chunks(
    session: AsyncSession,
    book_id: uuid.UUID,
    *,
    offset: int = 0,
    limit: int = 50,
    status: str | None = None,
    has_pending_flags: bool = False,
) -> tuple[list[Chunk], int]:
    base = select(Chunk).where(Chunk.book_id == book_id)
    if status:
        try:
            base = base.where(Chunk.status == ChunkStatus(status))
        except ValueError as exc:
            raise ValueError(f"unknown status {status!r}") from exc
    if has_pending_flags:
        pending = (
            select(TerminologyFlag.chunk_id)
            .where(TerminologyFlag.human_decision == HumanDecision.pending)
            .distinct()
        )
        base = base.where(Chunk.id.in_(pending))
    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
    stmt = (
        base.options(
            selectinload(Chunk.verification_results), selectinload(Chunk.terminology_flags)
        )
        .order_by(Chunk.index.asc())
        .offset(offset)
        .limit(limit)
    )
    chunks = list((await session.execute(stmt)).scalars().all())
    return chunks, int(total)


def latest_verification(chunk: Chunk) -> VerificationResult | None:
    if not chunk.verification_results:
        return None
    return max(chunk.verification_results, key=lambda v: (v.attempt, v.created_at))


def serialize_chunk(chunk: Chunk) -> dict[str, Any]:
    ver = latest_verification(chunk)
    flags = sorted(chunk.terminology_flags, key=lambda f: f.created_at)
    return {
        "id": chunk.id,
        "book_id": chunk.book_id,
        "index": chunk.index,
        "raw_text": chunk.raw_text,
        "translated_text": chunk.translated_text,
        "format_map": chunk.format_map,
        "content_type": chunk.content_type.value,
        "status": chunk.status.value,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "quality_score": chunk.quality_score,
        "retry_count": chunk.retry_count,
        "human_edited": chunk.human_edited,
        "error": chunk.error,
        "ocr_quality": chunk.ocr_quality,
        "ocr_engine": chunk.ocr_engine,
        "source_clean": chunk.source_clean,
        "verification": (
            {
                "score": ver.score,
                "summary": ver.summary,
                "suggestions": ver.suggestions,
                "attempt": ver.attempt,
            }
            if ver
            else None
        ),
        "flags": [serialize_flag(f, chunk.index) for f in flags],
        "pending_flags": sum(1 for f in flags if f.human_decision == HumanDecision.pending),
        "created_at": chunk.created_at,
        "updated_at": chunk.updated_at,
    }


def serialize_flag(flag: TerminologyFlag, chunk_index: int) -> dict[str, Any]:
    return {
        "id": flag.id,
        "chunk_id": flag.chunk_id,
        "chunk_index": chunk_index,
        "term": flag.term,
        "suggested_translation": flag.suggested_translation,
        "category": flag.category.value,
        "show_in_brackets": flag.show_in_brackets,
        "rationale": flag.rationale,
        "human_decision": flag.human_decision.value,
        "final_value": flag.final_value,
        "applied_to_book": flag.applied_to_book,
        "created_at": flag.created_at,
    }


async def _recount(session: AsyncSession, book_id: uuid.UUID) -> None:
    book = await session.get(Book, book_id)
    if book is None:
        return
    approved = (
        await session.execute(
            select(func.count()).where(
                Chunk.book_id == book_id, Chunk.status == ChunkStatus.approved
            )
        )
    ).scalar() or 0
    book.completed_chunks = int(approved)


async def edit_translation(
    session: AsyncSession, book_id: uuid.UUID, index: int, text: str
) -> Chunk:
    chunk = await get_chunk(session, book_id, index)
    chunk.translated_text = text
    chunk.human_edited = True
    if chunk.status in (ChunkStatus.failed, ChunkStatus.extracted, ChunkStatus.pending):
        chunk.status = ChunkStatus.translated
        chunk.error = None
    await session.commit()
    return await get_chunk(session, book_id, index)


async def approve(session: AsyncSession, book_id: uuid.UUID, index: int) -> Chunk:
    chunk = await get_chunk(session, book_id, index)
    if not chunk.translated_text:
        raise ValueError("Chunk has no translation yet")
    if chunk.status != ChunkStatus.approved:  # idempotent
        chunk.status = ChunkStatus.approved
        await session.flush()
        await _recount(session, book_id)
    await session.commit()
    return await get_chunk(session, book_id, index)


async def unapprove(session: AsyncSession, book_id: uuid.UUID, index: int) -> Chunk:
    chunk = await get_chunk(session, book_id, index)
    if chunk.status == ChunkStatus.approved:
        chunk.status = ChunkStatus.terminology_reviewed
        await session.flush()
        await _recount(session, book_id)
    await session.commit()
    return await get_chunk(session, book_id, index)


async def decide_suggestion(
    session: AsyncSession, book_id: uuid.UUID, index: int, n: int, action: str
) -> Chunk:
    chunk = await get_chunk(session, book_id, index)
    ver = latest_verification(chunk)
    if ver is None or n < 0 or n >= len(ver.suggestions):
        raise NotFound("Suggestion not found")
    suggestions = [dict(s) for s in ver.suggestions]
    suggestion = suggestions[n]
    if action == "accept":
        span = str(suggestion.get("original_span", ""))
        replacement = str(suggestion.get("suggested", ""))
        if span and chunk.translated_text and span in chunk.translated_text:
            chunk.translated_text = chunk.translated_text.replace(span, replacement, 1)
        elif chunk.translated_text is not None and not span:
            pass
        else:
            raise ValueError(
                "The original span no longer appears in the translation; edit manually."
            )
        chunk.human_edited = True
        suggestion["status"] = "accepted"
        ver.applied_at = datetime.now(UTC)
    elif action == "reject":
        suggestion["status"] = "rejected"
    else:
        raise ValueError("action must be 'accept' or 'reject'")
    suggestions[n] = suggestion
    ver.suggestions = suggestions
    ver.accepted = any(s.get("status") == "accepted" for s in suggestions)
    await session.commit()
    return await get_chunk(session, book_id, index)
