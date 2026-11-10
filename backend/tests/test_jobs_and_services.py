"""Integration tests against the test Postgres: queue semantics and the full
upload → extract → translate → review → export path with the fake provider."""

from __future__ import annotations

import asyncio
import uuid

from docx import Document
from sqlalchemy import func, select

from app.core.database import session_scope
from app.jobs import queue
from app.jobs.handlers import run_job
from app.models.base import BookStatus, ChunkStatus, HumanDecision, JobKind, JobStatus
from app.models.chunk import Chunk
from app.models.llm_call import LlmCall
from app.services import books as books_service
from app.services import export as export_service
from app.services import extraction as extraction_service
from app.services import glossary as glossary_service
from app.services import review as review_service
from app.services import terminology as terminology_service
from app.services import translation as translation_service


async def _noop(_fraction: float, _message: str) -> None:
    return None


async def _make_book(sample_pdf) -> uuid.UUID:
    async with session_scope() as session:
        book, job = await books_service.create_book(
            session,
            title="Sample",
            source_language="ur",
            target_language="ar",
            filename="sample.pdf",
            data=sample_pdf.read_bytes(),
        )
        assert job.kind == JobKind.extraction
        return book.id


# ---------------------------------------------------------------------------
# queue
# ---------------------------------------------------------------------------


async def test_claim_is_exclusive_and_retries_with_backoff(sample_pdf, tmp_storage) -> None:
    book_id = await _make_book(sample_pdf)  # enqueues one extraction job
    async with session_scope() as session:
        extra = await queue.enqueue(session, book_id, JobKind.export, max_attempts=2)
        await session.commit()
        extra_id = extra.id

    async def claim_one() -> uuid.UUID | None:
        async with session_scope() as session:
            job = await queue.claim(session, f"w-{uuid.uuid4().hex[:4]}")
            return job.id if job else None

    claimed = await asyncio.gather(claim_one(), claim_one(), claim_one())
    ids = [c for c in claimed if c]
    assert len(ids) == 2 and len(set(ids)) == 2, "two jobs, two distinct claims, third idle"

    async with session_scope() as session:
        job = await session.get(queue.Job, extra_id)
        assert job.status == JobStatus.running and job.attempts == 1
        await queue.fail(session, job, "boom")
    async with session_scope() as session:
        job = await session.get(queue.Job, extra_id)
        assert job.status == JobStatus.queued and job.run_after > job.created_at
        await session.refresh(job)
        job.attempts = 2
        await session.commit()
        await queue.fail(session, job, "boom again")
    async with session_scope() as session:
        job = await session.get(queue.Job, extra_id)
        assert job.status == JobStatus.failed


# ---------------------------------------------------------------------------
# end to end through the services (same code the worker runs)
# ---------------------------------------------------------------------------


