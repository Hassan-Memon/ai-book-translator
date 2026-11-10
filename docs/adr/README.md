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

| # | Title | Status |
|---|-------|--------|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | accepted |
| [0002](0002-postgres-as-job-queue.md) | Postgres as the job queue (SKIP LOCKED) instead of Celery/Redis | accepted |
| [0003](0003-versioned-markdown-prompts.md) | Prompts are versioned markdown files with front-matter | accepted |
| [0004](0004-integration-tests-on-real-postgres.md) | Integration tests run on a real Postgres | accepted |
| [0005](0005-structured-output-parse-failures-are-errors.md) | Typed LLM output; a parse failure is an error | accepted |
| [0006](0006-one-langgraph-per-chunk.md) | One LangGraph per chunk, checkpointed in Postgres | accepted |
| [0007](0007-judge-not-same-family.md) | The evaluation judge is never from the translator's family | planned |
| [0008](0008-passthrough-content.md) | Some content is passed through, never machine-translated | accepted |
| [0009](0009-glossary-lookup.md) | Glossary lookup: trigram now, embeddings later | partially implemented |
| [0010](0010-docx-before-pdf.md) | Export DOCX before PDF | accepted |
| [0011](0011-free-ocr-ladder.md) | Free OCR ladder first; vision models only for poor pages | accepted |
| [0012](0012-bring-your-own-key.md) | Bring your own key, stored encrypted in the database | accepted |
| [0013](0013-agent-strategy-by-model-size.md) | One graph, scaffolding chosen by model size | accepted |

| [0014](0014-evaluation-harness-in-the-app.md) | The evaluation harness lives in the app and runs the product's own graph | accepted |
| [0015](0015-cloudflare-pages-plus-tunnel.md) | Cloudflare Pages for the web app, a tunnel to the machine for everything else | accepted |

New records start at 0016.
