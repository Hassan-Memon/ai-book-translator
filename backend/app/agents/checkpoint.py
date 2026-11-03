"""LangGraph checkpointer factory (ADR-0006).

The per-chunk graph saves a checkpoint after every node under
``thread_id = "{book_id}:{chunk_index}"``. If the worker dies or a node raises
mid-chunk, the next attempt resumes at the failed node instead of paying for
``translate`` again. Successful threads are deleted once the result is
persisted, so the checkpoint tables only ever hold in-flight or failed chunks.

``CHECKPOINTER`` setting:
- ``postgres`` (default): durable, shares the app database (tables
  ``checkpoints``, ``checkpoint_blobs``, ``checkpoint_writes``, ``checkpoint_migrations``).
- ``memory``: per-process, for tests and experiments.
- ``none``: no checkpointing (the pre-1.6 behaviour).

A checkpointer that cannot start never blocks translation: we log a warning and
run without one.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from app.core.config import Settings, settings

logger = logging.getLogger(__name__)


def psycopg_url(sqlalchemy_url: str) -> str:
    """'postgresql+asyncpg://…' → 'postgresql://…' (libpq form for psycopg)."""
    return sqlalchemy_url.replace("+asyncpg", "").replace("+psycopg", "")


@asynccontextmanager
async def open_checkpointer(cfg: Settings | None = None) -> AsyncIterator[Any | None]:
    cfg = cfg or settings
    kind = (cfg.checkpointer or "none").lower()
    if kind == "none":
        yield None
        return
    if kind == "memory":
        from langgraph.checkpoint.memory import InMemorySaver

        yield InMemorySaver()
        return
    if kind != "postgres":
        raise ValueError(f"unknown CHECKPOINTER={kind!r}; use postgres, memory or none")

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    pool = AsyncConnectionPool(
        psycopg_url(cfg.database_url),
        min_size=1,
        max_size=max(2, cfg.translation_concurrency + 1),
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=False,
    )
    try:
        await pool.open(wait=True, timeout=10)
        saver = AsyncPostgresSaver(pool)  # type: ignore[arg-type]
        await saver.setup()
    except Exception as exc:
        logger.warning(
            "checkpointer unavailable (%s: %s); running without one", type(exc).__name__, exc
        )
        await pool.close()
        yield None
        return
    try:
        yield saver
    finally:
        await pool.close()
