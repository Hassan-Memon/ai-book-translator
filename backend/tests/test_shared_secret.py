"""API_SHARED_SECRET: the gate used when the API is exposed through a tunnel."""

from __future__ import annotations

import httpx

from app.core.config import settings
from app.main import create_app

REMOTE = ("203.0.113.5", 40000)
LOCAL = ("127.0.0.1", 40000)


async def _get(
    path: str, headers: dict[str, str] | None = None, client: tuple[str, int] = REMOTE
) -> httpx.Response:
    transport = httpx.ASGITransport(app=create_app(), client=client)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        return await http.get(path, headers=headers or {})


async def test_api_is_open_without_a_secret(monkeypatch) -> None:
    monkeypatch.setattr(settings, "api_shared_secret", None)
    assert (await _get("/api/v1/languages")).status_code == 200


async def test_secret_required_for_remote_and_tunnel_traffic(monkeypatch) -> None:
    monkeypatch.setattr(settings, "api_shared_secret", "s3cret-value")
    assert (await _get("/api/v1/languages")).status_code == 401
    wrong = await _get("/api/v1/languages", {"X-TranslateBook-Key": "nope"})
    assert wrong.status_code == 401 and "API key" in wrong.json()["detail"]
    ok = await _get("/api/v1/languages", {"X-TranslateBook-Key": "s3cret-value"})
    assert ok.status_code == 200
    # A tunnel connects from localhost, but Cloudflare's headers give it away.
    tunnel = await _get("/api/v1/languages", {"Cf-Connecting-Ip": "198.51.100.7"}, client=LOCAL)
    assert tunnel.status_code == 401
    # Your own browser on the same machine keeps working without the key.
    assert (await _get("/api/v1/languages", client=LOCAL)).status_code == 200
    assert (await _get("/health")).status_code == 200
