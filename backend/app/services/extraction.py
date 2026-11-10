"""Extraction job: PDF -> pages -> format map -> semantic chunks -> DB.

Scanned pages go through the free OCR ladder (app/pipeline/ocr). Each chunk
records the OCR quality of the lines it came from so the reviewer can see
which chunks to trust and the translation graph can decide whether to run
the OCR-repair pass.
"""

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


def _chunk_ocr(
    format_map: list[dict[str, Any]], page_quality: dict[int, float | None]
) -> tuple[float | None, str | None]:
    """OCR quality for a chunk: the mean of its lines' confidences when the
    engine gave any, else the worst page score it spans."""
    confs = [m["ocr_confidence"] for m in format_map if m.get("ocr_confidence") is not None]
    engines = {m.get("ocr_engine") for m in format_map if m.get("ocr_engine")}
    engine = sorted(engines)[0] if engines else None
    if confs:
        return round(sum(confs) / len(confs), 3), engine
    pages = {m.get("page") for m in format_map}
    scores = [page_quality[p] for p in pages if page_quality.get(p) is not None]
    if scores:
        return round(min(scores), 3), engine
    return None, engine


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
        target_language = book.target_language

    if not pdf_path.exists():
        raise FileNotFoundError(f"uploaded file missing: {pdf_path}")

    extractor = PDFExtractor(
        settings, provider=provider, book_id=book_id, source_language=source_language
    )
    # Books quote the other language constantly (Arabic inside Urdu, English
    # terms inside anything): recognise the target language's script too.
    if target_language not in extractor.ladder.languages:
        extractor.ladder.languages.append(target_language)
    mapper = FormatMapper(settings)
    chunker = SemanticChunker(settings)

    await progress(0.02, "opening PDF")
    extraction = await extractor.extract(pdf_path, progress=progress)

    await progress(0.9, "mapping structure")
    format_metadata: list[list[dict[str, Any]]] = []
    page_quality: dict[int, float | None] = {}
    for page_idx, page in enumerate(extraction["pages"]):
        quality = (page.get("ocr_quality") or {}).get("score")
        page_quality[page_idx] = quality
        blocks = [b for b in page.get("blocks", []) if b.get("kind", "text") == "text"]
        page_meta = mapper.map_format(blocks, page_idx, source_language)
        text_blocks = [b for b in blocks if b.get("type") == "text"]
        rows: list[dict[str, Any]] = []
        for meta, block in zip(page_meta, text_blocks, strict=False):
            row = mapper.to_dict(meta)
            if page.get("used_ocr"):
                row["ocr_engine"] = page.get("ocr_engine")
                if block.get("ocr_confidence") is not None:
                    row["ocr_confidence"] = block["ocr_confidence"]
            rows.append(row)
        format_metadata.append(rows)

    await progress(0.93, "chunking")
    chunks = chunker.chunk_document(extraction["pages"], format_metadata)

    async with session_scope() as session:
        book = await get_book(session, book_id)
        await session.execute(delete(Chunk).where(Chunk.book_id == book.id))
        for sc in chunks:
            ocr_quality, ocr_engine = _chunk_ocr(sc.format_map, page_quality)
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
                    ocr_quality=ocr_quality,
                    ocr_engine=ocr_engine,
                )
            )
        book.total_chunks = len(chunks)
        book.completed_chunks = 0
        book.page_count = extraction["page_count"]
        book.is_scanned = extraction["is_scanned"]
        book.ocr_summary = extraction.get("ocr_summary") if extraction["is_scanned"] else None
        book.status = BookStatus.extracted if chunks else BookStatus.failed
        if not chunks:
            book.error = "No text could be extracted from this PDF. " + (
                "; ".join(extraction["errors"][:3])
                or "Scanned pages need an OCR engine: install Tesseract or allow language "
                "pack downloads (OCR_DOWNLOAD_PACKS=true), or configure a vision-capable model."
            )
        await session.commit()

    if not chunks:
        raise RuntimeError(book.error or "No text could be extracted")

    summary = extraction.get("ocr_summary") or {}
    note = ""
    if extraction["is_scanned"] and summary.get("mean_quality") is not None:
        note = f", OCR quality {summary['mean_quality']:.2f}"
    n, pages = len(chunks), extraction["page_count"]
    await progress(
        1.0,
        f"{n} chunk{'s' if n != 1 else ''} from {pages} page{'s' if pages != 1 else ''}{note}",
    )
    return {
        "chunks": len(chunks),
        "pages": extraction["page_count"],
        "is_scanned": extraction["is_scanned"],
        "ocr_summary": summary,
        "warnings": extraction["errors"][:20],
    }
