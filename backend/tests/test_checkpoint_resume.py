"""A chunk that fails mid-graph resumes at the failed node.

The expensive node is ``translate``. If ``verify`` fails (provider down, worker
killed), the retry must not pay for ``translate`` again.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select, text

from app.agents.checkpoint import open_checkpointer
from app.agents.chunk_graph import ChunkState, build_chunk_graph, run_chunk
from app.core import config as config_module
from app.core.database import session_scope
from app.models.base import ChunkStatus
from app.models.chunk import Chunk
from app.models.llm_call import LlmCall
from app.services import books as books_service
from app.services import extraction as extraction_service
from app.services import translation as translation_service


def _nodes(provider) -> list[str]:
    kinds = {
        "TranslationOutput": "translate",
        "VerificationOutput": "verify",
        "TerminologyOutput": "terminology",
    }
    return [kinds.get(kind, kind) for kind, _ in provider.calls]


def _state(chunk_index: int = 0, text: str = "پہلا پیراگراف") -> ChunkState:
    return {
        "book_id": "book-1",
        "chunk_index": chunk_index,
        "source_text": text,
        "content_type": "paragraph",
        "source_language": "ur",
        "target_language": "ar",
        "glossary": [],
    }


@pytest.mark.parametrize("kind", ["memory", "postgres"])
async def test_graph_resumes_at_failed_node(kind, fake_provider, monkeypatch) -> None:
    monkeypatch.setattr(config_module.settings, "checkpointer", kind)
    async with open_checkpointer(config_module.settings) as saver:
        assert saver is not None, f"{kind} checkpointer failed to start"
        graph = build_chunk_graph(fake_provider, config_module.settings, checkpointer=saver)

        fake_provider.fail_on_node = {"verify": 1}
        with pytest.raises(Exception, match="fake failure"):
            await run_chunk(graph, _state())
        assert _nodes(fake_provider) == ["translate", "verify"]

        result = await run_chunk(graph, _state())
        # Resumed at verify: translate was NOT called a second time.
        assert _nodes(fake_provider) == ["translate", "verify", "verify", "terminology"]
        assert result["translation"].startswith("[fake-")
        assert result["verification"]["score"] >= 0.9


async def test_changed_source_text_ignores_stale_checkpoint(fake_provider, monkeypatch) -> None:
    monkeypatch.setattr(config_module.settings, "checkpointer", "memory")
    async with open_checkpointer(config_module.settings) as saver:
        graph = build_chunk_graph(fake_provider, config_module.settings, checkpointer=saver)
        fake_provider.fail_on_node = {"verify": 1}
        with pytest.raises(Exception, match="fake failure"):
            await run_chunk(graph, _state(text="old text"))
        result = await run_chunk(graph, _state(text="new text"))
        assert "new text" in result["translation"]
        assert _nodes(fake_provider).count("translate") == 2


async def test_translation_service_resume_and_cleanup(
    sample_pdf, tmp_storage, fake_provider
) -> None:
    """End to end through the service and the real Postgres checkpointer."""
    async with session_scope() as session:
        book, _job = await books_service.create_book(
            session,
            title="Sample",
            source_language="ur",
            target_language="ar",
            filename="sample.pdf",
            data=sample_pdf.read_bytes(),
        )
        book_id = book.id

    async def noop(_f: float, _m: str) -> None:
        return None

    await extraction_service.run_extraction(book_id, fake_provider, noop)
    async with session_scope() as session:
        n_chunks = await session.scalar(
            select(func.count()).select_from(Chunk).where(Chunk.book_id == book_id)
        )
    assert n_chunks and n_chunks >= 2
    fake_provider.calls.clear()

    # Run 1: verify fails once → that chunk is marked failed, its checkpoint kept.
    fake_provider.fail_on_node = {"verify": 1}
    first = await translation_service.run_translation(book_id, fake_provider, noop)
    assert first["failed"] == 1
    translate_calls_run1 = _nodes(fake_provider).count("translate")
    assert translate_calls_run1 == n_chunks

    # Run 2 (retry failed): resumes at verify; no new translate call.
    second = await translation_service.run_translation(
        book_id, fake_provider, noop, only_failed=True
    )
    assert second == {"translated": 1, "failed": 0, "total": 1}
    assert _nodes(fake_provider).count("translate") == translate_calls_run1

    async with session_scope() as session:
        statuses = (
            (await session.execute(select(Chunk.status).where(Chunk.book_id == book_id)))
            .scalars()
            .all()
        )
        assert all(s == ChunkStatus.terminology_reviewed for s in statuses)
        translate_rows = await session.scalar(
            select(func.count())
            .select_from(LlmCall)
            .where(LlmCall.book_id == book_id, LlmCall.node == "translate")
        )
        assert translate_rows == n_chunks, "exactly one paid translate call per chunk"
        # Persisted chunks have their checkpoints deleted.
        left = await session.scalar(
            text("SELECT count(*) FROM checkpoints WHERE thread_id LIKE :p"),
            {"p": f"{book_id}:%"},
        )
        assert left == 0


def test_psycopg_url() -> None:
    from app.agents.checkpoint import psycopg_url

    assert psycopg_url("postgresql+asyncpg://u:p@h:1/db") == "postgresql://u:p@h:1/db"
