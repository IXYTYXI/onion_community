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


def test_copy_stats_deduplicate_users_accumulate_copies_and_require_csrf(client, app, token):
    from app.schemas.auth import Department, Principal
    from app.services.browser_auth import SESSION_COOKIE, csrf_token

    client.cookies.clear()
    assert client.get("/api/v1/ows-release/copy-stats").status_code == 401
    assert client.post("/api/v1/ows-release/copy-stats").status_code == 401

    def login_as(uid, name, dept="研发部"):
        principal = Principal(
            user_id=f"feishu:app:{uid}",
            tenant_id="tenant",
            display_name=name,
            identity_source="feishu",
            departments=[Department(department_id="d1", name=dept)],
        )
        return client.portal.call(app.state.auth.issue, principal).access_token

    alice = login_as("ou_alice", "张三")
    bob = login_as("ou_bob", "李四", "产品部")

    initial = client.get("/api/v1/ows-release/copy-stats", headers=auth(alice)).json()["data"]
    assert initial == {"unique_users": 0, "total_copies": 0, "my_copies": 0}

    first = client.post("/api/v1/ows-release/copy-stats", headers=auth(alice), json={"cli_version": "0.1.8"}).json()["data"]
    assert first == {"unique_users": 1, "total_copies": 1, "my_copies": 1}

    second = client.post("/api/v1/ows-release/copy-stats", headers=auth(alice), json={"cli_version": "0.1.8"}).json()["data"]
    assert second == {"unique_users": 1, "total_copies": 2, "my_copies": 2}

    # Cookie-authenticated POST must enforce Origin + CSRF token.
    client.cookies.set(SESSION_COOKIE, bob)
    origin = {"Origin": app.state.settings.site_origin}
    assert client.post("/api/v1/ows-release/copy-stats", headers=origin).status_code == 403
    third = client.post(
        "/api/v1/ows-release/copy-stats",
        headers={**origin, "X-CSRF-Token": csrf_token(bob)},
        json={"cli_version": "v0.1.9"},
    ).json()["data"]
    assert third == {"unique_users": 2, "total_copies": 3, "my_copies": 1}


async def test_copy_stats_sync_to_feishu_and_import_existing_records(settings, tmp_path):
    from copy import deepcopy
    from app.schemas.auth import Department, Principal
    from app.services.ows_copy_stats import (
        ACCOUNT_FIELD, COUNT_FIELD, DEPT_FIELD, FIRST_AT_FIELD, KEY_FIELD,
        LAST_AT_FIELD, NAME_FIELD, VERSION_FIELD, OwsCopyStatsService, digest,
    )

    class FakeCopyTable:
        def __init__(self):
            self.rows = []
            self.creates = 0
            self.writes = []

        async def all_records(self, *, record_filter=None):
            if record_filter is None:
                return deepcopy(self.rows)
            [cond] = record_filter["conditions"]
            [val] = cond["value"]
            return deepcopy([r for r in self.rows if r["fields"].get(cond["field_name"]) == val])

        async def create_once(self, fields, client_token):
            self.creates += 1
            row = {"record_id": f"rec_{self.creates}", "fields": deepcopy(fields)}
            self.rows.append(row)
            return row

        async def write(self, records, *, update=False):
            assert update
            self.writes.extend(deepcopy(records))
            for item in records:
                target = next(r for r in self.rows if r["record_id"] == item["record_id"])
                target["fields"].update(item["fields"])
            return deepcopy(records)

    settings.feishu_app_id = "cli_app"
    settings.feishu_bitable_app_token = SecretStr("G4IDb5NF9awa0Hs1mn9cvRlNnGb")
    settings.ows_copy_stats_table_id = "tblFkqHq5BoYxpBB"
    table = FakeCopyTable()
    db_path = tmp_path / "copy.sqlite3"
    service = OwsCopyStatsService(settings, db_path, table)

    alice = Principal(
        user_id="feishu:cli_app:ou_alice",
        tenant_id="t1",
        display_name="王五",
        identity_source="feishu",
        departments=[Department(department_id="d1", name="组织效能")],
    )
    dev_user = Principal(
        user_id="dev-member",
        tenant_id="development",
        display_name="本地开发用户",
        identity_source="development",
    )

    await service.record_copy(alice, "0.1.8")
    await service.record_copy(alice, "0.1.9")
    await service.record_copy(dev_user, "0.1.9")  # Dev account never syncs to Feishu.
    assert await service.sync_once() == 1
    assert await service.sync_once() == 0
    assert len(table.rows) == 1
    saved = table.rows[0]["fields"]
    assert saved[NAME_FIELD] == "王五"
    assert saved[DEPT_FIELD] == "组织效能"
    assert saved[COUNT_FIELD] == 2
    assert saved[VERSION_FIELD] == "v0.1.9"
    assert saved[FIRST_AT_FIELD] <= saved[LAST_AT_FIELD]
    assert saved[KEY_FIELD] == digest(service.scope(), saved[ACCOUNT_FIELD])

    # Subsequent copy updates the existing Feishu row in place rather than creating duplicates.
    await service.record_copy(alice, "0.2.0")
    assert await service.sync_once() == 1
    assert table.creates == 1 and len(table.writes) == 1
    assert table.rows[0]["fields"][COUNT_FIELD] == 3
    assert table.rows[0]["fields"][VERSION_FIELD] == "v0.2.0"

    # Fresh SQLite file restores counts from the Feishu projection on first access.
    restored = OwsCopyStatsService(settings, tmp_path / "restored.sqlite3", table)
    summary = await restored.summary(alice)
    assert summary == {"unique_users": 1, "total_copies": 3, "my_copies": 3}


def test_known_site_base_binds_provisioned_ows_copy_stats_table(monkeypatch):
    from app.core.config import Settings

    args = dict(_env_file=None, news_sync_enabled=False)
    monkeypatch.setenv("OWS_COMMUNITY_FEISHU_BITABLE_APP_TOKEN", "G4IDb5NF9awa0Hs1mn9cvRlNnGb")
    monkeypatch.delenv("OWS_COMMUNITY_OWS_COPY_STATS_TABLE_ID", raising=False)
    assert Settings(**args).ows_copy_stats_table_id == "tblFkqHq5BoYxpBB"
    monkeypatch.setenv("OWS_COMMUNITY_OWS_COPY_STATS_TABLE_ID", "")
    assert Settings(**args).ows_copy_stats_table_id == ""
