from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.config import Settings
from app.core.errors import AppError
from app.core.error_codes import ErrorCode
from app.main import create_app
from app.schemas.auth import Principal, SessionRecord
from conftest import DEV_KEY


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def assert_error(response, status, code):
    assert response.status_code == status
    body = response.json()
    assert body["code"] == code
    assert body["data"] is None
    assert isinstance(body["error"]["details"], list)
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert body["timestamp"]
    assert response.headers["Cache-Control"] == "no-store"


def test_health_and_request_id(client):
    response = client.get("/health/live", headers={"X-Request-ID": "test-trace-123"})
    assert response.status_code == 200
    assert response.json()["request_id"] == "test-trace-123"
    assert response.json()["data"]["status"] == "alive"
    assert "Server-Timing" in response.headers
    assert client.get("/health/ready").json()["data"]["store"] == "memory"


def test_invalid_request_id_replaced(client):
    response = client.get("/health/live", headers={"X-Request-ID": "bad value"})
    assert len(response.headers["X-Request-ID"]) == 32


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": "Basic fake"}])
def test_protected_routes_reject_missing_or_invalid_identity(client, headers):
    for path in ("/api/v1/me", "/api/v1/content/snapshot", "/api/v1/admin/sync/status"):
        response = client.get(path, headers=headers)
        assert_error(response, 401, "UNAUTHORIZED")
        assert response.headers["WWW-Authenticate"] == "Bearer"


def test_dev_login_uses_server_identity_and_logout_revokes(client, token):
    response = client.get("/api/v1/me", headers=auth(token))
    assert response.json()["data"]["user_id"] == "dev-member"
    assert response.json()["data"]["roles"] == ["member"]
    assert client.post("/api/v1/auth/logout", headers=auth(token)).status_code == 200
    assert_error(client.get("/api/v1/me", headers=auth(token)), 401, "UNAUTHORIZED")


def test_dev_login_denied(client):
    assert_error(client.post("/api/v1/auth/dev", headers={"X-Dev-Login-Key": "wrong"}), 401, "DEV_LOGIN_DENIED")


def test_disabled_dev_login(settings):
    settings.dev_login_enabled = False
    with TestClient(create_app(settings)) as client:
        assert_error(client.post("/api/v1/auth/dev", headers={"X-Dev-Login-Key": DEV_KEY}), 404, "NOT_FOUND")


def test_member_cannot_access_admin(client, token):
    assert_error(client.get("/api/v1/admin/sync/status", headers=auth(token)), 403, "FORBIDDEN")


def test_admin_authorization_and_missing_snapshot(client, app):
    principal = Principal(user_id="admin", tenant_id="test", display_name="Admin",
                          roles=["admin"], identity_source="development")
    issued = client.portal.call(app.state.auth.issue, principal)
    response = client.get("/api/v1/admin/sync/status", headers=auth(issued.access_token))
    assert response.status_code == 200
    assert response.json()["data"] == {"snapshot_ready": False, "version": None,
                                        "synced_at": None, "worker_connected": False}


def test_missing_snapshot_does_not_call_feishu(client, app, token):
    async def forbidden(*args):
        raise AssertionError("Request-time Feishu access is forbidden")
    app.state.feishu.exchange_code = forbidden
    assert_error(client.get("/api/v1/content/snapshot", headers=auth(token)), 503, "SNAPSHOT_NOT_READY")


def test_expired_session(client, app, store):
    principal = Principal(user_id="old", tenant_id="test", display_name="Old", identity_source="development")
    record = SessionRecord(principal=principal, expires_at=datetime.now(UTC)-timedelta(seconds=1))
    client.portal.call(store.set, app.state.auth.key("expired"), record.model_dump_json())
    assert_error(client.get("/api/v1/me", headers=auth("expired")), 401, "UNAUTHORIZED")


def test_raw_feishu_code_without_browser_state_is_rejected(client):
    assert_error(client.post("/api/v1/auth/feishu", json={"code": "valid-shaped-code"}), 400, "OAUTH_STATE_INVALID")


def test_validation_does_not_echo_input(client):
    response = client.post("/api/v1/auth/feishu", json={"code": {"secret": "must-not-leak"}})
    assert_error(response, 422, "VALIDATION_ERROR")
    assert "must-not-leak" not in response.text
    assert response.json()["error"]["details"][0]["field"] == "body.code"
    assert_error(client.post("/api/v1/auth/feishu", json={"code": "x", "role": "admin"}), 422, "VALIDATION_ERROR")
    assert_error(client.post("/api/v1/auth/feishu", content=b'{bad', headers={"Content-Type": "application/json"}), 422, "VALIDATION_ERROR")