async def test_upload_extract_translate_review_export(
    sample_pdf, tmp_storage, fake_provider
) -> None:
    book_id = await _make_book(sample_pdf)

    # Same file uploaded twice is stored once.
    async with session_scope() as session:
        book2, _ = await books_service.create_book(
            session,
            title="Again",
            source_language="ur",
            target_language="ar",
            filename="sample.pdf",
            data=sample_pdf.read_bytes(),
        )
        assert book2.source_path == (await books_service.get_book(session, book_id)).source_path
    assert len(list(tmp_storage.joinpath("uploads").iterdir())) == 1

    # extraction
    result = await extraction_service.run_extraction(book_id, fake_provider, _noop)
    assert result["pages"] == 2 and result["chunks"] >= 2
    async with session_scope() as session:
        book = await books_service.get_book(session, book_id)
        assert book.status == BookStatus.extracted
        assert book.total_chunks == result["chunks"]
        counts = await books_service.chunk_counts(session, book_id)
        assert counts["extracted"] == book.total_chunks

    # translation (fake provider: deterministic, flags «salah»)
    result = await translation_service.run_translation(book_id, fake_provider, _noop)
    assert result["failed"] == 0 and result["translated"] >= 2
    async with session_scope() as session:
        book = await books_service.get_book(session, book_id)
        assert book.status == BookStatus.review
        chunks, total = await review_service.list_chunks(session, book_id, limit=100)
        assert total == book.total_chunks
        assert all(c.status == ChunkStatus.terminology_reviewed for c in chunks)
        assert all(c.translated_text.startswith("[fake-") for c in chunks)
        assert all(c.verification_results for c in chunks)
        flagged = [c for c in chunks if c.terminology_flags]
        assert flagged and flagged[0].terminology_flags[0].term == "salah"
        llm_calls = (await session.execute(select(func.count()).select_from(LlmCall))).scalar()
        assert llm_calls == 3 * total  # translate + verify + terminology per chunk

    # re-running translation is a no-op: nothing pending any more
    result = await translation_service.run_translation(book_id, fake_provider, _noop)
    assert result == {"translated": 0, "failed": 0}

    # human decides the flag, applies it to the book → glossary term
    async with session_scope() as session:
        rows = await terminology_service.list_flags(session, book_id)
        flag, idx = rows[0]
        flag, idx, term = await terminology_service.decide(
            session, book_id, flag.id, decision="edited", final_value="الصلاة", apply_to_book=True
        )
        assert flag.human_decision == HumanDecision.edited and flag.applied_to_book
        assert term is not None and term.translation == "الصلاة"
        assert await terminology_service.list_flags(session, book_id) == []
        # deciding again with a different value upserts rather than violating the unique constraint
        term2 = await glossary_service.upsert_term(
            session, book_id, original_term="salah", translation="صلاة"
        )
        await session.commit()
        assert term2.id == term.id

    # retranslate that chunk: glossary now injected, adherence computed
    result = await translation_service.run_translation(
        book_id, fake_provider, _noop, chunk_indexes=[idx]
    )
    assert result["translated"] == 1
    assert "- salah → صلاة" in fake_provider.calls[-3][1]

    # review: edit, approve (idempotent), unapprove
    async with session_scope() as session:
        chunk = await review_service.edit_translation(session, book_id, idx, "edited text")
        assert chunk.human_edited and chunk.translated_text == "edited text"
        await review_service.approve(session, book_id, idx)
        await review_service.approve(session, book_id, idx)
        book = await books_service.get_book(session, book_id)
        assert book.completed_chunks == 1
        chunk = await review_service.unapprove(session, book_id, idx)
        assert chunk.status == ChunkStatus.terminology_reviewed
        book = await books_service.get_book(session, book_id)
        assert book.completed_chunks == 0
        await review_service.approve(session, book_id, idx)

    # export
    result = await export_service.run_export(book_id, _noop)
    doc = Document(result["path"])
    texts = [p.text for p in doc.paragraphs if p.text.strip()]
    assert texts[0] == "Sample"
    assert any("edited text" in t for t in texts)
    assert result["untranslated"] == 0
    async with session_scope() as session:
        latest = await books_service.latest_export(session, book_id)
        assert latest is None  # exports only count when produced by a succeeded job


async def test_worker_handlers_run_queued_jobs(
    sample_pdf, tmp_storage, monkeypatch, fake_provider
) -> None:
    from app.jobs import handlers

    async def _fake_get_provider(force: bool = False):
        return fake_provider

    monkeypatch.setattr(handlers, "get_provider", _fake_get_provider)
    book_id = await _make_book(sample_pdf)

    async with session_scope() as session:
        job = await queue.claim(session, "test-worker")
        assert job is not None and job.kind == JobKind.extraction
        result = await run_job(job, _noop)
        await queue.complete(session, job.id, result)

    async with session_scope() as session:
        job = await queue.enqueue(session, book_id, JobKind.translation, {"page_range": "1-1"})
        await session.commit()
        job = await queue.claim(session, "test-worker")
        result = await run_job(job, _noop)
        await queue.complete(session, job.id, result)
        done = (
            await session.execute(
                select(func.count()).where(
                    Chunk.book_id == book_id, Chunk.status == ChunkStatus.terminology_reviewed
                )
            )
        ).scalar()
        pending = (
            await session.execute(
                select(func.count()).where(
                    Chunk.book_id == book_id, Chunk.status == ChunkStatus.extracted
                )
            )
        ).scalar()
        assert done >= 1 and pending >= 1, "page range limited the run to page 1"

    async with session_scope() as session:
        job = await queue.enqueue(session, book_id, JobKind.export, {"format": "docx"})
        await session.commit()
        job = await queue.claim(session, "test-worker")
        result = await run_job(job, _noop)
        await queue.complete(session, job.id, result)
        latest = await books_service.latest_export(session, book_id)
        assert latest is not None and latest["file_name"].endswith(".docx")
        assert result["untranslated"] >= 1  # page-2 chunks were not translated
