"""One event-loop policy for every entrypoint (API, worker, CLI, tests).

Why: the LangGraph Postgres checkpointer runs on async psycopg, which cannot use
Windows' default ``ProactorEventLoop``. asyncpg (our SQLAlchemy driver) works on
either loop, so on Windows we always use a ``SelectorEventLoop``. On Linux and
macOS this is the normal default loop, so nothing changes in Docker/CI.

- worker / CLI:  ``eventloop.run(main())``
- uvicorn:       ``uvicorn app.main:app --loop app.core.eventloop:new_event_loop``
"""

from __future__ import annotations

import asyncio
import selectors
import sys
from collections.abc import Coroutine
from typing import Any


def new_event_loop() -> asyncio.AbstractEventLoop:
    if sys.platform == "win32":
        return asyncio.SelectorEventLoop(selectors.SelectSelector())
    return asyncio.new_event_loop()


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro, loop_factory=new_event_loop)
