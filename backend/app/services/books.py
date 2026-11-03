"""Book use-cases: create (with de-dup), list, detail, delete."""

from __future__ import annotations

import hashlib
import logging
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.jobs import queue
from app.models.base import BookStatus, ChunkStatus, JobKind, JobStatus
from app.models.book import Book
from app.models.chunk import Chunk
from app.models.job import Job

logger = logging.getLogger(__name__)


class NotFound(LookupError):
    pass


class Conflict(RuntimeError):
    pass


async def get_book(session: AsyncSession, book_id: uuid.UUID | str) -> Book:
    try:
        bid = book_id if isinstance(book_id, uuid.UUID) else uuid.UUID(str(book_id))
    except ValueError as exc:
        raise NotFound("Book not found") from exc
    book = await session.get(Book, bid)
    if book is None:
        raise NotFound("Book not found")
    return book


async def create_book(
    session: AsyncSession,
    *,
    title: str,
    source_language: str,
    target_language: str,
    filename: str,
    data: bytes,
) -> tuple[Book, Job]:
    """Store the PDF once (sha256 de-dup), create the book and queue extraction."""
    digest = hashlib.sha256(data).hexdigest()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name.replace(" ", "_")
    path = settings.upload_dir / f"{digest[:16]}_{safe_name}"
    if not path.exists():
        path.write_bytes(data)

    book = Book(
        title=title.strip() or safe_name,
        source_language=source_language,
        target_language=target_language,
        source_path=str(path),
        source_sha256=digest,
        status=BookStatus.uploaded,
    )
    session.add(book)
    await session.flush()
    job = await queue.enqueue(session, book.id, JobKind.extraction)
    await session.commit()
    await session.refresh(book)
    return book, job


async def list_books(session: AsyncSession) -> list[Book]:
    stmt = select(Book).order_by(Book.created_at.desc())
    return list((await session.execute(stmt)).scalars().all())


async def chunk_counts(session: AsyncSession, book_id: uuid.UUID) -> dict[str, int]:
    stmt = select(Chunk.status, func.count()).where(Chunk.book_id == book_id).group_by(Chunk.status)
    counts = {s.value: 0 for s in ChunkStatus}
    for status, n in (await session.execute(stmt)).all():
        counts[status.value if hasattr(status, "value") else str(status)] = int(n)
    return counts


async def chunk_counts_bulk(
    session: AsyncSession, book_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, int]]:
    if not book_ids:
        return {}
    stmt = (
        select(Chunk.book_id, Chunk.status, func.count())
        .where(Chunk.book_id.in_(book_ids))
        .group_by(Chunk.book_id, Chunk.status)
    )
    out: dict[uuid.UUID, dict[str, int]] = {b: {s.value: 0 for s in ChunkStatus} for b in book_ids}
    for book_id, status, n in (await session.execute(stmt)).all():
        out[book_id][status.value if hasattr(status, "value") else str(status)] = int(n)
    return out


def percentages(counts: dict[str, int], total: int) -> tuple[float, float]:
    if total <= 0:
        return 0.0, 0.0
    translated = sum(
        counts.get(s, 0) for s in ("translated", "verified", "terminology_reviewed", "approved")
    )
    approved = counts.get("approved", 0)
    return round(100 * translated / total, 1), round(100 * approved / total, 1)


async def latest_export(session: AsyncSession, book_id: uuid.UUID) -> dict[str, Any] | None:
    stmt = (
        select(Job)
        .where(
            Job.book_id == book_id, Job.kind == JobKind.export, Job.status == JobStatus.succeeded
        )
        .order_by(Job.finished_at.desc())
        .limit(1)
    )
    job = (await session.execute(stmt)).scalars().first()
    if job is None or not job.result or not job.result.get("path"):
        return None
    path = Path(job.result["path"])
    if not path.exists():
        return None
    return {
        "job_id": str(job.id),
        "file_name": path.name,
        "created_at": job.finished_at,
        "path": str(path),
    }


async def list_jobs(session: AsyncSession, book_id: uuid.UUID, limit: int = 50) -> list[Job]:
    stmt = select(Job).where(Job.book_id == book_id).order_by(Job.created_at.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars().all())


async def delete_book(session: AsyncSession, book: Book) -> None:
    if book.source_path:
        path = Path(book.source_path)
        # Only delete the file when no other book shares the same upload.
        others = await session.execute(
            select(func.count()).where(Book.source_sha256 == book.source_sha256, Book.id != book.id)
        )
        if path.exists() and (others.scalar() or 0) == 0:
            try:
                path.unlink()
            except OSError as exc:  # pragma: no cover
                logger.warning("could not delete %s: %s", path, exc)
    await session.execute(delete(Book).where(Book.id == book.id))
    await session.commit()
