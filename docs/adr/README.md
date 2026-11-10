# Architecture Decision Records

One short file per decision that someone could reasonably have made differently. Numbered,
never deleted; superseded ones get a "Superseded by ADR-00xx" line at the top.

Format (copy `0001-record-architecture-decisions.md`):

```
# ADR-NNNN: <title>
Date: YYYY-MM-DD · Status: proposed | accepted | superseded by ADR-NNNN

## Context
What forces are at play (requirements, constraints, what exists today).

## Decision
What we chose, in one or two sentences.

## Alternatives considered
- Option A — why not
- Option B — why not

## Consequences
What becomes easier, what becomes harder, what we must watch.
```

## Index

| # | Title | Status | Milestone |
|---|-------|--------|-----------|
| 0001 | Record architecture decisions | accepted | 0 |
| 0002 | Postgres as the job queue (SKIP LOCKED) instead of Celery/Redis | accepted (implemented 2026-11-02, file pending) | 3 |
| 0003 | Prompts are versioned markdown files with front-matter | accepted (implemented 2026-11-02, file pending) | 1 |
| 0004 | Integration tests use a real Postgres (compose test DB; testcontainers optional) | accepted (implemented 2026-11-02, file pending) | 1 |
| 0005 | Structured LLM output; parse failures are errors | accepted (implemented 2026-11-02, file pending) | 1 |
| 0006 | One LangGraph per chunk; thread_id = book:index; Postgres checkpointer | accepted (graph 2026-11-02, checkpointer + kill test 2026-11-03, file pending) | 1 |
| 0007 | Judge model is never the translating model family | planned | 2 |
| 0008 | Quranic verses are passed through, never machine-translated | accepted (implemented 2026-11-02, file pending) | 3 |
| 0009 | Glossary lookup: pgvector with trigram fallback | planned | 4 |
| 0010 | DOCX export before PDF export | accepted (implemented 2026-11-02, file pending) | 5 |
| [0011](0011-free-ocr-ladder.md) | Free OCR ladder first; vision models only for poor pages | accepted (implemented 2026-11-09) | 6 |
| [0012](0012-bring-your-own-key.md) | Bring your own key, stored encrypted in the database | accepted (implemented 2026-11-09) | 6 |
| [0013](0013-agent-strategy-by-model-size.md) | One graph, scaffolding chosen by model size | accepted (implemented 2026-11-09) | 6 |
