"""Runtime LLM settings: bring-your-own-key, local models, test connection.

Precedence: values saved from the Settings screen (``app_setting.llm``)
override ``.env``; ``.env`` is the default for a fresh install. API keys are
encrypted at rest (:mod:`app.core.secrets`) and never sent back to the
browser, only a masked hint.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import secrets
from app.core.config import settings
from app.core.database import session_scope
from app.llm.catalog import (
    model_supports_vision,
    model_tier,
    provider_spec,
    serialize_local_recommendations,
    serialize_providers,
)
from app.llm.provider import (
    LLMConfigError,
    LLMError,
    RuntimeLlm,
    build_provider,
    runtime_from_settings,
)
from app.models.app_setting import AppSetting

logger = logging.getLogger(__name__)

LLM_KEY = "llm"
_SECRET_FIELDS = ("api_key",)


async def _get_row(session: AsyncSession, key: str) -> AppSetting | None:
    return (
        (await session.execute(select(AppSetting).where(AppSetting.key == key))).scalars().first()
    )


async def load_runtime(session: AsyncSession) -> RuntimeLlm:
    """Effective configuration: UI settings when saved, else .env."""
    env = runtime_from_settings(settings)
    row = await _get_row(session, LLM_KEY)
    if row is None or not row.value or not row.value.get("provider"):
        return env
    stored = row.value
    provider = str(stored.get("provider") or env.provider)
    spec = provider_spec(provider)
    api_key = secrets.decrypt(stored.get("api_key")) or None
    if api_key is None and provider == env.provider:
        api_key = env.api_key  # UI chose the same provider; keep the env key
    return RuntimeLlm(
        provider=provider,
        model=str(stored.get("model") or (spec.default_model if spec else "")),
        api_key=api_key,
        base_url=stored.get("base_url") or (env.base_url if provider == env.provider else None),
        vision_model=stored.get("vision_model") or None,
        temperature=stored.get("temperature"),
        max_output_tokens=stored.get("max_output_tokens"),
        source="ui",
    )


async def runtime_version(session: AsyncSession) -> str:
    """Cheap change detector for provider caches in other processes."""
    row = await _get_row(session, LLM_KEY)
    return row.updated_at.isoformat() if row is not None else "env"


def public_view(
    runtime: RuntimeLlm, *, configured: bool, error: str | None = None
) -> dict[str, Any]:
    spec = runtime.spec
    return {
        "provider": runtime.provider,
        "provider_label": spec.label if spec else runtime.provider,
        "model": runtime.model,
        "base_url": runtime.base_url or (spec.base_url if spec else None),
        "vision_model": runtime.vision_model,
        "temperature": runtime.temperature,
        "max_output_tokens": runtime.max_output_tokens,
        "api_key_hint": secrets.mask(runtime.api_key),
        "has_api_key": bool(runtime.api_key),
        "needs_key": bool(spec and spec.needs_key),
        "is_local": runtime.is_local,
        "model_tier": model_tier(runtime.model),
        "supports_vision": model_supports_vision(runtime.vision_model or runtime.model),
        "source": runtime.source,
        "configured": configured,
        "error": error,
    }


async def save_runtime(session: AsyncSession, body: dict[str, Any]) -> RuntimeLlm:
    """Persist UI settings. ``api_key`` None keeps the stored key, '' clears it."""
    provider = str(body.get("provider") or "").lower().strip()
    spec = provider_spec(provider)
    if spec is None:
        raise ValueError(f"unknown provider {provider!r}")
    row = await _get_row(session, LLM_KEY)
    current: dict[str, Any] = dict(row.value) if row is not None else {}
    value: dict[str, Any] = {
        "provider": provider,
        "model": (body.get("model") or spec.default_model or "").strip(),
        "base_url": (body.get("base_url") or "").strip() or None,
        "vision_model": (body.get("vision_model") or "").strip() or None,
        "temperature": body.get("temperature"),
        "max_output_tokens": body.get("max_output_tokens"),
    }
    api_key = body.get("api_key")
    if api_key is None:
        # keep the previous key only if it belongs to the same provider
        value["api_key"] = current.get("api_key") if current.get("provider") == provider else None
    elif api_key == "":
        value["api_key"] = None
    else:
        value["api_key"] = secrets.encrypt(str(api_key).strip())
    if row is None:
        row = AppSetting(key=LLM_KEY, value=value)
        session.add(row)
    else:
        row.value = value
    await session.commit()
    return await load_runtime(session)


async def reset_runtime(session: AsyncSession) -> None:
    row = await _get_row(session, LLM_KEY)
    if row is not None:
        await session.delete(row)
        await session.commit()


def runtime_from_body(body: dict[str, Any], stored: RuntimeLlm | None) -> RuntimeLlm:
    """Build a runtime for 'Test connection' without saving: an omitted key
    means 'use the one already stored for this provider'."""
    provider = str(body.get("provider") or "").lower().strip()
    spec = provider_spec(provider)
    api_key = body.get("api_key")
    if api_key is None and stored is not None and stored.provider == provider:
        api_key = stored.api_key
    env = runtime_from_settings(settings)
    if not api_key and env.provider == provider:
        api_key = env.api_key
    return RuntimeLlm(
        provider=provider,
        model=str(body.get("model") or (spec.default_model if spec else "")),
        api_key=api_key or None,
        base_url=(body.get("base_url") or None),
        vision_model=body.get("vision_model") or None,
        temperature=body.get("temperature"),
        max_output_tokens=body.get("max_output_tokens"),
        source="test",
    )


async def test_connection(runtime: RuntimeLlm) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        provider = build_provider(runtime, cfg=settings, recorder=None)
        reply = await provider.aping()
    except LLMConfigError as exc:
        return {"ok": False, "stage": "config", "error": str(exc)}
    except LLMError as exc:
        return {"ok": False, "stage": "call", "error": str(exc)[:500]}
    except Exception as exc:  # pragma: no cover - defensive
        return {"ok": False, "stage": "call", "error": f"{type(exc).__name__}: {exc}"[:500]}
    return {
        "ok": True,
        "reply": reply,
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "model": runtime.model,
        "supports_vision": provider.supports_vision(),
        "model_tier": model_tier(runtime.model),
        "is_local": provider.is_local,
    }


async def list_models(provider: str, base_url: str | None, api_key: str | None) -> dict[str, Any]:
    """Models the provider can serve right now. Local runtimes are queried
    live; cloud providers return the catalog suggestions."""
    spec = provider_spec(provider)
    if spec is None:
        raise ValueError(f"unknown provider {provider!r}")
    url = (base_url or spec.base_url or "").rstrip("/")
    try:
        if spec.kind == "ollama":
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{url}/api/tags")
                r.raise_for_status()
                models = []
                for m in r.json().get("models", []):
                    name = m.get("name") or m.get("model")
                    details = m.get("details") or {}
                    models.append(
                        {
                            "id": name,
                            "size_gb": round((m.get("size") or 0) / 1e9, 1),
                            "params": details.get("parameter_size"),
                            "family": details.get("family"),
                            "tier": model_tier(name or ""),
                            "vision": model_supports_vision(name or ""),
                        }
                    )
                return {"source": "live", "models": models, "running": True}
        if spec.kind == "openai" and (spec.local or spec.custom_base_url):
            headers = {"Authorization": f"Bearer {api_key or 'not-needed'}"}
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{url}/models", headers=headers)
                r.raise_for_status()
                data = r.json().get("data", [])
                models = [
                    {
                        "id": m.get("id"),
                        "tier": model_tier(m.get("id", "")),
                        "vision": model_supports_vision(m.get("id", "")),
                    }
                    for m in data
                    if m.get("id")
                ]
                return {"source": "live", "models": models, "running": True}
    except Exception as exc:
        return {
            "source": "live",
            "models": [],
            "running": False,
            "error": f"{spec.label} is not reachable at {url}: {type(exc).__name__}",
        }
    return {
        "source": "catalog",
        "models": [
            {"id": m, "tier": model_tier(m), "vision": model_supports_vision(m)}
            for m in spec.models
        ],
        "running": None,
    }


def catalog_payload() -> dict[str, Any]:
    return {
        "providers": serialize_providers(),
        "local_recommendations": serialize_local_recommendations(),
    }


async def detect_local_runtimes() -> list[dict[str, Any]]:
    """Which local servers answer right now (for the Settings screen banner)."""
    found: list[dict[str, Any]] = []
    probes = (
        ("ollama", f"{settings.ollama_base_url.rstrip('/')}/api/tags"),
        ("lmstudio", f"{settings.lmstudio_base_url.rstrip('/')}/models"),
    )
    async with httpx.AsyncClient(timeout=1.5) as client:
        for provider, url in probes:
            try:
                r = await client.get(url)
                if r.status_code == 200:
                    payload = r.json()
                    names = [
                        m.get("name") or m.get("id")
                        for m in (payload.get("models") or payload.get("data") or [])
                    ]
                    found.append(
                        {"provider": provider, "url": url, "models": [n for n in names if n][:50]}
                    )
            except Exception:
                continue
    return found


async def current_runtime() -> RuntimeLlm:
    """Convenience for code outside a request (worker, CLI)."""
    async with session_scope() as session:
        return await load_runtime(session)
