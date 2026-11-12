import re
from conftest import DEV_KEY

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.error_codes import ErrorCode
from app.core.errors import AppError
from app.schemas.common import ErrorEnvelope, ErrorInfo
from scripts.export_error_codes import OUTPUT, render


def test_catalog_is_unique_and_documentation_is_current():
    assert len(ErrorCode) == len(ErrorCode.__members__)
    for code in ErrorCode:
        assert re.fullmatch(r"[A-Z][A-Z0-9_]*", code.value)
        assert 400 <= code.definition.status <= 599
        assert code.definition.message
    assert OUTPUT.read_text() == render()


def test_business_exception_rejects_unregistered_codes_and_status_override():
    with pytest.raises(TypeError):
        AppError("NOT_FOUND")
    with pytest.raises(TypeError):
        AppError(ErrorCode.NOT_FOUND, status=200)
    with pytest.raises(TypeError):
        AppError(ErrorCode.NOT_FOUND, message="unreviewed text")
    with pytest.raises(ValidationError):
        ErrorEnvelope(code="UNREGISTERED", message="test", error=ErrorInfo(), request_id="test")


@pytest.mark.parametrize("status,expected_status,expected_code", [
    (400, 400, "BAD_REQUEST"), (401, 401, "UNAUTHORIZED"), (403, 403, "FORBIDDEN"),
    (404, 404, "NOT_FOUND"), (405, 405, "METHOD_NOT_ALLOWED"),
    (409, 409, "CONFLICT"), (429, 429, "RATE_LIMITED"),
    (503, 503, "SERVICE_UNAVAILABLE"), (418, 400, "BAD_REQUEST"),
    (599, 500, "INTERNAL_ERROR"),
])
def test_framework_exceptions_use_catalog(app, status, expected_status, expected_code):
    @app.get("/catalog-failure")
    async def fail():
        raise HTTPException(status, "sensitive exception detail")
    with TestClient(app, raise_server_exceptions=False) as client:
        client.post("/api/v1/auth/dev", headers={"X-Dev-Login-Key": DEV_KEY})
        response = client.get("/catalog-failure")
    assert response.status_code == expected_status
    assert response.json()["code"] == expected_code
    assert response.json()["message"] == ErrorCode(expected_code).definition.message
    assert "sensitive" not in response.text
    if status == 401:
        assert response.headers["WWW-Authenticate"] == "Bearer"


def test_default_headers_and_explicit_retry_after(app):
    @app.get("/retry-default")
    async def default():
        raise AppError(ErrorCode.SNAPSHOT_NOT_READY)
    @app.get("/retry-custom")
    async def custom():
        raise AppError(ErrorCode.RATE_LIMITED, headers={"Retry-After": "30"})
    with TestClient(app) as client:
        client.post("/api/v1/auth/dev", headers={"X-Dev-Login-Key": DEV_KEY})
        assert client.get("/retry-default").headers["Retry-After"] == "10"
        assert client.get("/retry-custom").headers["Retry-After"] == "30"


def test_openapi_catalog_matches_runtime_codes(client):
    schema = client.get("/openapi.json").json()
    assert set(schema["components"]["schemas"]["ErrorCode"]["enum"]) == {c.value for c in ErrorCode}
    responses = schema["paths"]["/api/v1/me"]["get"]["responses"]
    for code in ErrorCode:
        response = responses[str(code.definition.status)]
        assert response["content"]["application/json"]["schema"]["$ref"].endswith("/ErrorEnvelope")
        example = response["content"]["application/json"]["examples"][code.value]["value"]
        assert example["code"] == code.value
        assert example["message"] == code.definition.message
