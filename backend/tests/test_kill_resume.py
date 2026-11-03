"""Kill a real worker process mid-job, start a new one, and check
the book still finishes with no duplicated paid work beyond the in-flight chunk.

This is the test behind two design claims:
- the Postgres job queue is crash-safe (stale lock → reclaimed → re-run), and
- the LangGraph checkpointer makes the re-run cheap (finished nodes are not repeated).

The worker is hard-killed (SIGKILL / TerminateProcess), not SIGTERM: SIGTERM
lets it finish the current job gracefully, which would test nothing.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import fitz
from conftest import TEST_URL
from sqlalchemy import func, select

from app.core.database import session_scope
from app.jobs import queue
from app.models.base import ChunkStatus, JobKind, JobStatus
from app.models.chunk import Chunk
from app.models.job import Job
from app.models.llm_call import LlmCall
from app.services import books as books_service
from app.services import extraction as extraction_service

BACKEND_DIR = Path(__file__).resolve().parents[1]
DELAY_MS = 300  # per fake LLM call; the kill must land inside one `verify` call


def _multi_page_pdf(path: Path, pages: int = 6) -> Path:
    doc = fitz.open()
    for p in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Chapter {p + 1}", fontsize=20)
        for line in range(12):
            page.insert_text(
                (72, 110 + line * 18),
                f"Page {p + 1} sentence {line + 1} about worship and its conditions.",
                fontsize=11,
            )
    doc.save(path)
    doc.close()
    return path


def _start_worker(log: Path) -> subprocess.Popen:
    env = {
        **os.environ,
        "DATABASE_URL": TEST_URL,
        "LLM_PROVIDER": "fake",
        "CHECKPOINTER": "postgres",
        "FAKE_LLM_DELAY_MS": str(DELAY_MS),
        "TRANSLATION_CONCURRENCY": "1",
        "WORKER_POLL_SECONDS": "0.2",
        "JOB_STALE_SECONDS": "1",
        "WORKER_INLINE": "false",
        "LOG_LEVEL": "INFO",
    }
    return subprocess.Popen(
        [sys.executable, "-m", "app.worker"],
        cwd=BACKEND_DIR,
        env=env,
        stdout=log.open("ab"),
        stderr=subprocess.STDOUT,
    )


async def _count_done(book_id: uuid.UUID) -> int:
    async with session_scope() as session:
        return await session.scalar(
            select(func.count())
            .select_from(Chunk)
            .where(Chunk.book_id == book_id, Chunk.status == ChunkStatus.terminology_reviewed)
        )


async def _wait_for(predicate, timeout: float, what: str) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if await predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"timed out waiting for {what}")


async def test_worker_killed_mid_job_resumes_without_duplicate_work(
    tmp_path, tmp_storage, fake_provider
) -> None:
    pdf = _multi_page_pdf(tmp_path / "book.pdf")
    async with session_scope() as session:
        book, extraction_job = await books_service.create_book(
            session,
            title="Kill test",
            source_language="ur",
            target_language="ar",
            filename="book.pdf",
            data=pdf.read_bytes(),
        )
        book_id = book.id
        # Run extraction in-process; only the translation goes to the subprocess.
        await session.delete(await session.get(Job, extraction_job.id))
        await session.commit()
    await extraction_service.run_extraction(book_id, fake_provider, _noop)

    async with session_scope() as session:
        n_chunks = await session.scalar(
            select(func.count()).select_from(Chunk).where(Chunk.book_id == book_id)
        )
        assert n_chunks >= 4, f"fixture should produce several chunks, got {n_chunks}"
        job = await queue.enqueue(session, book_id, JobKind.translation)
        await session.commit()
        job_id = job.id

    log = tmp_path / "worker.log"
    first = _start_worker(log)
    try:
        # Kill inside `verify` of the third chunk: its translate call is paid for
        # and checkpointed, verify (DELAY_MS long) is still running.
        await _wait_for(lambda: _in_verify(book_id, 2), 60, "chunk 2 to reach verify")
        await asyncio.sleep(DELAY_MS / 3000)  # let the async checkpoint write land
    finally:
        first.kill()  # hard kill: no cleanup, job row stays 'running'
        first.wait(10)
    done_at_kill = await _count_done(book_id)
    assert done_at_kill < n_chunks, "worker finished before we could kill it; raise DELAY_MS"

    async with session_scope() as session:
        assert (await session.get(Job, job_id)).status == JobStatus.running

    await asyncio.sleep(1.2)  # let the dead worker's lock go stale (JOB_STALE_SECONDS=1)
    second = _start_worker(log)
    try:

        async def job_finished() -> bool:
            async with session_scope() as session:
                j = await session.get(Job, job_id)
                await session.refresh(j)
                return j.status in (JobStatus.succeeded, JobStatus.failed)

        await _wait_for(job_finished, 90, "the restarted worker to finish the job")
    finally:
        second.kill()
        second.wait(10)

    output = log.read_text(encoding="utf-8", errors="replace")
    async with session_scope() as session:
        job = await session.get(Job, job_id)
        assert job.status == JobStatus.succeeded, output[-3000:]
        assert job.attempts == 2, "one attempt per worker"
        assert await _count_done(book_id) == n_chunks

        rows = (
            await session.execute(
                select(LlmCall.chunk_index, func.count())
                .where(LlmCall.book_id == book_id, LlmCall.node == "translate")
                .group_by(LlmCall.chunk_index)
            )
        ).all()
        per_chunk = dict(rows)
        assert set(per_chunk) == set(range(n_chunks)), per_chunk
        # Every chunk was translated exactly once: the in-flight chunk resumed at
        # verify from its checkpoint instead of paying for translate again.
        assert all(c == 1 for c in per_chunk.values()), per_chunk
    assert "checkpointer unavailable" not in output, output[-3000:]
    assert "chunk 2: resuming at ('verify',)" in output, output[-3000:]


async def _in_verify(book_id: uuid.UUID, chunk_index: int) -> bool:
    async with session_scope() as session:
        nodes = (
            (
                await session.execute(
                    select(LlmCall.node).where(
                        LlmCall.book_id == book_id, LlmCall.chunk_index == chunk_index
                    )
                )
            )
            .scalars()
            .all()
        )
    return "translate" in nodes and "verify" not in nodes


async def _noop(_f: float, _m: str) -> None:
    return None
