"""Main pipeline orchestration for end-to-end book translation workflow."""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.terminology_agent import TerminologyAgent
from app.agents.translation_agent import TranslationAgent
from app.agents.verification_agent import VerificationAgent
from app.core.config import settings
from app.core.database import session_scope
from app.models.base import BookStatus, ChunkStatus
from app.models.book import Book
from app.models.chunk import Chunk
from app.models.terminology_flag import TerminologyFlag
from app.models.verification_result import VerificationResult
from app.pipeline.chunker import SemanticChunker
from app.pipeline.extractor import PDFExtractor
from app.pipeline.format_mapper import FormatMapper
from app.pipeline.glossary import load_book_glossary

logger = logging.getLogger(__name__)

# How many chunks translate concurrently (capped by settings).
_DEFAULT_CONCURRENCY = 3


class TranslationPipeline:
    """Orchestrate PDF extraction, chunking, and translation for a book."""

    def __init__(self):
        self.extractor = PDFExtractor(settings)
        self.format_mapper = FormatMapper(settings)
        self.chunker = SemanticChunker(settings)

    # ------------------------------------------------------------------
    # Phase 1 — extraction
    # ------------------------------------------------------------------

    async def process_book(
        self,
        book: Book,
        pdf_path: Path,
        session: AsyncSession,
    ) -> Book:
        """Extract, map format, chunk, and persist a book.

        Called synchronously inside the upload request.
        """
        try:
            logger.info(f"Starting extraction pipeline for: {book.title!r}")

            # Step 1: extract text (or OCR)
            extraction_result = await self.extractor.extract(pdf_path)
            book.is_scanned = extraction_result["is_scanned"]
            book.page_count = extraction_result["page_count"]
            if extraction_result["errors"]:
                logger.warning(f"Extraction warnings: {extraction_result['errors']}")

            # Step 2: map structure / format
            format_metadata: list[list[dict[str, Any]]] = []
            for page_idx, page in enumerate(extraction_result["pages"]):
                page_meta = self.format_mapper.map_format(
                    page.get("blocks", []), page_idx, book.source_language
                )
                format_metadata.append([self.format_mapper.to_dict(m) for m in page_meta])

            # Step 3: semantic chunking
            chunks = self.chunker.chunk_document(
                extraction_result["pages"], format_metadata
            )
            book.total_chunks = len(chunks)

            # Step 4: persist chunks
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
            await session.flush()

            book.status = BookStatus.extracted
            session.add(book)
            await session.commit()

            logger.info(
                f"Extraction complete for {book.title!r}: "
                f"{book.total_chunks} chunks, {book.page_count} pages"
            )
            return book

        except Exception as exc:
            logger.error(f"Extraction pipeline failed for {book.title!r}: {exc}", exc_info=True)
            book.status = BookStatus.failed
            book.error = str(exc)
            session.add(book)
            await session.commit()
            raise

    # ------------------------------------------------------------------
    # Phase 2 — translation  (runs as a background task)
    # ------------------------------------------------------------------

    async def run_translation(
        self,
        book_id: str | uuid.UUID,
        llm_provider: Any,
    ) -> None:
        """Translate all pending chunks for a book.

        Runs inside a FastAPI BackgroundTask — opens its own DB session so the
        HTTP response is not blocked and the session lifetime matches the job.
        """
        translation_agent = TranslationAgent(llm_provider)
        verification_agent = VerificationAgent(llm_provider)
        terminology_agent = TerminologyAgent(llm_provider)
        semaphore = asyncio.Semaphore(
            getattr(settings, "translation_concurrency", _DEFAULT_CONCURRENCY)
        )

        async with session_scope() as session:
            # Load book
            book = await self._get_book(book_id, session)
            if book is None:
                logger.error(f"run_translation: book {book_id} not found")
                return

            # Fetch chunks that still need translation
            # TODO(testing): ORIGINAL LINE — this selects every pending chunk in
            # the book and is the correct behavior for production. It is commented
            # out below only to cut LLM token usage while testing. Uncomment the
            # line directly below, and delete/comment out the "TESTING ONLY" block
            # that follows it, once testing is complete.
            # pending = await self._pending_chunks(book.id, session)

            # ---------------------------------------------------------------
            # TESTING ONLY — restrict translation to a 4-page window around the
            # middle of the book so test runs don't burn LLM tokens translating
            # the whole thing. Remove this block and restore the line above when
            # testing is finished.
            # ---------------------------------------------------------------
            pending = await self._pending_chunks(book.id, session)
            if book.page_count:
                mid_page = book.page_count // 2
                test_page_start = max(1, mid_page - 1)
                test_page_end = test_page_start + 3  # 4-page window
                pending = [
                    c
                    for c in pending
                    if c.page_start is not None
                    and test_page_start <= c.page_start <= test_page_end
                ]
                logger.info(
                    f"[TESTING] Limiting translation to pages "
                    f"{test_page_start}-{test_page_end} of {book.title!r} "
                    f"({len(pending)} chunk(s) selected out of full book)"
                )
            # ---------------------------------------------------------------
            # END TESTING ONLY BLOCK
            # ---------------------------------------------------------------

            if not pending:
                logger.info(f"No pending chunks for book {book.title!r}")
                book.status = BookStatus.review
                session.add(book)
                await session.commit()
                return

            logger.info(
                f"Translating {len(pending)} chunks for {book.title!r} "
                f"(concurrency={settings.translation_concurrency})"
            )

            # Pre-load all chunks so neighbor look-up is O(1)
            all_chunks_stmt = (
                select(Chunk)
                .where(Chunk.book_id == book.id)
                .order_by(Chunk.index.asc())
            )
            all_result = await session.execute(all_chunks_stmt)
            index_map: dict[int, Chunk] = {
                c.index: c for c in all_result.scalars().all()
            }

            failed_count = 0
            tasks = [
                self._translate_one(
                    chunk=chunk,
                    book=book,
                    index_map=index_map,
                    translation_agent=translation_agent,
                    verification_agent=verification_agent,
                    terminology_agent=terminology_agent,
                    semaphore=semaphore,
                    session=session,
                )
                for chunk in pending
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    failed_count += 1
                    logger.error(f"Chunk translation task raised: {r}")

            # Update book status
            if failed_count == len(pending):
                book.status = BookStatus.failed
                book.error = f"All {failed_count} chunk(s) failed."
            else:
                book.status = BookStatus.review
                if failed_count:
                    logger.warning(
                        f"{failed_count}/{len(pending)} chunks failed for {book.title!r}"
                    )
            session.add(book)
            await session.commit()
            logger.info(f"Translation run finished for {book.title!r} → status={book.status}")

    # ------------------------------------------------------------------
    # per-chunk translation worker
    # ------------------------------------------------------------------

    async def _translate_one(
        self,
        chunk: Chunk,
        book: Book,
        index_map: dict[int, Chunk],
        translation_agent: TranslationAgent,
        verification_agent: VerificationAgent,
        terminology_agent: TerminologyAgent,
        semaphore: asyncio.Semaphore,
        session: AsyncSession,
    ) -> None:
        """Translate, verify, and flag terminology for a single chunk.

        Guarded by a semaphore so at most N chunks run concurrently.
        Status is written after each sub-step so the pipeline is resumable.
        """
        async with semaphore:
            # --- context neighbours ---
            neighbors = {
                "n_minus_2": index_map.get(chunk.index - 2, Chunk(raw_text="")).raw_text,
                "n_minus_1": index_map.get(chunk.index - 1, Chunk(raw_text="")).raw_text,
                "n_plus_1":  index_map.get(chunk.index + 1, Chunk(raw_text="")).raw_text,
                "n_plus_2":  index_map.get(chunk.index + 2, Chunk(raw_text="")).raw_text,
            }

            # Fresh glossary snapshot for this chunk
            glossary = await load_book_glossary(book.id, session)

            # ---------- translate ----------
            try:
                trans_result = await translation_agent.translate_chunk(
                    chunk_text=chunk.raw_text,
                    chunk_index=chunk.index,
                    neighbors=neighbors,
                    glossary=glossary,
                    source_language=book.source_language,
                    target_language=book.target_language,
                )
                chunk.translated_text = trans_result["translation"]
                chunk.status = ChunkStatus.translated
                if trans_result.get("errors"):
                    chunk.error = "; ".join(trans_result["errors"])
                session.add(chunk)
                await session.flush()
            except Exception as exc:
                logger.error(f"Translation failed for chunk {chunk.index}: {exc}", exc_info=True)
                chunk.status = ChunkStatus.failed
                chunk.error = str(exc)
                chunk.retry_count = (chunk.retry_count or 0) + 1
                session.add(chunk)
                await session.flush()
                raise  # propagate so gather() counts failures

            # ---------- verify ----------
            try:
                ver_result = await verification_agent.verify_translation(
                    chunk_text=chunk.raw_text,
                    translated_text=chunk.translated_text,
                    context_before=neighbors["n_minus_1"],
                    context_after=neighbors["n_plus_1"],
                    glossary=glossary,
                )
                ver = VerificationResult(
                    chunk_id=chunk.id,
                    suggestions=ver_result.get("issues", []),
                    score=1.0 if not ver_result.get("has_issues") else 0.7,
                    summary="OK" if not ver_result.get("has_issues") else "Issues flagged",
                )
                session.add(ver)
                chunk.status = ChunkStatus.verified
                session.add(chunk)
                await session.flush()
            except Exception as exc:
                logger.warning(f"Verification failed for chunk {chunk.index}: {exc}")
                # Verification failure is non-fatal — continue to terminology

            # ---------- terminology ----------
            try:
                term_result = await terminology_agent.flag_terminology(
                    chunk_text=chunk.raw_text,
                    translated_text=chunk.translated_text or "",
                    glossary=glossary,
                )
                for flag_data in term_result.get("flags", []):
                    flag = TerminologyFlag(
                        chunk_id=chunk.id,
                        term=flag_data.get("term", ""),
                        suggested_translation=flag_data.get("suggested_translation", ""),
                        rationale=flag_data.get("reasoning", ""),
                    )
                    session.add(flag)
                chunk.status = ChunkStatus.terminology_reviewed
                session.add(chunk)
                await session.flush()
            except Exception as exc:
                logger.warning(f"Terminology detection failed for chunk {chunk.index}: {exc}")

            # Flush final state
            await session.commit()
            logger.info(
                f"Chunk {chunk.index} done → status={chunk.status}, "
                f"translation={len(chunk.translated_text or '')} chars"
            )

    # ------------------------------------------------------------------
    # resumability helpers
    # ------------------------------------------------------------------

    async def resume_from_chunk(self, book: Book, session: AsyncSession) -> list[Chunk]:
        """Return all chunks that still need translation (for external use)."""
        return await self._pending_chunks(book.id, session)

    # ------------------------------------------------------------------
    # private helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _get_book(
        book_id: str | uuid.UUID,
        session: AsyncSession,
    ) -> Book | None:
        stmt = select(Book).where(Book.id == book_id)
        result = await session.execute(stmt)
        return result.scalars().first()

    @staticmethod
    async def _pending_chunks(
        book_id: uuid.UUID,
        session: AsyncSession,
    ) -> list[Chunk]:
        """Chunks whose status is extracted or failed (failed ones get retried)."""
        stmt = (
            select(Chunk)
            .where(Chunk.book_id == book_id)
            .where(Chunk.status.in_([ChunkStatus.extracted, ChunkStatus.failed]))
            .order_by(Chunk.index.asc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())