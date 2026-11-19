import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.repositories.store import MemoryStore

DEV_KEY = "test-key-only-not-for-production-12345"


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, deploy_state_root=tmp_path / "deployment", news_sync_enabled=False, environment="test", store_backend="memory",
                    case_interactions_db=tmp_path / "case-interactions.sqlite3",
                    dev_login_enabled=True, dev_login_key=DEV_KEY, max_body_bytes=1024)


@pytest.fixture
def store():
    return MemoryStore()


@pytest.fixture
def app(settings, store):
    return create_app(settings, store)


@pytest.fixture
def client(app):
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def token(client):
    response = client.post("/api/v1/auth/dev", headers={"X-Dev-Login-Key": DEV_KEY})
    assert response.status_code == 200
    return response.json()["data"]["access_token"]
