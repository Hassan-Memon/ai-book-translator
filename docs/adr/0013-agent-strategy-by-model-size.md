# ADR-0013: One graph, with scaffolding chosen by model size
Date: 2026-11-09 · Status: accepted (implemented in `agents/strategy.py`, `agents/quality.py`, `agents/segmenter.py`, `agents/chunk_graph.py`)

## Context
Users run anything from a 4B model on a CPU laptop to a frontier API. Small models fail in predictable, mostly mechanical ways: skipped sentences, wrong-language answers, chat preambles, broken JSON and ignored glossary terms. Large models rarely do, and paying them to fight failures they do not make wastes time and money. A separate graph per model class would split the tests and the checkpoint semantics.

## Decision
Keep one LangGraph, `prepare → clean_source → translate → gate → verify → retry → polish → terminology`. Resolve a `Strategy` from the model name's size tier and the per-book overrides. The strategy switches on sentence alignment, tagged output, candidates, polish, smaller chunks and more retries for small models. A deterministic quality gate runs for every real model, before any LLM review, and its findings feed both the retry prompt and the reviewer.

## Alternatives considered
- **A bigger prompt for small models**: helps a little, but does not catch a skipped sentence.
- **Always running the full thorough pipeline**: about 3× the calls on large models for little gain.
- **Fine-tuning a small translator**: out of scope for a self-hosted product that supports any model.
- **LLM-only review**: a small reviewer is lenient about its own model family's output. Deterministic checks are not.

## Consequences
- Easier: one graph, one checkpoint layout, one test suite. Every model gets the cheap checks. Each step is visible in the UI ("What this model will get").
- Harder: name-based tiering is a heuristic, so unknown names default to medium and keep the safeguards on. The claim that small models get "close enough" is not measured yet; the evaluation harness (EVALUATION.md) has to quantify the gap per model and strategy.