def test_not_found_and_wrong_method(client):
    assert_error(client.get("/not-a-route"), 404, "NOT_FOUND")
    response = client.post("/api/v1/me")
    assert_error(response, 405, "METHOD_NOT_ALLOWED")
    assert "GET" in response.headers["Allow"]


@pytest.mark.parametrize("exception,status,code", [
    (RuntimeError("secret-do-not-echo"), 500, "INTERNAL_ERROR"),
    (RedisConnectionError("redis-secret-url"), 503, "CACHE_UNAVAILABLE"),
    (httpx.ReadTimeout("private-url"), 504, "UPSTREAM_TIMEOUT"),
    (httpx.ConnectError("private-url"), 502, "UPSTREAM_ERROR"),
    (AppError(ErrorCode.CONFLICT), 409, "CONFLICT"),
    (HTTPException(403, "private detail"), 403, "FORBIDDEN"),
])
def test_errors_keep_status_envelope_and_cors(app, exception, status, code):
    @app.get("/test-failure")
    async def fail():
        raise exception
    with TestClient(app, raise_server_exceptions=False) as client:
        client.post("/api/v1/auth/dev", headers={"X-Dev-Login-Key": DEV_KEY})
        response = client.get("/test-failure", headers={"Origin": "http://127.0.0.1:8765"})
        assert_error(response, status, code)
        assert response.headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:8765"
        assert "secret" not in response.text and "private" not in response.text


def test_request_body_limit_with_and_without_content_length(client):
    response = client.post("/api/v1/auth/feishu", content=b"a"*1025)
    assert_error(response, 413, "PAYLOAD_TOO_LARGE")
    response = client.post("/api/v1/auth/feishu", content=iter([b"a"*600, b"b"*600]))
    assert "Content-Length" not in response.request.headers
    assert_error(response, 413, "PAYLOAD_TOO_LARGE")


def test_host_validation(client):
    assert_error(client.get("/health/live", headers={"Host": "evil.example"}), 400, "INVALID_HOST")


def test_cors_preflight(client):
    response = client.options("/api/v1/me", headers={"Origin": "http://127.0.0.1:8765",
                              "Access-Control-Request-Method": "GET",
                              "Access-Control-Request-Headers": "authorization"})
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:8765"
    assert "Access-Control-Allow-Origin" not in client.get("/health/live", headers={"Origin": "https://evil.example"}).headers


def test_openapi_declares_auth_and_error_schema(client):
    schema = client.get("/openapi.json").json()
    route = schema["paths"]["/api/v1/me"]["get"]
    assert route["security"] == [{"HTTPBearer": []}]
    assert "401" in route["responses"] and "422" in route["responses"]
    assert "request_id" in schema["components"]["schemas"]["Envelope_Principal_"]["properties"]


@pytest.mark.parametrize("changes", [
    {"environment": "production", "store_backend": "memory", "docs_enabled": False},
    {"environment": "production", "store_backend": "redis", "docs_enabled": False,
     "dev_login_enabled": True, "dev_login_key": DEV_KEY},
    {"cors_origins": ["*"]}, {"allowed_hosts": ["*"]},
    {"dev_login_enabled": True, "dev_login_key": "short"},
])
def test_invalid_config_fails_fast(changes):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, news_sync_enabled=False, **changes)


def test_content_endpoint_returns_published_snapshot(client, app, token):
    from app.schemas.content import ContentSnapshot
    snapshot = ContentSnapshot(version="test-v1", synced_at=datetime.now(UTC),
                               cases=[dict(id="case-1", title="案例", category="办公", source="团队", summary="摘要")])
    client.portal.call(app.state.snapshots.publish, snapshot)
    response = client.get("/api/v1/content/snapshot", headers=auth(token))
    assert response.status_code == 200
    assert response.json()["data"]["version"] == "test-v1"
    assert response.json()["data"]["cases"][0]["title"] == "案例"


def test_store_outage_is_not_anonymous_or_memory_fallback(client, store, token, monkeypatch):
    async def offline(*args):
        raise RedisConnectionError("private connection")
    monkeypatch.setattr(store, "get", offline)
    monkeypatch.setattr(store, "ping", offline)
    assert_error(client.get("/api/v1/me", headers=auth(token)), 503, "CACHE_UNAVAILABLE")
    assert_error(client.get("/health/ready"), 503, "CACHE_UNAVAILABLE")
    assert client.get("/health/live").status_code == 200
