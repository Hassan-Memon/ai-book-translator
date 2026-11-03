"""Extraction job: PDF → pages → format map → semantic chunks → DB."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from sqlalchemy import delete

from app.core.config import settings
from app.core.database import session_scope
from app.llm.provider import LLMProvider
from app.models.base import BookStatus, ChunkStatus
from app.models.chunk import Chunk
from app.pipeline.chunker import SemanticChunker
from app.pipeline.extractor import PDFExtractor
from app.pipeline.format_mapper import FormatMapper
from app.services.books import get_book

logger = logging.getLogger(__name__)

ProgressCb = Callable[[float, str], Awaitable[None]]


async def run_extraction(
    book_id: Any, provider: LLMProvider | None, progress: ProgressCb
) -> dict[str, Any]:
    """Idempotent: re-running replaces the book's chunks (only valid before translation)."""
    async with session_scope() as session:
        book = await get_book(session, book_id)
        if book.status not in (
            BookStatus.uploaded,
            BookStatus.extracting,
            BookStatus.failed,
            BookStatus.extracted,
        ):
            raise RuntimeError(f"book is {book.status}; extraction only runs before translation")
        book.status = BookStatus.extracting
        book.error = None
        await session.commit()
        pdf_path = Path(book.source_path or "")
        source_language = book.source_language

    if not pdf_path.exists():
        raise FileNotFoundError(f"uploaded file missing: {pdf_path}")

    extractor = PDFExtractor(settings, provider=provider, book_id=book_id)
    mapper = FormatMapper(settings)
    chunker = SemanticChunker(settings)

    await progress(0.02, "opening PDF")
    extraction = await extractor.extract(pdf_path, progress=progress)

    await progress(0.9, "mapping structure")
    format_metadata: list[list[dict[str, Any]]] = []
    for page_idx, page in enumerate(extraction["pages"]):
        page_meta = mapper.map_format(page.get("blocks", []), page_idx, source_language)
        format_metadata.append([mapper.to_dict(m) for m in page_meta])

    await progress(0.93, "chunking")
    chunks = chunker.chunk_document(extraction["pages"], format_metadata)

    async with session_scope() as session:
        book = await get_book(session, book_id)
        await session.execute(delete(Chunk).where(Chunk.book_id == book.id))
        for sc in chunks:
            session.add(
                Chunk(
                    book_id=book.id,
                    index=sc.index,
                    raw_text=sc.raw_text,
                    format_map=sc.format_map,
                    content_type=sc.content_type,
                    status=ChunkStatus.extracted,
                    page_start=sc.page_start,
                    page_end=sc.page_end,
                )
            )
        book.total_chunks = len(chunks)
        book.completed_chunks = 0
        book.page_count = extraction["page_count"]
        book.is_scanned = extraction["is_scanned"]
        book.status = BookStatus.extracted if chunks else BookStatus.failed
        if not chunks:
            book.error = "No text could be extracted from this PDF. " + (
                "; ".join(extraction["errors"][:3])
                or "Scanned pages need a vision-capable "
                "LLM provider or EasyOCR (uv sync --extra ocr-local)."
            )
        await session.commit()

    if not chunks:
        raise RuntimeError(book.error or "No text could be extracted")

    await progress(1.0, f"{len(chunks)} chunks from {extraction['page_count']} pages")
    return {
        "chunks": len(chunks),
        "pages": extraction["page_count"],
        "is_scanned": extraction["is_scanned"],
        "warnings": extraction["errors"][:20],
    }
