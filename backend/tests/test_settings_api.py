"""Bring-your-own-key settings: encryption, persistence, API, catalog, languages."""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from app.core import secrets
from app.core.database import session_scope
from app.main import app
from app.services import settings as settings_service


def test_secrets_round_trip_and_mask() -> None:
    token = secrets.encrypt("sk-live-1234567890abcdef")
    assert token.startswith("enc:v1:") and "1234567890" not in token
    assert secrets.decrypt(token) == "sk-live-1234567890abcdef"
    assert secrets.decrypt("plain-legacy") == "plain-legacy"
    assert secrets.mask("sk-live-1234567890abcdef") == "sk-l••••def"
    assert secrets.mask(None) is None


async def test_runtime_settings_persist_with_encrypted_key() -> None:
    async with session_scope() as session:
        runtime = await settings_service.save_runtime(
            session,
            {"provider": "openai", "model": "gpt-4.1-mini", "api_key": "sk-test-key-000111"},
        )
        assert runtime.provider == "openai" and runtime.api_key == "sk-test-key-000111"
        assert runtime.source == "ui" and not runtime.is_local
        # omitted key keeps the stored one; empty string clears it
        runtime = await settings_service.save_runtime(
            session, {"provider": "openai", "model": "gpt-4.1"}
        )
        assert runtime.api_key == "sk-test-key-000111" and runtime.model == "gpt-4.1"
        runtime = await settings_service.save_runtime(
            session, {"provider": "openai", "api_key": ""}
        )
        assert runtime.api_key is None
        view = settings_service.public_view(runtime, configured=False)
        assert view["has_api_key"] is False and view["needs_key"] is True
        await settings_service.reset_runtime(session)
        assert (await settings_service.load_runtime(session)).source == "env"


async def test_settings_endpoints_and_catalog() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/languages")
        assert r.status_code == 200 and len(r.json()["languages"]) >= 45

        r = await client.get("/api/v1/settings/llm")
        body = r.json()
        assert r.status_code == 200
        assert {"providers", "local_recommendations"} <= set(body["catalog"])
        assert body["strategy"]["profile"] in ("fast", "balanced", "thorough")

        r = await client.put(
            "/api/v1/settings/llm",
            json={"provider": "ollama", "model": "qwen3:4b", "base_url": "http://localhost:11434"},
        )
        assert r.status_code == 200, r.text
        saved = r.json()
        assert (
            saved["provider"] == "ollama" and saved["is_local"] and saved["model_tier"] == "small"
        )
        assert saved["strategy"]["sentence_alignment"] is True

        r = await client.get("/api/v1/settings")
        assert r.json()["llm_provider"] == "ollama"

        r = await client.post(
            "/api/v1/settings/llm/test", json={"provider": "fake", "model": "fake-1"}
        )
        assert r.status_code == 200 and r.json()["ok"] is True and r.json()["reply"] == "OK"

        r = await client.get("/api/v1/settings/llm/models", params={"provider": "openai"})
        assert r.status_code == 200 and r.json()["source"] == "catalog"

        r = await client.get("/api/v1/settings/ocr")
        assert r.status_code == 200 and len(r.json()["engines"]) == 3

        r = await client.delete("/api/v1/settings/llm")
        assert r.status_code == 204
        r = await client.get("/api/v1/settings")
        assert r.json()["llm_provider"] == "fake"


def test_catalog_only_provider_reads_key_from_environment(monkeypatch) -> None:
    from app.core.config import settings
    from app.llm.provider import runtime_from_settings

    monkeypatch.setenv("GEMINI_API_KEY", "gm-test-123")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-pro")
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    runtime = runtime_from_settings(settings)
    assert runtime.api_key == "gm-test-123" and runtime.model == "gemini-2.5-pro"
