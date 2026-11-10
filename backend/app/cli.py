"""CLI: run the same services the API uses, without HTTP.

uv run translatebook upload <pdf> --title "..." [--source ur --target ar]
uv run translatebook translate <book_id> [--pages 10-13] [--only-failed]
uv run translatebook export <book_id>
uv run translatebook books
uv run translatebook worker
uv run translatebook serve
uv run translatebook eval validate|run|calibrate   (docs/EVALUATION.md)
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


# --------------------------------------------------------------------- eval

eval_app = typer.Typer(
    no_args_is_help=True, help="Measure translation quality (docs/EVALUATION.md)"
)
app.add_typer(eval_app, name="eval")

DEFAULT_GOLDEN = settings.prompts_dir.parent / "docs" / "evals" / "golden" / "starter-v1.jsonl"
DEFAULT_RESULTS = settings.prompts_dir.parent / "docs" / "evals" / "results"


def _eval_provider(provider: str | None, model: str | None):
    """A provider from .env, optionally switched to another provider/model."""
    from app.llm.provider import build_provider, runtime_from_settings

    cfg = settings.model_copy(update={"llm_provider": provider}) if provider else settings
    runtime = runtime_from_settings(cfg)
    if model:
        runtime.model = model
    return build_provider(runtime, cfg=settings)


def _load(golden: Path):
    from app.evals.golden import GoldenError, load_golden, validate_golden

    try:
        items = load_golden(golden)
    except (GoldenError, OSError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    problems = validate_golden(items)
    if problems:
        for p in problems:
            console.print(f"[red]✗[/red] {p}")
        raise typer.Exit(1)
    return items


@eval_app.command("validate")
def eval_validate(
    golden: Path = typer.Argument(DEFAULT_GOLDEN, help="Golden set (.jsonl)"),
    release: bool = typer.Option(False, help="Also enforce v1 size rules (≥15 test, ≥5 per type)"),
):
    """Check a golden set against docs/evals/golden/SCHEMA.md."""
    from collections import Counter

    from app.evals.golden import validate_golden

    items = _load(golden)
    if release:
        problems = validate_golden(items, release=True)
        for p in problems:
            console.print(f"[red]✗[/red] {p}")
        if problems:
            raise typer.Exit(1)
    pairs = Counter(i.pair for i in items)
    types = Counter(i.content_type.value for i in items)
    splits = Counter(i.split for i in items)
    drafts = sum(1 for i in items if i.reviewed_by is None)
    console.print(f"[green]✓ {len(items)} items valid[/green] · {golden.name}")
    console.print(f"  pairs: {dict(pairs)}")
    console.print(f"  types: {dict(types)}")
    console.print(f"  splits: {dict(splits)} · draft references: {drafts}")


@eval_app.command("run")
def eval_run(
    golden: Path = typer.Option(DEFAULT_GOLDEN, help="Golden set (.jsonl)"),
    provider: str = typer.Option(None, help="Translator provider (default: LLM_PROVIDER)"),
    model: str = typer.Option(None, help="Translator model (default: from .env)"),
    judge_provider: str = typer.Option(None, help="Judge provider; omit to skip the judge"),
    judge_model: str = typer.Option(None, help="Judge model (use another model family)"),
    profile: str = typer.Option("auto", help="auto | fast | balanced | thorough"),
    split: str = typer.Option("dev", help="dev | test | all"),
    pair: list[str] = typer.Option(None, help="Only these pairs, e.g. --pair en->ur"),
    limit: int = typer.Option(None, help="First N items only"),
    concurrency: int = typer.Option(1, help="Items in parallel (keep 1 for local models)"),
    out: Path = typer.Option(DEFAULT_RESULTS, help="Results folder"),
    note: str = typer.Option("", help="One line: what changed in this run"),
    no_cache: bool = typer.Option(False, help="Ignore cached translations"),
):
    """Run the real chunk graph over a golden set and record the scores."""
    from app.evals.runner import EvalConfig, run_eval, write_results

    setup_logging()
    items = _load(golden)
    translator = _eval_provider(provider, model)
    judge_llm = (
        _eval_provider(judge_provider, judge_model) if (judge_provider or judge_model) else None
    )
    conf = EvalConfig(
        profile=profile,
        concurrency=concurrency,
        split=None if split == "all" else split,
        limit=limit,
        pairs=pair or None,
        cache_dir=None if no_cache else out / ".cache",
        note=note,
    )
    console.print(
        f"evaluating [bold]{translator.model}[/bold] ({translator.name})"
        + (f", judge [bold]{judge_llm.model}[/bold]" if judge_llm else ", no judge")
    )
    run = eventloop.run(run_eval(items, translator, judge_provider=judge_llm, conf=conf))
    path = write_results(run, out, golden.name)
    agg = run["aggregate"]
    for w in run["meta"]["warnings"]:
        console.print(f"[yellow]! {w}[/yellow]")
    table = Table(title=f"{translator.model} · {run['meta']['strategy']['profile']}")
    for col in ("pair", "items", "chrF++", "structure", "judge"):
        table.add_column(col)
    for pair_name, row in agg.get("by_pair", {}).items():
        table.add_row(
            pair_name,
            str(row["items"]),
            f"{row['chrf']:.1f}" if row["chrf"] is not None else "–",
            f"{row['structure']:.2f}" if row["structure"] is not None else "–",
            f"{row['judge_mean']:.2f}" if row["judge_mean"] is not None else "–",
        )
    console.print(table)
    console.print(
        f"chrF++ {agg.get('chrf')} CI95 {agg.get('chrf_ci95')} · adherence {agg.get('adherence')}"
        f" · structure {agg.get('structure')} · errors {agg.get('errors')}"
    )
    console.print(f"[green]results[/green] {path}")


@eval_app.command("calibrate")
def eval_calibrate(
    golden: Path = typer.Option(DEFAULT_GOLDEN, help="Golden set (.jsonl)"),
    judge_provider: str = typer.Option(None, help="Judge provider"),
    judge_model: str = typer.Option(None, help="Judge model"),
    limit: int = typer.Option(10, help="Items to calibrate on"),
):
    """Check the judge scores each reference above a degraded copy of it."""
    from app.evals.judge import calibrate

    setup_logging()
    items = [i for i in _load(golden) if i.content_type.value != "quranic_verse"][:limit]
    judge_llm = _eval_provider(judge_provider, judge_model)
    result = eventloop.run(calibrate(judge_llm, items))
    for row in result["items"]:
        mark = "[green]✓[/green]" if row["agrees"] else "[red]✗[/red]"
        console.print(
            f"{mark} {row['id']}: {row['axis']} reference {row['reference'][row['axis']]}"
            f" vs degraded {row['degraded'][row['axis']]}"
        )
    agreement = result["agreement"]
    colour = "green" if agreement is not None and agreement >= 0.8 else "red"
    console.print(f"[{colour}]agreement {agreement}[/{colour}] (trust the judge at ≥ 0.8)")


if __name__ == "__main__":
    app()
