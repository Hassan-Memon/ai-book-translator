# ADR-0004: Integration tests run on a real Postgres
Date: 2026-11-02 · Status: accepted (implemented in `backend/tests/conftest.py`, `docker/initdb/`, CI service container)

## Context
The job queue relies on `FOR UPDATE SKIP LOCKED`, the glossary on `pg_trgm`, the schema on Postgres enums and JSONB, and resume on the LangGraph Postgres checkpointer. SQLite or mocks would not exercise any of these, and the bugs worth catching (a session shared across tasks, a lock not released) only appear against the real database.

## Decision
Tests use a dedicated `translatebook_test` database on the same Postgres 17 + pgvector image as development. Docker Compose creates it through `docker/initdb/`, and CI runs it as a service container. The schema is built once per session with Alembic (downgrade to base, then upgrade to head, which also tests the migrations), and every table is truncated after each test. No test calls a real LLM: the deterministic `FakeProvider` stands in.

## Alternatives considered
- **SQLite in memory**: fast, but no `SKIP LOCKED`, enums, JSONB or trigram support.
- **Mocking the session**: tests the mocks, not the queries.
- **testcontainers**: equivalent isolation, but slower start-up and harder on Windows. It remains an option for contributors without Docker Compose.

## Consequences
- Easier: the kill-resume test, the queue-claim test and migration drift are all caught for real.
- Harder: tests need Docker running (`make test` starts the database). The suite takes about a minute instead of seconds.
