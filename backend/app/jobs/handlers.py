"""Map job kinds to service functions. The worker calls ``run_job``.

``get_provider`` is the one place that turns configuration (``.env`` plus the
Settings screen) into an ``LLMProvider``. It re-reads the stored settings at
most every few seconds, so a key pasted into the UI reaches a worker running
in another process without a restart.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.config import settings
from app.core.database import session_scope
from app.llm.provider import (
    FakeProvider,
    LLMConfigError,
    LLMProvider,
    RuntimeLlm,
    build_provider,
    runtime_from_settings,
)
from app.llm.recorder import record_llm_call
from app.models.base import JobKind
from app.models.job import Job
from app.services import export as export_service
from app.services import extraction as extraction_service
from app.services import translation as translation_service

logger = logging.getLogger(__name__)

ProgressCb = Callable[[float, str], Awaitable[None]]

_REFRESH_SECONDS = 5.0


class _Cache:
    provider: LLMProvider | None = None
    runtime: RuntimeLlm | None = None
    fingerprint: str = ""
    checked_at: float = 0.0
    configured: bool = False
    error: str | None = None


_cache = _Cache()


async def _load_runtime() -> RuntimeLlm:
    try:
        from app.services import settings as settings_service

        async with session_scope() as session:
            return await settings_service.load_runtime(session)
    except Exception as exc:  # table missing (fresh DB before migrate), DB down
        logger.debug("runtime settings unavailable (%s); using .env", exc)
        return runtime_from_settings(settings)


async def get_provider(force: bool = False) -> LLMProvider:
    """One provider per process, rebuilt when the configuration changes.
    Falls back to the fake provider with a loud warning when the configured
    one has no credentials, so the app still runs end-to-end in demo mode."""
    now = time.monotonic()
    if _cache.provider is not None and not force and now - _cache.checked_at < _REFRESH_SECONDS:
        return _cache.provider
    runtime = await _load_runtime()
    fingerprint = runtime.fingerprint()
    if _cache.provider is None or force or fingerprint != _cache.fingerprint:
        try:
            provider = build_provider(runtime, cfg=settings, recorder=record_llm_call)
            _cache.configured = True
            _cache.error = None
        except LLMConfigError as exc:
            logger.warning(
                "LLM provider %r not configured (%s); using fake provider", runtime.provider, exc
            )
            provider = FakeProvider(cfg=settings, recorder=record_llm_call)
            _cache.configured = False
            _cache.error = str(exc)
        _cache.provider = provider
        _cache.runtime = runtime
        _cache.fingerprint = fingerprint
        if fingerprint != "" and _cache.provider is not None:
            logger.info("LLM provider: %s / %s (%s)", provider.name, provider.model, runtime.source)
    _cache.checked_at = now
    return _cache.provider  # type: ignore[return-value]


def provider_status() -> dict[str, Any]:
    return {
        "configured": _cache.configured,
        "error": _cache.error,
        "runtime": _cache.runtime,
    }


def reset_provider_cache() -> None:
    _cache.provider = None
    _cache.runtime = None
    _cache.fingerprint = ""
    _cache.checked_at = 0.0


async def run_job(job: Job, progress: ProgressCb) -> dict[str, Any]:
    payload = job.payload or {}
    provider = await get_provider()
    if job.kind == JobKind.extraction:
        return await extraction_service.run_extraction(job.book_id, provider, progress)
    if job.kind == JobKind.translation:
        return await translation_service.run_translation(
            job.book_id,
            provider,
            progress,
            page_range=payload.get("page_range"),
            only_failed=bool(payload.get("only_failed", False)),
            chunk_indexes=payload.get("chunk_indexes"),
        )
    if job.kind == JobKind.export:
        return await export_service.run_export(job.book_id, progress, payload.get("format", "docx"))
    raise RuntimeError(f"no handler for job kind {job.kind}")
