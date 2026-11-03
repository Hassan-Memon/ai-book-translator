"""Job worker.

Run standalone:   uv run python -m app.worker
Or inline in the API process (dev default, WORKER_INLINE=true).

Loop: reclaim stale locks → claim one job → run its handler with a progress
callback that heartbeats the row → complete / fail (re-queue with backoff).
Stops cleanly on SIGINT/SIGTERM after the current job finishes.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
from datetime import UTC, datetime

from app.core import eventloop
from app.core.config import settings
from app.core.database import session_scope
from app.core.logging import setup_logging
from app.jobs import handlers, queue
from app.models.job import Job

logger = logging.getLogger(__name__)


def default_worker_id() -> str:
    return settings.worker_id or f"{socket.gethostname()}-{os.getpid()}"


async def process_one(worker_id: str) -> bool:
    """Claim and run a single job. Returns False when the queue is empty."""
    async with session_scope() as session:
        job = await queue.claim(session, worker_id)
        if job is None:
            return False
        job_id, kind, attempts = job.id, job.kind, job.attempts
        # Detach a plain copy; the handler opens its own sessions.
        detached = Job(
            id=job.id,
            book_id=job.book_id,
            kind=job.kind,
            payload=dict(job.payload or {}),
            attempts=job.attempts,
            max_attempts=job.max_attempts,
        )

    logger.info("job %s %s started (attempt %d)", job_id, kind.value, attempts)
    last_beat = datetime.now(UTC)

    async def progress(fraction: float, message: str) -> None:
        nonlocal last_beat
        now = datetime.now(UTC)
        # Throttle DB writes: always write on completion, otherwise at most ~2/s.
        if fraction >= 1.0 or (now - last_beat).total_seconds() >= 0.5:
            last_beat = now
            async with session_scope() as s:
                await queue.heartbeat(s, job_id, fraction, message)

    try:
        result = await handlers.run_job(detached, progress)
    except Exception as exc:
        logger.exception("job %s failed: %s", job_id, exc)
        async with session_scope() as s:
            await queue.fail(s, detached, f"{type(exc).__name__}: {exc}")
        return True

    async with session_scope() as s:
        await queue.complete(s, job_id, result)
    logger.info("job %s %s succeeded: %s", job_id, kind.value, result)
    return True


async def run_worker(stop: asyncio.Event, worker_id: str | None = None) -> None:
    wid = worker_id or default_worker_id()
    logger.info("worker %s started (provider=%s)", wid, settings.llm_provider)
    # Reclaim immediately on start: a previous worker may have died mid-job.
    last_reclaim = datetime.fromtimestamp(0, UTC)
    while not stop.is_set():
        try:
            if (datetime.now(UTC) - last_reclaim).total_seconds() > 60:
                async with session_scope() as s:
                    await queue.reclaim_stale(s)
                last_reclaim = datetime.now(UTC)
            worked = await process_one(wid)
        except Exception as exc:  # DB down etc.: keep the loop alive
            logger.error("worker loop error: %s", exc)
            worked = False
        if not worked:
            try:
                await asyncio.wait_for(stop.wait(), timeout=settings.worker_poll_seconds)
            except TimeoutError:
                pass
    logger.info("worker %s stopped", wid)


def main() -> None:
    setup_logging()
    stop = asyncio.Event()

    async def _run() -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop.set)
            except NotImplementedError:  # Windows
                signal.signal(sig, lambda *_: stop.set())
        await run_worker(stop)

    eventloop.run(_run())


if __name__ == "__main__":
    main()
