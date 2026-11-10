"""Settings, catalog, languages and OCR status routes.

Everything the Settings screen and the upload wizard need:

- ``GET  /settings``                 effective provider summary (nav badge)
- ``GET  /settings/llm``             full LLM config (masked key) + catalog
- ``PUT  /settings/llm``             save bring-your-own-key configuration
- ``DELETE /settings/llm``           back to the .env defaults
- ``POST /settings/llm/test``        try a tiny call with a (possibly unsaved) config
- ``GET  /settings/llm/models``      models a provider can serve (live for local)
- ``GET  /settings/local-runtimes``  which local servers answer right now
- ``GET  /settings/ocr``             OCR engines, installed language packs
- ``GET  /languages``                the language registry
- ``GET  /strategy``                 the agent strategy the current model gets
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import strategy as strategy_mod
from app.core.config import APP_VERSION, settings
from app.core.database import get_session
from app.core.languages import all_languages
from app.jobs.handlers import get_provider, provider_status, reset_provider_cache
from app.llm.catalog import model_tier
from app.pipeline.ocr import ocr_status
from app.schemas.book import AppSettingsResponse, LlmSettingsRequest, LlmTestRequest
from app.services import settings as settings_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")


@router.get("/settings", response_model=AppSettingsResponse)
async def app_settings() -> AppSettingsResponse:
    provider = await get_provider()
    status_info = provider_status()
    runtime = status_info.get("runtime")
    return AppSettingsResponse(
        llm_provider=provider.name,
        model=provider.model,
        worker_inline=settings.worker_inline,
        version=APP_VERSION,
        provider_configured=bool(status_info.get("configured")),
        provider_label=(runtime.spec.label if runtime and runtime.spec else provider.name),
        model_tier=model_tier(provider.model),
        supports_vision=provider.supports_vision(),
        is_local=bool(getattr(provider, "is_local", False)),
        source=runtime.source if runtime else "env",
    )


@router.get("/settings/llm")
async def get_llm_settings(session: AsyncSession = Depends(get_session)):
    runtime = await settings_service.load_runtime(session)
    status_info = provider_status()
    configured = bool(status_info.get("configured")) if status_info.get("runtime") else True
    payload = settings_service.public_view(
        runtime, configured=configured, error=status_info.get("error")
    )
    payload["catalog"] = settings_service.catalog_payload()
    payload["strategy"] = strategy_mod.resolve(
        runtime.model, cfg=settings, is_local=runtime.is_local
    ).as_dict()
    return payload


@router.put("/settings/llm")
async def put_llm_settings(body: LlmSettingsRequest, session: AsyncSession = Depends(get_session)):
    try:
        runtime = await settings_service.save_runtime(session, body.model_dump())
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    reset_provider_cache()
    await get_provider(force=True)
    status_info = provider_status()
    payload = settings_service.public_view(
        runtime, configured=bool(status_info.get("configured")), error=status_info.get("error")
    )
    payload["strategy"] = strategy_mod.resolve(
        runtime.model, cfg=settings, is_local=runtime.is_local
    ).as_dict()
    return payload


@router.delete("/settings/llm", status_code=status.HTTP_204_NO_CONTENT)
async def reset_llm_settings(session: AsyncSession = Depends(get_session)) -> None:
    await settings_service.reset_runtime(session)
    reset_provider_cache()


@router.post("/settings/llm/test")
async def test_llm_settings(body: LlmTestRequest, session: AsyncSession = Depends(get_session)):
    stored = await settings_service.load_runtime(session)
    runtime = settings_service.runtime_from_body(body.model_dump(), stored)
    if runtime.spec is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown provider {runtime.provider!r}")
    return await settings_service.test_connection(runtime)


@router.get("/settings/llm/models")
async def llm_models(
    provider: str = Query(...),
    base_url: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    stored = await settings_service.load_runtime(session)
    api_key = stored.api_key if stored.provider == provider else None
    try:
        return await settings_service.list_models(provider, base_url, api_key)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/settings/local-runtimes")
async def local_runtimes():
    return {"runtimes": await settings_service.detect_local_runtimes()}


@router.get("/settings/ocr")
async def ocr_settings():
    return ocr_status(settings)


@router.get("/languages")
async def languages():
    return {"languages": all_languages()}


@router.get("/strategy")
async def strategy(model: str | None = Query(None)):
    provider = await get_provider()
    name = model or provider.model
    return {
        "model": name,
        "strategy": strategy_mod.resolve(
            name, cfg=settings, is_local=bool(getattr(provider, "is_local", False))
        ).as_dict(),
    }
