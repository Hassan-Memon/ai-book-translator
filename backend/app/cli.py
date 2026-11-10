"""CLI: run the same services the API uses, without HTTP.

uv run translatebook upload <pdf> --title "..." [--source ur --target ar]
uv run translatebook translate <book_id> [--pages 10-13] [--only-failed]
uv run translatebook export <book_id>
uv run translatebook books
uv run translatebook worker
uv run translatebook serve
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from app.core import eventloop
from app.core.config import settings
from app.core.database import session_scope
from app.core.logging import setup_logging

console = Console()
app = typer.Typer(no_args_is_help=True, help="TranslateBook AI command line")


async def _progress(fraction: float, message: str) -> None:
    console.print(f"  [dim]{fraction * 100:5.1f}%[/dim] {message}")


@app.command()
def upload(
    pdf_path: Path,
    title: str = typer.Option("", help="Book title (defaults to file name)"),
    source: str = typer.Option("ur", help="Source language code"),
    target: str = typer.Option("ar", help="Target language code"),
    extract: bool = typer.Option(True, help="Run extraction immediately in this process"),
):
    """Register a PDF and (by default) extract it right away."""
    setup_logging()
    if not pdf_path.exists():
        console.print(f"[red]File not found: {pdf_path}[/red]")
        raise typer.Exit(1)

    async def run() -> None:
        from app.jobs.handlers import get_provider
        from app.services import books as books_service
        from app.services import extraction as extraction_service

        async with session_scope() as session:
            book, job = await books_service.create_book(
                session,
                title=title or pdf_path.stem,
                source_language=source,
                target_language=target,
                filename=pdf_path.name,
                data=pdf_path.read_bytes(),
            )
            console.print(f"[green]book {book.id}[/green] {book.title}  (extraction job {job.id})")
        if extract:
            # Run it here instead of waiting for a worker; the queued job becomes a no-op.
            result = await extraction_service.run_extraction(
                book.id, await get_provider(), _progress
            )
            console.print(f"[green]extracted[/green] {result}")

    eventloop.run(run())


@app.command()
def translate(
    book_id: str,
    pages: str = typer.Option(None, help="1-based page range, e.g. 10-13"),
    only_failed: bool = typer.Option(False, help="Retry failed chunks only"),
):
    """Translate pending chunks of a book in this process."""
    setup_logging()

    async def run() -> None:
        from app.jobs.handlers import get_provider
        from app.services import translation as translation_service

        result = await translation_service.run_translation(
            book_id, await get_provider(), _progress, page_range=pages, only_failed=only_failed
        )
        console.print(f"[green]done[/green] {result}")

    eventloop.run(run())


@app.command()
def export(book_id: str):
    """Export the book to DOCX."""
    setup_logging()

    async def run() -> None:
        from app.services import export as export_service

        result = await export_service.run_export(book_id, _progress)
        console.print(f"[green]{result['path']}[/green]")

    eventloop.run(run())


@app.command()
def books():
    """List books."""

    async def run() -> None:
        from app.services import books as books_service

        async with session_scope() as session:
            rows = await books_service.list_books(session)
            counts = await books_service.chunk_counts_bulk(session, [b.id for b in rows])
        table = Table(title="Books")
        for col in ("id", "title", "pair", "status", "chunks", "approved", "pages"):
            table.add_column(col)
        for b in rows:
            c = counts.get(b.id, {})
            table.add_row(
                str(b.id),
                b.title,
                f"{b.source_language}->{b.target_language}",
                b.status.value,
                str(b.total_chunks),
                str(c.get("approved", 0)),
                str(b.page_count),
            )
        console.print(table)

    eventloop.run(run())


@app.command()
def worker():
    """Run the job worker loop (Ctrl-C to stop after the current job)."""
    from app.worker import main as worker_main

    worker_main()


@app.command()
def serve(host: str = typer.Option(None), port: int = typer.Option(None), reload: bool = False):
    """Run the API (and, with WORKER_INLINE=true, the worker)."""
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=host or settings.api_host,
        port=port or settings.api_port,
        reload=reload,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    app()
