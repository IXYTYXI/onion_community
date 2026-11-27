import io
from datetime import datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from PIL import Image
from pydantic import SecretStr

from app.core.config import Settings
from app.core.errors import AppError
from app.schemas.auth import Principal
from app.services.activities import ACTIVITY_FIELDS, ActivityService, parse_links, parse_schedule
from app.services.browser_auth import safe_next
from conftest import DEV_KEY

SHANGHAI = ZoneInfo("Asia/Shanghai")


def sample_records():
    return [
        {
            "record_id": "rec_past_1",
            "fields": {
                "活动主题": [{"text": "豆包工作伙伴分享", "type": "text"}],
                "活动日期": 1795536000000,  # 2026-11-25 00:00:00+08:00
                "时间": [{"text": "11:00～12:30", "type": "text"}],
                "活动对象": "全员",
                "讲师": [{"text": "裴子江", "type": "text"}],
                "负责人": [{"name": "刘云澈", "id": "ou_admin"}],
                "地点": "北京 - 2层 - NASA",
                "报名链接": {"link": "https://guanghe.feishu.cn/share/base/form/shrcnPast", "text": "点击报名"},
                "日程链接": {"link": "https://applink.feishu.cn/client/calendar/event/detail?past=1", "text": "加入日程"},
                "文档资料": [
                    {"link": "https://guanghe.feishu.cn/docx/doc1", "text": "分享课件"},
                    {"link": "javascript:alert(1)", "text": "恶意链接"},
                ],
                "课程回放": {"link": "https://guanghe.feishu.cn/minutes/obcn1", "text": "https://guanghe.feishu.cn/minutes/obcn1"},
                "活动照片": [
                    {"file_token": "tok_photo_1", "name": "现场1.jpg", "type": "image/jpeg", "url": "https://open.feishu.cn/dl/1"},
                    {"file_token": "tok_photo_2", "name": "现场2.png", "type": "image/png", "url": "https://open.feishu.cn/dl/2"},
                    {"file_token": "tok_doc_ignore", "name": "说明.pdf", "type": "application/pdf", "url": "https://open.feishu.cn/dl/3"},
                ],
            },
        },
        {
            "record_id": "rec_upcoming_1",
            "fields": {
                "活动主题": "Agent 实战工作坊",
                "活动日期": "2026-12-10",
                "时间": "14:30-16:00",
                "活动对象": "产研团队",
                "讲师": "王老师",
                "地点": "线上飞书会议",
                "报名链接": "https://guanghe.feishu.cn/share/base/form/shrcnUpcoming",
                "日程链接": "https://applink.feishu.cn/client/calendar/event/detail?up=1",
            },
        },
    ]


@pytest.fixture
def activity_service(store, settings, tmp_path):
    settings.media_root = tmp_path
    source = AsyncMock()
    source.records.return_value = sample_records()
    return ActivityService(store, source, settings)


def test_activity_fields_match_existing_feishu_columns():
    assert ACTIVITY_FIELDS == [
        "活动主题",
        "活动日期",
        "时间",
        "活动对象",
        "讲师",
        "负责人",
        "地点",
        "报名链接",
        "日程链接",
        "文档资料",
        "课程回放",
        "活动照片",
    ]
    assert "活动简介" not in ACTIVITY_FIELDS
    assert "活动封面" not in ACTIVITY_FIELDS


def test_schedule_and_link_parsing():
    date_label, time_label, starts_at, ends_at = parse_schedule(1795536000000, "11:00～12:30")
    assert date_label == "2026-11-25"
    assert time_label == "11:00～12:30"
    assert starts_at == datetime(2026, 11, 25, 11, 0, tzinfo=SHANGHAI)
    assert ends_at == datetime(2026, 11, 25, 12, 30, tzinfo=SHANGHAI)

    d2, _, s2, e2 = parse_schedule("2026/12/05", "15:00")
    assert d2 == "2026-12-05"
    assert s2 == datetime(2026, 12, 5, 15, 0, tzinfo=SHANGHAI)
    assert e2 == datetime(2026, 12, 5, 16, 30, tzinfo=SHANGHAI)

    links = parse_links("飞书讲义|https://guanghe.feishu.cn/docx/a\n[实战手册](https://guanghe.feishu.cn/docx/b)\njavascript:alert(1)", "文档资料")
    assert [(link.title, link.url) for link in links] == [
        ("飞书讲义", "https://guanghe.feishu.cn/docx/a"),
        ("实战手册", "https://guanghe.feishu.cn/docx/b"),
    ]


