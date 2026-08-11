"""CLI entry point."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from app.core.config import settings
from app.core.database import session_scope
from app.models.book import Book
from app.pipeline.pipeline import TranslationPipeline

console = Console()
app = typer.Typer()
pipeline = TranslationPipeline()


@app.command()
def process(
    pdf_path: str,
    title: str,
    source_lang: str = typer.Option("ur", help="Source language code"),
    target_lang: str = typer.Option("ar", help="Target language code"),
):
    """Process a PDF book through extraction and chunking."""
    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        console.print(f"[red]Error: File not found: {pdf_path}[/red]")
        raise typer.Exit(1)

    async def run():
        async with session_scope() as session:
            console.print(f"[cyan]Processing: {title}[/cyan]")

            book = Book(
                title=title,
                source_language=source_lang,
                target_language=target_lang,
                source_path=str(pdf_path),
            )
            session.add(book)
            await session.flush()

            try:
                book = await pipeline.process_book(book, pdf_path, session)
                await session.commit()

                console.print(
                    f"[green]✓ Complete: {book.total_chunks} chunks created[/green]"
                )
                console.print(f"  Scanned: {book.is_scanned}")
                console.print(f"  Pages: {book.page_count}")

            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")
                raise typer.Exit(1)

    asyncio.run(run())


@app.command()
def list_books():
    """List all processed books."""

    async def run():
        async with session_scope() as session:
            from sqlalchemy import select

            stmt = select(Book).order_by(Book.created_at.desc())
            result = await session.execute(stmt)
            books = result.scalars().all()

            table = Table(title="Books")
            table.add_column("Title", style="cyan")
            table.add_column("Status", style="green")
            table.add_column("Chunks", style="magenta")
            table.add_column("Pages", style="yellow")

            for book in books:
                table.add_row(
                    book.title,
                    book.status,
                    str(book.total_chunks),
                    str(book.page_count),
                )

            console.print(table)

    asyncio.run(run())


if __name__ == "__main__":
    app()
