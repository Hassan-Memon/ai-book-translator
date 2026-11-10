"""Run the product's chunk graph over a golden set and score it.

The graph is built with :func:`app.agents.chunk_graph.build_chunk_graph`, the
same function the worker uses, with no checkpointer and a glossary seeded
from each item's decided ``terms``. Nothing touches the database: provider
calls are captured by an in-memory recorder for cost and latency.

Failures (provider errors, refusals, empty output) are *scored* as zero,
never dropped (EVALUATION.md, rule 5).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import statistics
import subprocess
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.agents import strategy as strategy_mod
from app.agents.chunk_graph import ChunkState, build_chunk_graph
from app.core.config import REPO_ROOT, Settings, settings
from app.evals import metrics
from app.evals.golden import GoldenItem
from app.evals.judge import AXES, judge, model_family, same_family
from app.llm.prompts import load_prompt
from app.llm.provider import CallRecord, LLMProvider

logger = logging.getLogger(__name__)

# Used only to express cost as "$ per 100 pages" for the results table.
CHARS_PER_PAGE = 1800
PIPELINE_PROMPTS = ("translation", "verification", "terminology", "ocr_cleanup", "polish")


@dataclass
class EvalConfig:
    profile: str = "auto"  # strategy profile override: auto | fast | balanced | thorough
    concurrency: int = 1
    split: str | None = None  # dev | test | None = all
    limit: int | None = None
    pairs: list[str] | None = None  # e.g. ["en→ur"]
    cache_dir: Path | None = None
    note: str = ""


@dataclass
class ItemResult:
    id: str
    pair: str
    content_type: str
    split: str
    reviewed: bool
    source_chars: int = 0
    translation: str = ""
    error: str | None = None
    chrf: float = 0.0
    adherence: float | None = None
    terms_expected: int = 0
    terms_matched: int = 0
    structure: dict[str, Any] = field(default_factory=dict)
    length_ratio: float = 0.0
    gate_passed: bool | None = None
    gate_score: float | None = None
    reviewer_score: float | None = None
    attempts: int = 0
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    seconds: float = 0.0
    judge: dict[str, Any] | None = None
    cached: bool = False

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def prompt_versions(cfg: Settings) -> dict[str, int]:
    versions: dict[str, int] = {}
    for name in (*PIPELINE_PROMPTS, "judge"):
        try:
            versions[name] = load_prompt(name, cfg.prompts_dir).version
        except Exception:
            continue
    return versions


def _cache_key(item: GoldenItem, model: str, profile: str, versions: dict[str, int]) -> str:
    raw = json.dumps(
        [
            item.id,
            item.source,
            item.source_lang,
            item.target_lang,
            item.content_type.value,
            [t.model_dump() for t in item.terms],
            model,
            profile,
            {k: v for k, v in versions.items() if k != "judge"},
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _state(item: GoldenItem, index: int) -> ChunkState:
    return ChunkState(
        book_id=f"eval:{item.id}",
        chunk_index=index,
        source_text=item.source,
        content_type=item.content_type.value,
        source_language=item.source_lang,
        target_language=item.target_lang,
        context_before=item.context_before or "",
        context_after=item.context_after or "",
        glossary=[
            {"original_term": t.source, "translation": t.target, "with_original_in_brackets": False}
            for t in item.terms
        ],
        domain=item.domain or "",
        instructions="",
        examples=[],
        ocr_quality=None,
    )


def select_items(items: list[GoldenItem], conf: EvalConfig) -> list[GoldenItem]:
    chosen = [i for i in items if conf.split is None or i.split == conf.split]
    if conf.pairs:
        wanted = {p.replace("->", "→") for p in conf.pairs}
        chosen = [i for i in chosen if i.pair in wanted]
    return chosen[: conf.limit] if conf.limit else chosen


def score_translation(item: GoldenItem, translation: str) -> dict[str, Any]:
    terms = [t.model_dump() for t in item.terms]
    adherence = metrics.term_adherence(translation, item.source, terms)
    return {
        "chrf": metrics.chrf_pp(translation, item.references),
        "adherence": adherence["adherence"],
        "terms_expected": adherence["expected"],
        "terms_matched": adherence["matched"],
        "structure": metrics.structure_report(
            translation, item.source, item.content_type.value, item.structure
        ),
        "length_ratio": metrics.length_ratio(translation, item.source),
    }


async def run_eval(
    items: list[GoldenItem],
    provider: LLMProvider,
    *,
    judge_provider: LLMProvider | None = None,
    conf: EvalConfig | None = None,
    cfg: Settings | None = None,
) -> dict[str, Any]:
    conf = conf or EvalConfig()
    cfg = cfg or settings
    chosen = select_items(items, conf)
    versions = prompt_versions(cfg)

    calls: dict[str, list[CallRecord]] = defaultdict(list)
    previous_recorder = provider.recorder

    async def recorder(record: CallRecord) -> None:
        calls[str(record.book_id)].append(record)
        if previous_recorder is not None:
            await previous_recorder(record)

    provider.recorder = recorder
    book_settings = {"quality_profile": conf.profile} if conf.profile != "auto" else {}
    graph = build_chunk_graph(provider, cfg, checkpointer=None, book_settings=book_settings)
    strat = strategy_mod.resolve(
        provider.model,
        cfg=cfg,
        book_settings=book_settings,
        is_local=getattr(provider, "is_local", False),
        fake=provider.name == "fake",
    )
    warnings: list[str] = []
    if judge_provider is not None and same_family(provider.model, judge_provider.model):
        warnings.append(
            f"judge {judge_provider.model} is the same family as the translator "
            f"({model_family(provider.model)}); judge scores are likely inflated (ADR-0007)"
        )
    if any(i.reviewed_by is None for i in chosen):
        warnings.append(
            "some references are drafts not yet reviewed by a fluent translator; "
            "treat chrF++ on those items as indicative"
        )

    semaphore = asyncio.Semaphore(max(1, conf.concurrency))
    cache_dir = conf.cache_dir
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)

    async def one(index: int, item: GoldenItem) -> ItemResult:
        res = ItemResult(
            id=item.id,
            pair=item.pair,
            content_type=item.content_type.value,
            split=item.split,
            reviewed=item.reviewed_by is not None,
            source_chars=len(item.source),
        )
        key = _cache_key(item, provider.model, strat.profile, versions)
        cached_path = cache_dir / f"{key}.json" if cache_dir else None
        async with semaphore:
            if cached_path and cached_path.exists():
                data = json.loads(cached_path.read_text(encoding="utf-8"))
                res.__dict__.update(
                    {k: v for k, v in data.items() if k in res.__dict__ and k != "judge"}
                )
                res.cached = True
            else:
                started = time.perf_counter()
                try:
                    out = await graph.ainvoke(_state(item, index))
                    res.translation = out.get("translation", "") or ""
                    gate = out.get("gate_report") or {}
                    res.gate_passed = gate.get("passed") if gate else None
                    res.gate_score = gate.get("score") if gate else None
                    ver = out.get("verification") or {}
                    res.reviewer_score = ver.get("score")
                    res.attempts = int(out.get("attempts", 0) or 0)
                except Exception as exc:  # scored failure, never excluded
                    logger.warning("eval %s failed: %s", item.id, exc)
                    res.error = f"{type(exc).__name__}: {exc}"[:500]
                res.seconds = round(time.perf_counter() - started, 2)
                mine = calls.get(f"eval:{item.id}", [])
                res.llm_calls = len(mine)
                res.input_tokens = sum(c.input_tokens for c in mine)
                res.output_tokens = sum(c.output_tokens for c in mine)
                res.cost_usd = round(sum(c.cost_usd for c in mine), 6)
                if cached_path and res.error is None:
                    cached_path.write_text(
                        json.dumps(res.as_dict(), ensure_ascii=False), encoding="utf-8"
                    )
            res.__dict__.update(score_translation(item, res.translation))
            if judge_provider is not None:
                try:
                    verdict = await judge(
                        judge_provider,
                        source=item.source,
                        reference=item.reference,
                        candidate=res.translation,
                        source_lang=item.source_lang,
                        target_lang=item.target_lang,
                        terms=[t.model_dump() for t in item.terms],
                        item_id=item.id,
                        cfg=cfg,
                    )
                    res.judge = {**verdict.model_dump(), "mean": verdict.mean}
                except Exception as exc:
                    res.judge = {"error": f"{type(exc).__name__}: {exc}"[:300]}
        logger.info(
            "eval %s: chrF++ %.1f, adherence %s, %.0fs%s",
            item.id,
            res.chrf,
            res.adherence,
            res.seconds,
            " (cached)" if res.cached else "",
        )
        return res

    try:
        results = await asyncio.gather(*(one(i, item) for i, item in enumerate(chosen)))
    finally:
        provider.recorder = previous_recorder

    return {
        "meta": {
            "date": datetime.now(UTC).strftime("%Y-%m-%d"),
            "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
            "commit": git_commit(),
            "provider": provider.name,
            "model": provider.model,
            "is_local": bool(getattr(provider, "is_local", False)),
            "strategy": strat.as_dict(),
            "prompt_versions": versions,
            "judge_model": judge_provider.model if judge_provider else None,
            "split": conf.split or "all",
            "items": len(results),
            "note": conf.note,
            "warnings": warnings,
        },
        "aggregate": aggregate(list(results)),
        "items": [r.as_dict() for r in results],
    }


def bootstrap_ci(values: list[float], n: int = 1000, seed: int = 7) -> tuple[float, float] | None:
    """95% percentile bootstrap interval of the mean (seeded, reproducible)."""
    if len(values) < 3:
        return None
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choices(values, k=len(values))) for _ in range(n))
    return round(means[int(0.025 * n)], 2), round(means[int(0.975 * n) - 1], 2)


def _mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 3) if values else None


def aggregate(results: list[ItemResult]) -> dict[str, Any]:
    if not results:
        return {}
    chrf = [r.chrf for r in results]
    expected = sum(r.terms_expected for r in results)
    matched = sum(r.terms_matched for r in results)
    judged = [r.judge for r in results if r.judge and "error" not in r.judge]
    source_chars = sum(r.source_chars for r in results)
    cost = sum(r.cost_usd for r in results)
    fresh = [r.seconds for r in results if not r.cached and r.seconds]
    by_pair: dict[str, dict[str, Any]] = {}
    for pair in sorted({r.pair for r in results}):
        rows = [r for r in results if r.pair == pair]
        by_pair[pair] = {
            "items": len(rows),
            "chrf": _mean([r.chrf for r in rows]),
            "structure": _mean([1.0 if r.structure.get("preserved") else 0.0 for r in rows]),
            "judge_mean": _mean([r.judge["mean"] for r in rows if r.judge and "mean" in r.judge]),
        }
    return {
        "items": len(results),
        "errors": sum(1 for r in results if r.error),
        "chrf": _mean(chrf),
        "chrf_ci95": bootstrap_ci(chrf),
        "adherence": round(matched / expected, 3) if expected else None,
        "terms": {"expected": expected, "matched": matched},
        "structure": _mean([1.0 if r.structure.get("preserved") else 0.0 for r in results]),
        "gate_pass": _mean(
            [1.0 if r.gate_passed else 0.0 for r in results if r.gate_passed is not None]
        ),
        "reviewer_score": _mean(
            [r.reviewer_score for r in results if r.reviewer_score is not None]
        ),
        "judge": {a: _mean([j[a] for j in judged]) for a in (*AXES, "mean")} if judged else None,
        "judge_errors": sum(1 for r in results if r.judge and "error" in r.judge),
        "cost_usd": round(cost, 6),
        "usd_per_100_pages": round(cost / source_chars * CHARS_PER_PAGE * 100, 4)
        if source_chars
        else None,
        "p50_seconds": round(statistics.median(fresh), 1) if fresh else None,
        "llm_calls": sum(r.llm_calls for r in results),
        "by_pair": by_pair,
    }


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() or c in "-." else "-" for c in text).strip("-")[:60]


def write_results(run: dict[str, Any], out_dir: Path, golden_name: str) -> Path:
    """Write the run JSON and append one row to ``out_dir/README.md``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    meta, agg = run["meta"], run["aggregate"]
    stem = f"{meta['date']}_{_slug(meta['model'])}_{meta['strategy']['profile']}_{meta['split']}"
    path = out_dir / f"{stem}.json"
    n = 2
    while path.exists():
        path = out_dir / f"{stem}-{n}.json"
        n += 1
    run["meta"]["golden"] = golden_name
    path.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")

    readme = out_dir / "README.md"
    if not readme.exists():
        readme.write_text(RESULTS_HEADER, encoding="utf-8")
    judge = (agg.get("judge") or {}).get("mean")
    ci = agg.get("chrf_ci95")
    row = (
        f"| {meta['date']} | `{meta['model']}` | {meta['strategy']['profile']} | "
        f"{golden_name} ({meta['split']}, {agg['items']}) | "
        f"{_fmt(agg.get('chrf'), 1)}" + (f" ({ci[0]:.0f}–{ci[1]:.0f})" if ci else "") + " | "
        f"{_fmt(agg.get('adherence'), 2)} | {_fmt(agg.get('structure'), 2)} | "
        f"{_fmt(judge, 2)}"
        + (f" `{meta['judge_model']}`" if meta.get("judge_model") else "")
        + " | "
        f"{agg.get('errors', 0)} | "
        f"{'0 (local)' if meta.get('is_local') else _fmt(agg.get('usd_per_100_pages'), 2)} | "
        f"{_fmt(agg.get('p50_seconds'), 0)} | [{path.name}]({path.name}) |\n"
    )
    with readme.open("a", encoding="utf-8") as fh:
        fh.write(row)
    return path


def _fmt(value: Any, digits: int) -> str:
    if value is None:
        return "–"
    return f"{float(value):.{digits}f}"


_COLUMNS = (
    "Date",
    "Model",
    "Profile",
    "Golden set (split, items)",
    "chrF++ (95% CI)",
    "Term adherence",
    "Structure kept",
    "Judge (1–5)",
    "Errors",
    "$/100 pages",
    "p50 s/item",
    "Run",
)
RESULTS_HEADER = (
    "# Evaluation results\n\n"
    "One row per run of `translatebook eval run`, appended automatically. Each row links the\n"
    "full JSON (every item, its translation, every score). How to read the columns is in\n"
    "[`docs/EVALUATION.md`](../../EVALUATION.md#5-reading-the-results). Rows are never edited\n"
    "or deleted; negative results stay.\n\n"
    "| " + " | ".join(_COLUMNS) + " |\n"
    "|" + "---|" * len(_COLUMNS) + "\n"
)
