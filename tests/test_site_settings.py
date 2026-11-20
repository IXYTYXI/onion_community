from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr

from app.core.errors import AppError
from app.schemas.auth import Principal
from app.services.site_settings import SHANGHAI, SiteState, Switches


def row(visitors="1", ledger="1", personal="01"):
    return [{"fields": {"配置名称": [{"text": "生产配置"}], "访客统计展示": visitors,
                        "账本同步": ledger, "个人列表展示": personal}}]


@pytest.mark.asyncio
async def test_hidden_visitors_still_count_deduplicated_across_midnight_and_instances(settings):
    source = AsyncMock()
    state = SiteState(settings, source)
    account = Principal(identity_source="feishu", tenant_id="tenant", user_id="one", display_name="User")
    other = account.model_copy(update={"user_id": "two"})
    midnight = int(datetime(2026,11,21,tzinfo=SHANGHAI).timestamp())
    source.all_records.return_value = row("0")
    await state.refresh()
    for _ in range(2):
        assert (await state.visitors(account, True, midnight - 100))["counts"] is None
    source.all_records.return_value = row()
    reopened = SiteState(settings, source)
    await reopened.refresh()
    assert (await state.visitors(other, True, midnight))["counts"] == {"total":2,"today":1,"online":2}
    assert (await state.visitors(account, False, midnight + 200))["counts"] == {"total":2,"today":1,"online":1}
    assert (await state.visitors(account, True, midnight + 300))["counts"] == {"total":2,"today":2,"online":1}
    source.all_records.return_value = row("1","2")
    with pytest.raises(AppError):
        await reopened.refresh()
    assert await state.current() == Switches(True, True, "01")


def test_hook_requires_dedicated_token_reloads_from_source_and_protects_counts(app, client, token):
    site = app.state.site
    site.source = AsyncMock()
    site.source.all_records.return_value = row("1", "0", "10")
    app.state.settings.site_switch_webhook_token = SecretStr("test-site-hook")
    url = "/api/v1/site-settings/webhook"
    assert client.post(url, headers={"Authorization": "Bearer " + token}).status_code == 401
    assert client.post(url, headers={"Authorization": "Bearer test-site-hook"}, json={"ledger": True}).status_code == 200
    assert client.portal.call(site.current) == Switches(True, False, "10")
    client.cookies.clear()
    assert client.get("/api/v1/visitors").status_code == 401
    res = client.post("/api/v1/visitors", headers={"Authorization":"Bearer " + token})
    assert res.json()["data"] == {"counts":{"total":0,"today":0,"online":0},"personal_lists":"10"}
