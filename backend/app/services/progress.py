"""Server-Sent Events for live book progress.

``GET /books/{id}/events`` polls the database once per ``interval`` with a fresh
short session and emits a ``progress`` event only when the snapshot changed
(status, chunk counts, active job progress). When the book has no queued or
running job it sends a final ``idle`` event and closes, so an idle book costs
no open connection; the UI re-subscribes when it starts a new job.

Why poll the DB instead of LISTEN/NOTIFY: the worker already heartbeats job
progress into the ``job`` row (at most ~2 writes/s), so a 1 s read is cheap,
works with any number of API replicas and needs no extra channel.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from app.core.database import session_scope
from app.jobs import queue
from app.services import books as books_service

KEEPALIVE_SECONDS = 15.0


async def book_snapshot(book_id: uuid.UUID) -> dict[str, Any]:
    async with session_scope() as session:
        book = await books_service.get_book(session, book_id)
        counts = await books_service.chunk_counts(session, book.id)
        job = await queue.active_job_for_book(session, book.id)
        translated, approved = books_service.percentages(counts, book.total_chunks)
        return {
            "book_id": str(book.id),
            "status": book.status.value,
            "total_chunks": book.total_chunks,
            "chunk_counts": counts,
            "percent_translated": translated,
            "percent_approved": approved,
            "active_job": (
                {
                    "id": str(job.id),
                    "kind": job.kind.value,
                    "status": job.status.value,
                    "progress": round(float(job.progress or 0.0), 4),
                    "message": job.message,
                    "attempts": job.attempts,
                }
                if job
                else None
            ),
        }


def sse(event: str, data: dict[str, Any] | None = None, *, retry_ms: int | None = None) -> str:
    lines = []
    if retry_ms is not None:
        lines.append(f"retry: {retry_ms}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data or {}, ensure_ascii=False)}")
    return "\n".join(lines) + "\n\n"


async def stream_book_events(
    book_id: uuid.UUID,
    is_disconnected: Callable[[], Awaitable[bool]],
    *,
    interval: float = 1.0,
    max_seconds: float = 3600.0,
) -> AsyncIterator[str]:
    started = last_sent_at = time.monotonic()
    last: dict[str, Any] | None = None
    first = True
    while True:
        if await is_disconnected():
            return
        snap = await book_snapshot(book_id)
        if snap != last:
            yield sse("progress", snap, retry_ms=5000 if first else None)
            first = False
            last, last_sent_at = snap, time.monotonic()
        elif time.monotonic() - last_sent_at > KEEPALIVE_SECONDS:
            yield ": keepalive\n\n"  # comment line: keeps proxies from closing the stream
            last_sent_at = time.monotonic()
        if snap["active_job"] is None:
            yield sse("idle", {"status": snap["status"]})
            return
        if time.monotonic() - started > max_seconds:
            return  # the browser's EventSource reconnects on its own
        await asyncio.sleep(interval)
