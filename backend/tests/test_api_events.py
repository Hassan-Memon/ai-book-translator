"""The SSE progress stream, through the real FastAPI app."""

from __future__ import annotations

import asyncio
import json

import httpx

from app.core.database import session_scope
from app.jobs import queue
from app.main import create_app
from app.services import books as books_service
from app.services import progress as progress_service


def _parse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        fields = dict(
            line.split(": ", 1) for line in block.splitlines() if not line.startswith(":")
        )
        if "event" in fields:
            events.append((fields["event"], json.loads(fields.get("data", "{}"))))
    return events


async def _book_with_job(sample_pdf):
    async with session_scope() as session:
        book, job = await books_service.create_book(
            session,
            title="SSE",
            source_language="ur",
            target_language="ar",
            filename="sample.pdf",
            data=sample_pdf.read_bytes(),
        )
        return book.id, job.id


async def test_events_stream_progress_then_idle(sample_pdf, tmp_storage, monkeypatch) -> None:
    book_id, job_id = await _book_with_job(sample_pdf)  # upload enqueues extraction

    async def advance_job() -> None:
        await asyncio.sleep(0.15)
        async with session_scope() as session:
            await queue.claim(session, "test-worker")
        await asyncio.sleep(0.15)
        async with session_scope() as session:
            await queue.heartbeat(session, job_id, 0.5, "halfway")
        await asyncio.sleep(0.15)
        async with session_scope() as session:
            await queue.complete(session, job_id, {"ok": True})

    original = progress_service.stream_book_events

    def fast(book_id, is_disconnected, **kw):
        return original(book_id, is_disconnected, interval=0.05)

    monkeypatch.setattr(progress_service, "stream_book_events", fast)
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        mover = asyncio.create_task(advance_job())
        resp = await client.get(f"/api/v1/books/{book_id}/events")
        await mover

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = _parse(resp.text)
    kinds = [k for k, _ in events]
    assert kinds[-1] == "idle" and kinds.count("idle") == 1
    progress = [d for k, d in events if k == "progress"]
    statuses = [d["active_job"]["status"] if d["active_job"] else None for d in progress]
    # queued → running → running@50% → finished; each change sent exactly once.
    assert statuses[0] == "queued" and statuses[-1] is None
    assert any(d["active_job"] and d["active_job"]["progress"] == 0.5 for d in progress)
    assert len(progress) == len({json.dumps(d, sort_keys=True) for d in progress})
    assert resp.text.startswith("retry: 5000")


async def test_events_unknown_book_is_404() -> None:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.get("/api/v1/books/00000000-0000-0000-0000-000000000000/events")
    assert resp.status_code == 404
