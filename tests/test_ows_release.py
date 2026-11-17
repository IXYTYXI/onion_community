import asyncio
from unittest.mock import AsyncMock
from types import SimpleNamespace

import httpx
from pydantic import SecretStr

from app.api import ows_release
from app.repositories.store import MemoryStore


def manifest(version="0.1.2"):
    return {
        "schema_version": 1,
        "release_id": f"{version}-release",
        "cli_version": version,
        "python": ">=3.11",
        "platforms": ["macOS", "Linux"],
        "skills": ["ows-knowledge", "ows-upload"],
        "service_origin": "http://private.internal:9014",
        "release_notes": [{"version": version, "date": "2026-11-17", "title": "登录提示更清楚",
                           "changes": [{"category": "修复", "text": "说明重新连接的方法。"}]}],
    }


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_release_hook_updates_cached_page_data_without_exposing_internal_fields(client, app, token):
    app.state.settings.ows_release_webhook_token = SecretStr("publisher-secret")
    upstream = AsyncMock(side_effect=[httpx.Response(200, json=manifest()),
                                      httpx.Response(200, json=manifest("0.1.3"))])
    app.state.release_http.get = upstream

    first = client.get("/api/v1/ows-release", headers=auth(token))
    assert first.status_code == 200
    assert first.json()["data"]["cli_version"] == "0.1.2"
    assert "service_origin" not in first.text
    assert client.post("/api/v1/ows-release/webhook").status_code == 401
    assert client.post("/api/v1/ows-release/webhook", headers=auth("wrong")).status_code == 401

    updated = client.post("/api/v1/ows-release/webhook", headers=auth("publisher-secret"))
    assert updated.status_code == 200
    assert updated.json()["data"]["release_id"] == "0.1.3-release"
    current = client.get("/api/v1/ows-release", headers=auth(token))
    assert current.json()["data"]["cli_version"] == "0.1.3"
    assert upstream.await_count == 2


def test_invalid_release_does_not_replace_current_version(client, app, token):
    app.state.settings.ows_release_webhook_token = SecretStr("publisher-secret")
    upstream = AsyncMock(side_effect=[httpx.Response(200, json=manifest()),
                                      httpx.Response(200, json={**manifest("0.1.3"), "release_notes": []})])
    app.state.release_http.get = upstream
    assert client.get("/api/v1/ows-release", headers=auth(token)).status_code == 200
    assert client.post("/api/v1/ows-release/webhook", headers=auth("publisher-secret")).status_code == 502
    assert client.get("/api/v1/ows-release", headers=auth(token)).json()["data"]["cli_version"] == "0.1.2"


def test_published_files_are_limited_to_the_two_fixed_sources(client, app, token):
    body = b"# OWS install\n"
    app.state.release_http.get = AsyncMock(side_effect=[httpx.Response(200, content=body),
                                                          httpx.Response(200, content=b'{"version":"0.1.2"}')])
    guide = client.get("/api/v1/ows-release/files/ows-install.md", headers=auth(token))
    assert guide.status_code == 200
    assert guide.content == body
    assert guide.headers["Cache-Control"] == "no-store"
    manifest = client.get("/api/v1/ows-release/files/ows-release.json", headers=auth(token))
    assert manifest.status_code == 200
    assert manifest.content == b'{"version":"0.1.2"}'
    assert client.get("/api/v1/ows-release/files/other.md", headers=auth(token)).status_code == 404
    assert app.state.release_http.get.await_count == 2


def test_open_page_event_stream_receives_hook_updated_release(monkeypatch):
    async def scenario():
        store = MemoryStore()
        await store.set(ows_release.RELEASE_KEY, ows_release.ReleaseView.model_validate(manifest()).model_dump_json())
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(store=store)),
                                  is_disconnected=AsyncMock(return_value=False))

        async def no_wait(_seconds):
            return None

        monkeypatch.setattr(ows_release.asyncio, "sleep", no_wait)
        response = await ows_release.events(request)
        stream = response.body_iterator
        assert "0.1.2-release" in await anext(stream)
        await store.set(ows_release.RELEASE_KEY, ows_release.ReleaseView.model_validate(manifest("0.1.3")).model_dump_json())
        assert "0.1.3-release" in await anext(stream)
        await stream.aclose()

    asyncio.run(scenario())
