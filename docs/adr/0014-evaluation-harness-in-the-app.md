# ADR-0014: The evaluation harness lives in the app and runs the product's own graph

**Status:** accepted · 2026-11-10

## Context

EVALUATION.md planned a separate `evals/` folder at the repository root. A copy of the pipeline drifts from the product, though, and the numbers would then describe something users never run.

## Decision

- The harness is the package `backend/app/evals/` (`golden.py`, `metrics.py`, `judge.py`, `runner.py`), exposed as `translatebook eval validate | run | calibrate`.
- It builds the graph with `build_chunk_graph()`, the function the worker uses, and seeds the glossary from each golden item's decided terms. It needs no database: an in-memory recorder captures calls, tokens, cost and latency.
- **chrF++ is implemented in-house** (about 60 lines). It matches `sacrebleu.CHRF(word_order=2)` to two decimals on English, Arabic, Urdu and Hindi, and those values are pinned in tests. This avoids a dependency and keeps scores comparable with published numbers.
- Golden sets, the schema and results stay under `docs/evals/`, so people review them like documentation.
- Failures are scored as zero, never dropped. Each result file records the commit, the prompt versions, the model and the full strategy.
- The judge is optional and reference-based. It warns when it shares a model family with the translator (ADR-0007). `calibrate` checks that it scores a reference above a degraded copy before its numbers are trusted.

## Consequences

- One `uv sync` installs everything, and the tests run the harness end to end offline with the fake provider.
- Results change when the product changes, which is the point. Cached translations are keyed by item, model, profile and pipeline prompt versions, so a prompt change invalidates exactly what it should.