def test_settings_auto_binds_activities_table_for_community_base():
    configured = Settings(_env_file=None, news_sync_enabled=False, feishu_bitable_app_token="G4IDb5NF9awa0Hs1mn9cvRlNnGb")
    assert configured.activities_table_id == "tbl5qzmoEEGPE20k"
    assert configured.activities_view_id == "vewpNqiXVt"

    overridden = Settings(
        _env_file=None,
        news_sync_enabled=False,
        feishu_bitable_app_token="G4IDb5NF9awa0Hs1mn9cvRlNnGb",
        activities_table_id="tbl_custom",
        activities_view_id="vew_custom",
    )
    assert overridden.activities_table_id == "tbl_custom"
    assert overridden.activities_view_id == "vew_custom"


async def test_normalize_caching_and_private_photo_revocation(activity_service, store):
    buffer = io.BytesIO()
    Image.new("RGB", (32, 24), "royalblue").save(buffer, format="JPEG")
    activity_service.source.download.return_value = buffer.getvalue()

    directory = await activity_service.read()
    assert len(directory.items) == 2
    past = directory.items[0]
    assert past.title == "豆包工作伙伴分享"
    assert past.speaker == "裴子江"
    assert past.replays[0].title == "课程回放"
    assert len(past.photos) == 2
    assert all(photo.url.startswith("/api/v1/activities/media/") for photo in past.photos)

    photo_id = past.photos[0].id
    saved_path = await activity_service.image(photo_id)
    assert saved_path.is_file()
    assert Image.open(saved_path).format == "WEBP"
    assert activity_service.source.download.await_count == 1

    # Once removed from Feishu snapshot, previously cached photo must no longer be served.
    updated_records = sample_records()
    updated_records[0]["fields"]["活动照片"] = []
    activity_service.source.records.return_value = updated_records
    await activity_service.force_refresh()
    with pytest.raises(AppError) as exc_info:
        await activity_service.image(photo_id)
    assert exc_info.value.code.value == "NOT_FOUND"


def test_activities_api_auth_tenant_page_and_webhook(client, app, activity_service):
    app.state.activities = activity_service
    app.state.settings.activities_webhook_token = SecretStr("test-activities-webhook-secret")

    # Unauthenticated checks
    assert safe_next("/activities.html?review=rec_past_1") == "/activities.html?review=rec_past_1"
    page_redirect = client.get("/activities.html", follow_redirects=False)
    assert page_redirect.status_code == 303
    assert page_redirect.headers["location"].startswith("/login.html?")
    assert client.get("/api/v1/activities").status_code == 401
    assert client.get("/api/v1/activities/media/" + "a" * 64).status_code == 401

    # Webhook checks (no user cookie required, strict bearer token required)
    assert client.post("/api/v1/activities/webhook").status_code == 401
    assert client.post("/api/v1/activities/webhook", headers={"Authorization": "Bearer wrong"}).status_code == 401
    webhook_ok = client.post(
        "/api/v1/activities/webhook",
        headers={"Authorization": "Bearer test-activities-webhook-secret"},
    )
    assert webhook_ok.status_code == 200
    assert webhook_ok.json()["data"]["updated"] is True
    assert webhook_ok.json()["data"]["count"] == 2

    # Authenticated checks
    assert client.post("/api/v1/auth/dev", headers={"X-Dev-Login-Key": DEV_KEY}).status_code == 200
    assert client.get("/activities.html").status_code == 200
    resp = client.get("/api/v1/activities")
    assert resp.status_code == 200
    assert len(resp.json()["data"]["items"]) == 2
    assert "file_token" not in resp.text and "open.feishu.cn" not in resp.text

    # Source tenant isolation check
    app.state.settings.activities_source_tenant = "tenant-guanghe"
    outsider = Principal(user_id="feishu:cli:out", tenant_id="tenant-other", display_name="外租户", identity_source="feishu")
    issued = client.portal.call(app.state.auth.issue, outsider)
    denied = client.get("/api/v1/activities", headers={"Authorization": f"Bearer {issued.access_token}"})
    assert denied.status_code == 403
