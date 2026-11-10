# ADR-0006: One LangGraph per chunk, checkpointed in Postgres
Date: 2026-11-02 · Status: accepted (graph 2026-11-02, checkpointer and kill test 2026-11-03; `backend/app/agents/chunk_graph.py`, `checkpoint.py`, `tests/test_kill_resume.py`)

## Context
Translating a chunk is a small workflow (translate, check, review, maybe retry, flag terms) with paid calls at each step. A 400-page book has over a thousand chunks and runs for hours. Workers crash, laptops sleep, providers time out. Re-running a whole book, or even a whole chunk, after a failure in its last step wastes money and time.

## Decision
Compile one LangGraph per translation job and invoke it once per chunk with `thread_id = "{book_id}:{chunk_index}"`. A Postgres checkpointer (`langgraph-checkpoint-postgres`, same database) saves state after every node. On the next attempt, `run_chunk` resumes an unfinished checkpoint for the same source text at the failed node, or reuses a finished but unpersisted one. A checkpoint for different text (the book was re-extracted) is ignored. Checkpoints are deleted once the result is safely in the `chunk` row. The graph itself stays pure: persistence happens in the service layer, so it is unit-testable with the fake provider.

## Alternatives considered
- **A plain async function per chunk**: simple, but a crash in review repays for the translation.
- **One graph per book**: one huge state, and a resume granularity that is too coarse.
- **Redis or file checkpoints**: another moving part; Postgres is already the source of truth (ADR-0002).

## Consequences
- Easier: a worker hard-killed during review resumes at review. `test_kill_resume.py` asserts in CI that every chunk was translated exactly once and that the log shows `resuming at ('verify',)`.
- Harder: on Windows, async psycopg needs a selector event loop (`app.core.eventloop`). Checkpoint tables must be cleaned between tests.
