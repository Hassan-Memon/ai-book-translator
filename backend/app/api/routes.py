"""HTTP routes. Thin: validate → service → shape. See docs/API.md."""

from __future__ import annotations

import logging
import tempfile
import uuid
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_session, session_scope
from app.core.languages import get_language
from app.jobs import queue
from app.models.base import BookStatus, JobKind
from app.models.book import Book
from app.models.job import Job
from app.pipeline.extractor import sniff_pdf
from app.schemas.book import (
    BookDetailResponse,
    BookResponse,
    BookUpdateRequest,
    ChunkResponse,
    DecideFlagRequest,
    EditChunkRequest,
    ExportRequest,
    FlagResponse,
    GlossaryTermResponse,
    GlossaryUpsertRequest,
    JobResponse,
    SuggestionActionRequest,
    TranslateRequest,
)
from app.services import books as books_service
from app.services import glossary as glossary_service
from app.services import progress as progress_service
from app.services import review as review_service
from app.services import stats as stats_service
from app.services import terminology as terminology_service
from app.services.books import NotFound
from app.services.translation import parse_page_range

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _uuid(value: str, what: str = "id") -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found") from exc


async def _book(session: AsyncSession, book_id: str) -> Book:
    try:
        return await books_service.get_book(session, _uuid(book_id, "Book"))
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


def _book_response(book: Book, counts: dict[str, int]) -> BookResponse:
    translated, approved = books_service.percentages(counts, book.total_chunks)
    data = BookResponse.model_validate(book).model_dump()
    data["status"] = book.status.value
    data["percent_translated"] = translated
    data["percent_approved"] = approved
    return BookResponse(**data)


def _job_response(job: Job) -> JobResponse:
    data = JobResponse.model_validate(job).model_dump()
    data["kind"] = job.kind.value
    data["status"] = job.status.value
    return JobResponse(**data)


def _chunk_response(chunk) -> ChunkResponse:
    return ChunkResponse(**review_service.serialize_chunk(chunk))


def _glossary_response(term) -> GlossaryTermResponse:
    data = GlossaryTermResponse.model_validate(term).model_dump()
    data["category"] = term.category.value
    data["scope"] = term.scope.value
    return GlossaryTermResponse(**data)


async def _enqueue_exclusive(
    session: AsyncSession, book: Book, kind: JobKind, payload: dict
) -> Job:
    active = await queue.active_job_for_book(session, book.id)
    if active is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"A {active.kind.value} job is already {active.status.value} for this book.",
        )
    job = await queue.enqueue(session, book.id, kind, payload)
    await session.commit()
    await session.refresh(job)
    return job


# ---------------------------------------------------------------------------
# books
# ---------------------------------------------------------------------------


@router.post("/books", response_model=BookResponse, status_code=status.HTTP_201_CREATED)
async def upload_book(
    file: UploadFile = File(...),
    title: str = Form(""),
    author: str = Form(""),
    source_language: str = Form("ur"),
    target_language: str = Form("ar"),
    domain: str = Form(""),
    instructions: str = Form(""),
    session: AsyncSession = Depends(get_session),
) -> BookResponse:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only PDF files are supported")
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty file")
    if source_language == target_language:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Source and target language must differ")
    for code in (source_language, target_language):
        if get_language(code) is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown language code {code!r}")
    book, _job = await books_service.create_book(
        session,
        title=title or Path(file.filename).stem,
        source_language=source_language,
        target_language=target_language,
        filename=file.filename,
        data=data,
        author=author.strip() or None,
        domain=domain.strip() or None,
        instructions=instructions.strip() or None,
    )
    return _book_response(book, {})


