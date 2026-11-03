"""Postgres-backed job queue (ADR-0002).

The ``job`` table is the queue. ``claim`` takes the oldest runnable row with
``FOR UPDATE SKIP LOCKED`` so several workers never pick the same job, and the
claim transaction is tiny: the actual work happens afterwards in its own
sessions. Delivery is at-least-once; handlers must be idempotent (chunk
status drives what is re-done, so re-running a translation job only touches
chunks that are still pending).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.base import JobKind, JobStatus
from app.models.job import Job

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


async def enqueue(
    session: AsyncSession,
    book_id: uuid.UUID,
    kind: JobKind,
    payload: dict[str, Any] | None = None,
    *,
    max_attempts: int = 3,
) -> Job:
    job = Job(book_id=book_id, kind=kind, payload=payload or {}, max_attempts=max_attempts)
    session.add(job)
    await session.flush()
    return job


async def active_job_for_book(session: AsyncSession, book_id: uuid.UUID) -> Job | None:
    stmt = (
        select(Job)
        .where(Job.book_id == book_id, Job.status.in_([JobStatus.queued, JobStatus.running]))
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


async def claim(session: AsyncSession, worker_id: str) -> Job | None:
    """Atomically claim one runnable job. Commits. Returns None when idle."""
    stmt = text(
        """
        UPDATE job SET status = 'running', locked_by = :worker, locked_at = now(),
                       started_at = COALESCE(started_at, now()), attempts = attempts + 1,
                       updated_at = now()
        WHERE id = (
            SELECT id FROM job
            WHERE status = 'queued' AND run_after <= now()
            ORDER BY created_at
            FOR UPDATE SKIP LOCKED
            LIMIT 1
        )
        RETURNING id
        """
    )
    row = (await session.execute(stmt, {"worker": worker_id})).first()
    await session.commit()
    if row is None:
        return None
    return await session.get(Job, row[0])


async def heartbeat(
    session: AsyncSession, job_id: uuid.UUID, progress: float, message: str | None
) -> None:
    await session.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(progress=max(0.0, min(1.0, progress)), message=message, locked_at=_now())
    )
    await session.commit()


async def complete(
    session: AsyncSession, job_id: uuid.UUID, result: dict[str, Any] | None = None
) -> None:
    await session.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(
            status=JobStatus.succeeded,
            progress=1.0,
            result=result,
            finished_at=_now(),
            locked_by=None,
            error=None,
        )
    )
    await session.commit()


async def fail(session: AsyncSession, job: Job, error: str) -> None:
    """Re-queue with exponential backoff, or mark failed when attempts are exhausted."""
    if job.attempts >= job.max_attempts:
        values: dict[str, Any] = {
            "status": JobStatus.failed,
            "error": error[:4000],
            "finished_at": _now(),
            "locked_by": None,
        }
    else:
        delay = timedelta(seconds=min(300, 5 * (2 ** (job.attempts - 1))))
        values = {
            "status": JobStatus.queued,
            "error": error[:4000],
            "run_after": _now() + delay,
            "locked_by": None,
            "message": f"retry {job.attempts}/{job.max_attempts} after error",
        }
    await session.execute(update(Job).where(Job.id == job.id).values(**values))
    await session.commit()


async def reclaim_stale(session: AsyncSession, older_than: timedelta | None = None) -> int:
    """Jobs whose worker died mid-run (no heartbeat for ``job_stale_seconds``) go
    back to the queue. The attempt counter is kept, so a job that keeps killing
    its worker still ends up ``failed`` after ``max_attempts``."""
    cutoff = _now() - (older_than or timedelta(seconds=settings.job_stale_seconds))
    result = await session.execute(
        update(Job)
        .where(Job.status == JobStatus.running, Job.locked_at < cutoff)
        .values(status=JobStatus.queued, locked_by=None, message="reclaimed after stale lock")
    )
    await session.commit()
    n = result.rowcount or 0
    if n:
        logger.warning("reclaimed %d stale job(s)", n)
    return n
