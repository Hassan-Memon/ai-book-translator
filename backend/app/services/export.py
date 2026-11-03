"""Export job: approved + translated chunks → DOCX in settings.export_dir."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.core.database import session_scope
from app.models.chunk import Chunk
from app.pipeline.exporter_docx import export_book_docx
from app.services.books import get_book

ProgressCb = Callable[[float, str], Awaitable[None]]


def _slug(text: str) -> str:
    slug = re.sub(r"[^\w\-]+", "_", text, flags=re.UNICODE).strip("_")
    return slug[:60] or "book"


async def run_export(book_id: Any, progress: ProgressCb, fmt: str = "docx") -> dict[str, Any]:
    if fmt != "docx":
        raise ValueError("only 'docx' export is implemented (PDF is a roadmap item)")
    async with session_scope() as session:
        book = await get_book(session, book_id)
        stmt = select(Chunk).where(Chunk.book_id == book.id).order_by(Chunk.index.asc())
        chunks = [
            {
                "index": c.index,
                "raw_text": c.raw_text,
                "translated_text": c.translated_text,
                "content_type": c.content_type.value,
                "format_map": c.format_map,
                "status": c.status.value,
            }
            for c in (await session.execute(stmt)).scalars().all()
        ]
        title, src, tgt = book.title, book.source_language, book.target_language

    await progress(0.3, f"rendering {len(chunks)} chunks")
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out = settings.export_dir / f"{_slug(title)}_{tgt}_{stamp}.docx"
    path = export_book_docx(
        title=title, source_language=src, target_language=tgt, chunks=chunks, out_path=out
    )
    untranslated = sum(1 for c in chunks if not (c["translated_text"] or "").strip())
    await progress(1.0, f"wrote {path.name}")
    return {
        "path": str(path),
        "file_name": path.name,
        "chunks": len(chunks),
        "untranslated": untranslated,
    }
