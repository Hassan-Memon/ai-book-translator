# ADR-0002: Postgres as the job queue (SKIP LOCKED) instead of Celery/Redis
Date: 2026-11-02 · Status: accepted (implemented 2026-11-02; `backend/app/jobs/queue.py`, exclusive-claim test in `tests/test_jobs_and_services.py`)

## Context
Extraction, translation, and export are long-running (minutes to hours) and must be resumable,
observable, and retryable. Today they run inside FastAPI `BackgroundTasks` or inside the HTTP
request itself, which times out on large books and loses work on restart. The README promised
Celery. The whole product state already lives in PostgreSQL. One developer; must deploy with
minimal moving parts; expected load is tens of books per day, not thousands per minute.

## Decision
Use a `job` table as the queue. Workers claim with
`UPDATE job SET locked_by=…, locked_at=now(), status='running' WHERE id = (SELECT id FROM job WHERE status='queued' AND run_after <= now() ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *`.
Failed jobs are re-queued with exponential `run_after` until `max_attempts`. A heartbeat column
lets a sweeper reclaim jobs whose worker died. Per-chunk progress inside a translation job is
already persisted on `chunk.status` and in LangGraph checkpoints, so a re-run of the job is
idempotent.

## Alternatives considered
- **Celery + Redis/RabbitMQ** — mature, but adds a broker, a result backend, serialisation of
  SQLAlchemy objects, and operational surface; overkill below ~hundreds of jobs/minute.
- **arq / Dramatiq (Redis)** — lighter than Celery, still an extra service; same visibility issue
  (job state outside Postgres).
- **FastAPI BackgroundTasks** (current) — dies with the process; not resumable; no retries.
- **Cloud queues (SQS/Azure Queue)** — vendor lock-in for a demo; harder to run locally and in CI.

## Consequences
- Easier: one database to back up and inspect; `SELECT * FROM job` is the dashboard; CI can test
  the queue with the same testcontainers Postgres.
- Harder: we own retry/backoff/heartbeat logic (~150 lines, tested); polling adds ~1 s latency;
  at high throughput row contention would force a move to a broker. Documented ceiling: migrate
  when sustained queue depth > 10k or claim latency matters.
- Watch: long transactions holding locks; keep the claim transaction tiny and do the work outside it.