@router.post("/books/sniff")
async def sniff_book(file: UploadFile = File(...)):
    """Look at a PDF before creating the book: page count, text layer or scan,
    language guess. Nothing is stored."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only PDF files are supported")
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty file")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "sniff.pdf"
        path.write_bytes(data)
        try:
            return await sniff_pdf(path, settings)
        except Exception as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Could not read PDF: {exc}") from exc


@router.patch("/books/{book_id}", response_model=BookDetailResponse)
async def update_book(
    book_id: str, body: BookUpdateRequest, session: AsyncSession = Depends(get_session)
) -> BookDetailResponse:
    book = await _book(session, book_id)
    if body.title is not None and body.title.strip():
        book.title = body.title.strip()
    if body.author is not None:
        book.author = body.author.strip() or None
    if body.domain is not None:
        book.domain = body.domain.strip() or None
    if body.instructions is not None:
        book.instructions = body.instructions.strip() or None
    if body.settings is not None:
        book.settings = {k: v for k, v in body.settings.items() if v not in (None, "")}
    await session.commit()
    await session.refresh(book)
    return await get_book(book_id, session)


@router.get("/books")
async def list_books(session: AsyncSession = Depends(get_session)):
    books = await books_service.list_books(session)
    counts = await books_service.chunk_counts_bulk(session, [b.id for b in books])
    return {
        "books": [_book_response(b, counts.get(b.id, {})).model_dump() for b in books],
        "count": len(books),
    }


@router.get("/books/{book_id}", response_model=BookDetailResponse)
async def get_book(
    book_id: str, session: AsyncSession = Depends(get_session)
) -> BookDetailResponse:
    book = await _book(session, book_id)
    counts = await books_service.chunk_counts(session, book.id)
    active = await queue.active_job_for_book(session, book.id)
    latest = await books_service.latest_export(session, book.id)
    base = _book_response(book, counts).model_dump()
    return BookDetailResponse(
        **base,
        chunk_counts=counts,
        active_job=_job_response(active) if active else None,
        latest_export=latest,
    )


@router.delete("/books/{book_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_book(book_id: str, session: AsyncSession = Depends(get_session)) -> None:
    book = await _book(session, book_id)
    await books_service.delete_book(session, book)


@router.post("/books/{book_id}/translate", status_code=status.HTTP_202_ACCEPTED)
async def start_translation(
    book_id: str, body: TranslateRequest | None = None, session: AsyncSession = Depends(get_session)
):
    body = body or TranslateRequest()
    book = await _book(session, book_id)
    if book.status in (BookStatus.uploaded, BookStatus.extracting):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Book has not been extracted yet")
    if book.total_chunks == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Book has no chunks to translate")
    try:
        parse_page_range(body.page_range)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    job = await _enqueue_exclusive(
        session,
        book,
        JobKind.translation,
        {"page_range": body.page_range, "only_failed": body.only_failed},
    )
    return {"job": _job_response(job).model_dump()}


@router.post("/books/{book_id}/export", status_code=status.HTTP_202_ACCEPTED)
async def start_export(
    book_id: str, body: ExportRequest | None = None, session: AsyncSession = Depends(get_session)
):
    body = body or ExportRequest()
    book = await _book(session, book_id)
    if body.format != "docx":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only 'docx' export is available")
    if book.total_chunks == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing to export yet")
    job = await _enqueue_exclusive(session, book, JobKind.export, {"format": body.format})
    return {"job": _job_response(job).model_dump()}


@router.get("/books/{book_id}/export/download")
async def download_export(book_id: str, session: AsyncSession = Depends(get_session)):
    book = await _book(session, book_id)
    latest = await books_service.latest_export(session, book.id)
    if latest is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No export available yet")
    return FileResponse(
        latest["path"],
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=latest["file_name"],
    )


@router.get("/books/{book_id}/jobs")
async def list_jobs(book_id: str, session: AsyncSession = Depends(get_session)):
    book = await _book(session, book_id)
    jobs = await books_service.list_jobs(session, book.id)
    return {"jobs": [_job_response(j).model_dump() for j in jobs]}


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str, session: AsyncSession = Depends(get_session)) -> JobResponse:
    job = await session.get(Job, _uuid(job_id, "Job"))
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return _job_response(job)


@router.get("/books/{book_id}/events")
async def book_events(book_id: str, request: Request) -> StreamingResponse:
    """Server-Sent Events: ``progress`` on every change, then ``idle`` and close.

    No request-scoped session here: the stream can stay open for minutes, so
    each tick opens its own short session instead of pinning a pool connection.
    """
    async with session_scope() as session:
        book = await _book(session, book_id)
        bid = book.id
    return StreamingResponse(
        progress_service.stream_book_events(bid, request.is_disconnected),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/books/{book_id}/stats")
async def book_stats(book_id: str, session: AsyncSession = Depends(get_session)):
    book = await _book(session, book_id)
    return await stats_service.book_stats(session, book.id)


# ---------------------------------------------------------------------------
# chunks / review
# ---------------------------------------------------------------------------


@router.get("/books/{book_id}/chunks")
async def list_chunks(
    book_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    status_filter: str | None = Query(None, alias="status"),
    has_pending_flags: bool = False,
    session: AsyncSession = Depends(get_session),
):
    book = await _book(session, book_id)
    try:
        chunks, total = await review_service.list_chunks(
            session,
            book.id,
            offset=offset,
            limit=limit,
            status=status_filter,
            has_pending_flags=has_pending_flags,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"chunks": [_chunk_response(c).model_dump() for c in chunks], "total": total}


@router.get("/books/{book_id}/chunks/{index}", response_model=ChunkResponse)
async def get_chunk(book_id: str, index: int, session: AsyncSession = Depends(get_session)):
    book = await _book(session, book_id)
    try:
        return _chunk_response(await review_service.get_chunk(session, book.id, index))
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.patch("/books/{book_id}/chunks/{index}", response_model=ChunkResponse)
async def edit_chunk(
    book_id: str, index: int, body: EditChunkRequest, session: AsyncSession = Depends(get_session)
):
    book = await _book(session, book_id)
    try:
        chunk = await review_service.edit_translation(session, book.id, index, body.translated_text)
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return _chunk_response(chunk)


@router.post("/books/{book_id}/chunks/{index}/approve", response_model=ChunkResponse)
async def approve_chunk(book_id: str, index: int, session: AsyncSession = Depends(get_session)):
    book = await _book(session, book_id)
    try:
        chunk = await review_service.approve(session, book.id, index)
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _chunk_response(chunk)


@router.post("/books/{book_id}/chunks/{index}/unapprove", response_model=ChunkResponse)
async def unapprove_chunk(book_id: str, index: int, session: AsyncSession = Depends(get_session)):
    book = await _book(session, book_id)
    try:
        chunk = await review_service.unapprove(session, book.id, index)
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return _chunk_response(chunk)


@router.post("/books/{book_id}/chunks/{index}/retranslate", status_code=status.HTTP_202_ACCEPTED)
async def retranslate_chunk(book_id: str, index: int, session: AsyncSession = Depends(get_session)):
    book = await _book(session, book_id)
    try:
        await review_service.get_chunk(session, book.id, index)
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    job = await _enqueue_exclusive(session, book, JobKind.translation, {"chunk_indexes": [index]})
    return {"job": _job_response(job).model_dump()}


@router.post("/books/{book_id}/chunks/{index}/suggestions/{n}", response_model=ChunkResponse)
async def decide_suggestion(
    book_id: str,
    index: int,
    n: int,
    body: SuggestionActionRequest,
    session: AsyncSession = Depends(get_session),
):
    book = await _book(session, book_id)
    try:
        chunk = await review_service.decide_suggestion(session, book.id, index, n, body.action)
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _chunk_response(chunk)


# ---------------------------------------------------------------------------
# terminology (human-in-the-loop)
# ---------------------------------------------------------------------------


@router.get("/books/{book_id}/terminology")
async def list_flags(
    book_id: str, pending_only: bool = True, session: AsyncSession = Depends(get_session)
):
    book = await _book(session, book_id)
    rows = await terminology_service.list_flags(session, book.id, pending_only=pending_only)
    flags = [FlagResponse(**review_service.serialize_flag(f, idx)).model_dump() for f, idx in rows]
    return {"flags": flags, "count": len(flags)}


@router.post("/books/{book_id}/terminology/{flag_id}/decide")
async def decide_flag(
    book_id: str,
    flag_id: str,
    body: DecideFlagRequest,
    session: AsyncSession = Depends(get_session),
):
    book = await _book(session, book_id)
    try:
        flag, idx, term = await terminology_service.decide(
            session,
            book.id,
            _uuid(flag_id, "Flag"),
            decision=body.decision,
            final_value=body.final_value,
            apply_to_book=body.apply_to_book,
        )
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {
        "flag": FlagResponse(**review_service.serialize_flag(flag, idx)).model_dump(),
        "glossary_term": _glossary_response(term).model_dump() if term else None,
    }


# ---------------------------------------------------------------------------
# glossary
# ---------------------------------------------------------------------------


@router.get("/books/{book_id}/glossary")
async def get_glossary(book_id: str, session: AsyncSession = Depends(get_session)):
    book = await _book(session, book_id)
    terms = await glossary_service.list_terms(session, book.id)
    return {"terms": [_glossary_response(t).model_dump() for t in terms], "count": len(terms)}


@router.post("/books/{book_id}/glossary", response_model=GlossaryTermResponse)
async def upsert_glossary(
    book_id: str, body: GlossaryUpsertRequest, session: AsyncSession = Depends(get_session)
):
    book = await _book(session, book_id)
    try:
        term = await glossary_service.upsert_term(
            session,
            book.id,
            original_term=body.original_term,
            translation=body.translation,
            category=body.category,
            notes=body.notes,
            with_original_in_brackets=body.with_original_in_brackets,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    await session.refresh(term)
    return _glossary_response(term)


@router.delete("/books/{book_id}/glossary/{term_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_glossary_term(
    book_id: str, term_id: str, session: AsyncSession = Depends(get_session)
) -> None:
    book = await _book(session, book_id)
    if not await glossary_service.delete_term(session, book.id, _uuid(term_id, "Term")):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Term not found")


@router.get("/books/{book_id}/glossary/export")
async def export_glossary(book_id: str, session: AsyncSession = Depends(get_session)):
    book = await _book(session, book_id)
    terms = await glossary_service.list_terms(session, book.id)
    return JSONResponse(
        glossary_service.export_terms(terms),
        headers={"Content-Disposition": f'attachment; filename="glossary_{book.id.hex[:8]}.json"'},
    )


@router.post("/books/{book_id}/glossary/import")
async def import_glossary(
    book_id: str, file: UploadFile = File(...), session: AsyncSession = Depends(get_session)
):
    book = await _book(session, book_id)
    try:
        items = glossary_service.parse_import(file.filename or "glossary.json", await file.read())
        imported = await glossary_service.import_terms(session, book.id, items)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Could not parse file: {exc}") from exc
    return {"imported": imported}
