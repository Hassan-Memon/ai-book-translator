"""API route handlers."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_session
from app.llm.provider import get_llm_provider
from app.models.base import BookStatus, ChunkStatus, HumanDecision
from app.models.book import Book
from app.models.chunk import Chunk
from app.models.glossary_term import GlossaryTerm
from app.models.terminology_flag import TerminologyFlag
from app.pipeline.pipeline import TranslationPipeline
from app.schemas.book import BookResponse, BookStatusResponse, ChunkResponse, TerminologyFlagResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["books"])
extraction_pipeline = TranslationPipeline()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

async def _get_book_or_404(book_id: str, session: AsyncSession) -> Book:
    stmt = select(Book).where(Book.id == book_id)
    result = await session.execute(stmt)
    book = result.scalars().first()
    if not book:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")
    return book


# ---------------------------------------------------------------------------
# book upload / status
# ---------------------------------------------------------------------------

@router.post("/books/upload", response_model=BookResponse, status_code=status.HTTP_201_CREATED)
async def upload_book(
    title: str,
    file: UploadFile = File(...),
    source_language: str = "ur",
    target_language: str = "ar",
    session: AsyncSession = Depends(get_session),
) -> BookResponse:
    """Upload a PDF book and run the extraction pipeline synchronously."""

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are supported",
        )

    # Save uploaded file with a uuid prefix to avoid collisions
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"{uuid.uuid4().hex}_{Path(file.filename).name}"
    file_path = settings.upload_dir / safe_name

    try:
        contents = await file.read()
        file_path.write_bytes(contents)
    except Exception as e:
        logger.error(f"Failed to save upload: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save file",
        ) from e

    book = Book(
        title=title,
        source_language=source_language,
        target_language=target_language,
        source_path=str(file_path),
        status=BookStatus.uploaded,
    )
    session.add(book)
    await session.flush()

    try:
        logger.info(f"Processing book: {title}")
        book = await extraction_pipeline.process_book(book, file_path, session)
        # process_book already commits; refresh to load server-generated
        # columns (created_at, updated_at) into Python before serialization.
        await session.refresh(book)
        return BookResponse.model_validate(book)
    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        book.status = BookStatus.failed
        book.error = str(e)
        session.add(book)
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pipeline failed: {str(e)}",
        ) from e


@router.get("/books", summary="List all books")
async def list_books(session: AsyncSession = Depends(get_session)):
    """List all books ordered by creation date."""
    stmt = select(Book).order_by(Book.created_at.desc())
    result = await session.execute(stmt)
    books = result.scalars().all()
    return {
        "books": [BookResponse.model_validate(b).model_dump() for b in books],
        "count": len(books),
    }


@router.get("/books/{book_id}", response_model=BookStatusResponse)
async def get_book_status(
    book_id: str,
    session: AsyncSession = Depends(get_session),
) -> BookStatusResponse:
    """Get book status and pipeline progress."""
    book = await _get_book_or_404(book_id, session)
    return BookStatusResponse.model_validate(book)


# ---------------------------------------------------------------------------
# translation trigger
# ---------------------------------------------------------------------------

@router.post("/books/{book_id}/translate", status_code=status.HTTP_202_ACCEPTED)
async def start_translation(
    book_id: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    """Trigger the translation pipeline for an extracted book (runs in background)."""
    book = await _get_book_or_404(book_id, session)

    if book.status not in (BookStatus.extracted, BookStatus.failed):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Book must be in 'extracted' or 'failed' state to translate. Current: {book.status}",
        )

    book.status = BookStatus.translating
    session.add(book)
    await session.commit()

    llm = get_llm_provider(
        settings.llm_provider,
        github_token=settings.github_token,
        github_model=settings.github_model,
        anthropic_api_key=settings.anthropic_api_key,
        anthropic_model=settings.anthropic_model,
        openai_api_key=settings.openai_api_key,
        openai_model=settings.openai_model,
        ollama_base_url=settings.ollama_base_url,
        ollama_model=settings.ollama_model,
    )

    background_tasks.add_task(
        extraction_pipeline.run_translation,
        book_id=str(book.id),
        llm_provider=llm,
    )

    return {"message": "Translation started", "book_id": book_id, "status": book.status}


# ---------------------------------------------------------------------------
# chunk review
# ---------------------------------------------------------------------------

@router.get("/books/{book_id}/chunks")
async def list_chunks(
    book_id: str,
    page: int = 0,
    page_size: int = 20,
    session: AsyncSession = Depends(get_session),
):
    """Return a paginated list of chunks for a book."""
    await _get_book_or_404(book_id, session)

    stmt = (
        select(Chunk)
        .where(Chunk.book_id == book_id)
        .order_by(Chunk.index.asc())
        .offset(page * page_size)
        .limit(page_size)
    )
    result = await session.execute(stmt)
    chunks = result.scalars().all()
    return {
        "chunks": [ChunkResponse.model_validate(c).model_dump() for c in chunks],
        "page": page,
        "page_size": page_size,
    }


@router.get("/books/{book_id}/chunks/{chunk_index}", response_model=ChunkResponse)
async def get_chunk(
    book_id: str,
    chunk_index: int,
    session: AsyncSession = Depends(get_session),
) -> ChunkResponse:
    """Get a single chunk by its index."""
    stmt = select(Chunk).where(Chunk.book_id == book_id, Chunk.index == chunk_index)
    result = await session.execute(stmt)
    chunk = result.scalars().first()
    if not chunk:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chunk not found")
    return ChunkResponse.model_validate(chunk)


@router.patch("/books/{book_id}/chunks/{chunk_index}", response_model=ChunkResponse)
async def edit_chunk_translation(
    book_id: str,
    chunk_index: int,
    translated_text: str,
    session: AsyncSession = Depends(get_session),
) -> ChunkResponse:
    """Human editor updates the translation of a chunk."""
    stmt = select(Chunk).where(Chunk.book_id == book_id, Chunk.index == chunk_index)
    result = await session.execute(stmt)
    chunk = result.scalars().first()
    if not chunk:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chunk not found")

    chunk.translated_text = translated_text
    chunk.status = ChunkStatus.approved
    session.add(chunk)
    await session.commit()
    return ChunkResponse.model_validate(chunk)


@router.post("/books/{book_id}/chunks/{chunk_index}/approve", response_model=ChunkResponse)
async def approve_chunk(
    book_id: str,
    chunk_index: int,
    session: AsyncSession = Depends(get_session),
) -> ChunkResponse:
    """Mark a translated chunk as approved by the human reviewer."""
    stmt = select(Chunk).where(Chunk.book_id == book_id, Chunk.index == chunk_index)
    result = await session.execute(stmt)
    chunk = result.scalars().first()
    if not chunk:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chunk not found")

    if not chunk.translated_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Chunk has no translation yet",
        )

    chunk.status = ChunkStatus.approved
    session.add(chunk)

    # Update book completed_chunks counter
    book = await _get_book_or_404(book_id, session)
    book.completed_chunks = book.completed_chunks + 1
    session.add(book)

    await session.commit()
    return ChunkResponse.model_validate(chunk)


# ---------------------------------------------------------------------------
# terminology (human-in-the-loop)
# ---------------------------------------------------------------------------

@router.get("/books/{book_id}/terminology")
async def list_terminology_flags(
    book_id: str,
    pending_only: bool = True,
    session: AsyncSession = Depends(get_session),
):
    """List terminology flags for human review."""
    await _get_book_or_404(book_id, session)

    stmt = (
        select(TerminologyFlag)
        .join(Chunk, TerminologyFlag.chunk_id == Chunk.id)
        .where(Chunk.book_id == book_id)
    )
    if pending_only:
        stmt = stmt.where(TerminologyFlag.human_decision == HumanDecision.pending)
    result = await session.execute(stmt)
    flags = result.scalars().all()
    return {
        "flags": [TerminologyFlagResponse.model_validate(f).model_dump() for f in flags],
        "count": len(flags),
    }


@router.post("/books/{book_id}/terminology/{flag_id}/decide")
async def decide_terminology(
    book_id: str,
    flag_id: str,
    decision: str,          # "accepted" | "rejected" | "edited"
    final_value: str | None = None,
    apply_to_book: bool = False,
    session: AsyncSession = Depends(get_session),
):
    """Record a human decision on a terminology flag."""
    stmt = select(TerminologyFlag).where(TerminologyFlag.id == flag_id)
    result = await session.execute(stmt)
    flag = result.scalars().first()
    if not flag:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Flag not found")

    try:
        flag.human_decision = HumanDecision(decision)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid decision '{decision}'. Use: accepted, rejected, edited",
        )

    flag.final_value = final_value or flag.suggested_translation
    session.add(flag)

    # If accepted/edited and apply_to_book, add term to glossary
    if decision in ("accepted", "edited") and apply_to_book:
        book = await _get_book_or_404(book_id, session)
        term = GlossaryTerm(
            book_id=book.id,
            original_term=flag.term,
            translation=flag.final_value,
            human_approved=True,
        )
        session.add(term)

    await session.commit()
    return {"flag_id": flag_id, "decision": decision, "final_value": flag.final_value}


# ---------------------------------------------------------------------------
# glossary
# ---------------------------------------------------------------------------

@router.get("/books/{book_id}/glossary")
async def get_glossary(book_id: str, session: AsyncSession = Depends(get_session)):
    """Return the current glossary for a book."""
    await _get_book_or_404(book_id, session)
    stmt = select(GlossaryTerm).where(GlossaryTerm.book_id == book_id)
    result = await session.execute(stmt)
    terms = result.scalars().all()
    return {
        "terms": [
            {
                "id": str(t.id),
                "original_term": t.original_term,
                "translation": t.translation,
                "human_approved": t.human_approved,
            }
            for t in terms
        ],
        "count": len(terms),
    }
