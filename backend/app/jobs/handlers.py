"""Map job kinds to service functions. The worker calls ``run_job``."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.config import settings
from app.llm.provider import FakeProvider, LLMConfigError, LLMProvider, get_llm_provider
from app.llm.recorder import record_llm_call
from app.models.base import JobKind
from app.models.job import Job
from app.services import export as export_service
from app.services import extraction as extraction_service
from app.services import translation as translation_service

logger = logging.getLogger(__name__)

ProgressCb = Callable[[float, str], Awaitable[None]]

_provider_cache: dict[str, LLMProvider] = {}


def get_provider() -> LLMProvider:
    """One provider per process. Falls back to the fake provider with a loud
    warning when the configured one has no credentials, so the app still
    runs end-to-end in demo mode."""
    key = settings.llm_provider
    if key not in _provider_cache:
        try:
            _provider_cache[key] = get_llm_provider(settings, recorder=record_llm_call)
        except LLMConfigError as exc:
            logger.warning("LLM provider %r not configured (%s); using fake provider", key, exc)
            _provider_cache[key] = FakeProvider(cfg=settings, recorder=record_llm_call)
    return _provider_cache[key]


def reset_provider_cache() -> None:
    _provider_cache.clear()


async def run_job(job: Job, progress: ProgressCb) -> dict[str, Any]:
    payload = job.payload or {}
    if job.kind == JobKind.extraction:
        return await extraction_service.run_extraction(job.book_id, get_provider(), progress)
    if job.kind == JobKind.translation:
        return await translation_service.run_translation(
            job.book_id,
            get_provider(),
            progress,
            page_range=payload.get("page_range"),
            only_failed=bool(payload.get("only_failed", False)),
            chunk_indexes=payload.get("chunk_indexes"),
        )
    if job.kind == JobKind.export:
        return await export_service.run_export(job.book_id, progress, payload.get("format", "docx"))
    raise RuntimeError(f"no handler for job kind {job.kind}")
