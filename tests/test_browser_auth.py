import asyncio
import hashlib
import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import AppError
from app.integrations.feishu import FeishuIdentityProvider
from app.main import create_app
from app.repositories.store import MemoryStore
from app.schemas.auth import Principal
from app.services.browser_auth import safe_next
from conftest import DEV_KEY


@pytest.fixture
def oauth(client, app):
    app.state.settings.feishu_app_id = "cli_test"
    from pydantic import SecretStr
    app.state.settings.feishu_app_secret = SecretStr("test-secret")
    calls = []
    async def exchange(code, verifier):
        calls.append((code, verifier))
        return Principal(user_id="feishu:cli_test:member", tenant_id="our-tenant", display_name="测试成员", identity_source="feishu")
    app.state.feishu.exchange_code = exchange
    return calls


def start(client, next="/cases.html?q=test"):
    response = client.get("/api/v1/auth/feishu/start", params={"next": next}, follow_redirects=False)
    assert response.status_code == 303
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["code_challenge_method"] == ["S256"]
    assert "client_secret" not in query and "prompt" not in query
    return query["state"][0]


def test_oauth_flow_sets_cookie_and_returns_original_page(client, oauth):
    state = start(client)
    response = client.get("/api/v1/auth/feishu/callback", params={"state":state,"code":"once"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/cases.html?q=test"
    assert "HttpOnly" in response.headers["set-cookie"] and "SameSite=lax" in response.headers["set-cookie"]
    assert "ows_oauth" not in client.cookies
    assert client.get("/api/v1/auth/session").json()["data"]["user"]["display_name"] == "测试成员"
    assert client.get("/index.html").status_code == 200
    from app.api.pages import FRONTEND
    import json
    manifest = json.loads((FRONTEND / ".vite/manifest.json").read_text())
    assert client.get("/" + manifest["src/pages/Cases.vue"]["file"]).status_code == 200
    replay = client.get("/api/v1/auth/feishu/callback", params={"state":state,"code":"once"}, follow_redirects=False)
    assert "OAUTH_STATE_INVALID" in replay.headers["location"]
    assert len(oauth) == 1


def test_missing_mismatched_expired_and_cross_browser_state(client, app, oauth):
    state = start(client)
    cookie = client.cookies.get("ows_oauth")
    client.cookies.clear()
    for candidate in (state,"forged",""):
        result = client.get("/api/v1/auth/feishu/callback", params={"state":candidate,"code":"secret-code"},follow_redirects=False)
        assert "OAUTH_STATE_INVALID" in result.headers["location"]
        assert "secret-code" not in result.text + result.headers["location"]
    client.cookies.set("ows_oauth",cookie,path="/api/v1/auth/feishu")
    client.portal.call(app.state.store.delete, "oauth:" + hashlib.sha256(state.encode()).hexdigest())
    result=client.get("/api/v1/auth/feishu/callback",params={"state":state,"code":"once"},follow_redirects=False)
    assert "OAUTH_STATE_INVALID" in result.headers["location"]
    assert not oauth


def test_cancel_goes_to_retry_without_redirect_loop(client,oauth):
    state=start(client)
    response=client.get("/api/v1/auth/feishu/callback",params={"state":state,"error":"access_denied"},follow_redirects=False)
    assert "FEISHU_AUTH_FAILED" in response.headers["location"]
    assert "auto=" not in response.headers["location"]
    assert not oauth


@pytest.mark.parametrize("value",["https://evil.test", "//evil.test", "/\\evil.test", "/api/v1/auth/feishu/start", "/index.html\r\nX:test", "/%2f%2fevil.test"])
def test_no_open_redirect(value):
    assert safe_next(value)=="/index.html"


def test_unauthenticated_pages_assets_and_no_source_leaks(client):
    for page in ("/", "/index.html","/cases.html","/profile.html","/detail.html?type=case&id=research"):
        response=client.get(page,follow_redirects=False)
        assert response.status_code==303
        assert response.headers["location"].startswith("/login.html?")
        assert "精选案例" not in response.text
    from app.api.pages import FRONTEND, public_assets
    import json
    manifest = json.loads((FRONTEND / ".vite/manifest.json").read_text())
    business_bundle = manifest["src/pages/Cases.vue"]["file"]
    for path in ("/" + business_bundle, "/assets/onion-logo.png"):
        assert client.get(path).status_code==401
    for path in ("/.env","/README.md","/BACKEND_HANDOFF.md","/src/main.js","/.vite/manifest.json","/assets/","/assets/../../.env"):
        assert client.get(path).status_code==404
    for path in ("/" + asset for asset in public_assets()):
        assert client.get(path).status_code==200


def test_versioned_skill_poster_uses_private_browser_cache_after_login(client):
    from app.api.pages import FRONTEND

    posters = list((FRONTEND / "assets").glob("ows-skill-cli-poster-*.png"))
    assert len(posters) == 1
    path = "/assets/" + posters[0].name
    assert client.get(path).status_code == 401

    assert client.post("/api/v1/auth/dev", headers={"X-Dev-Login-Key": DEV_KEY}).status_code == 200
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, max-age=31536000, immutable"
    assert client.get("/index.html").headers["Cache-Control"] == "no-store"
    assert client.get("/assets/ows-community-logo.png").headers["Cache-Control"] == "no-store"


def test_deployment_skill_download_is_authenticated_complete_zip(client):
    from io import BytesIO
    from zipfile import ZipFile

    path = "/assets/awesome-deploy-protocol-20261117-r4.zip"
    assert client.get(path).status_code == 401
    assert client.post("/api/v1/auth/dev", headers={"X-Dev-Login-Key": DEV_KEY}).status_code == 200
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/zip")
    assert "attachment" in response.headers["content-disposition"]
    with ZipFile(BytesIO(response.content)) as archive:
        assert "awesome-deploy-protocol/SKILL.md" in archive.namelist()
        assert "awesome-deploy-protocol/assets/awesome-v2.schema.json" in archive.namelist()
        assert "2026-11-17-r4" in archive.read("awesome-deploy-protocol/SKILL.md").decode()
        guidance = archive.read("awesome-deploy-protocol/references/resources-and-delivery.md").decode()
        assert "没有需要用户填写的引用时" in guidance
        assert "SECRET_NOT_FOUND" in guidance


def test_cookie_logout_requires_origin_and_csrf(client):
    assert client.post("/api/v1/auth/dev",headers={"X-Dev-Login-Key":DEV_KEY}).status_code==200
    session=client.get("/api/v1/auth/session").json()["data"]
    assert client.post("/api/v1/auth/logout").status_code==403
    assert client.post("/api/v1/auth/logout",headers={"Origin":"https://evil.test","X-CSRF-Token":session["csrf_token"]}).status_code==403
    assert client.get("/api/v1/me").status_code==200
    response=client.post("/api/v1/auth/logout",headers={"Origin":"http://127.0.0.1:8765","X-CSRF-Token":session["csrf_token"]})
    assert response.status_code==200
    assert client.get("/api/v1/me").status_code==401
    assert client.get("/index.html",follow_redirects=False).status_code==303


def test_login_rotates_previous_session(client):
    old=client.post("/api/v1/auth/dev",headers={"X-Dev-Login-Key":DEV_KEY}).json()["data"]["access_token"]
    client.post("/api/v1/auth/dev",headers={"X-Dev-Login-Key":DEV_KEY})
    assert client.get("/api/v1/me",headers={"Authorization":f"Bearer {old}"}).status_code==401


async def test_atomic_consume_memory_and_redis():
    from fakeredis.aioredis import FakeRedis
    from app.repositories.store import RedisStore
    for store in (MemoryStore(),RedisStore(FakeRedis(decode_responses=True),"auth-test")):
        await store.set("flow","value",300)
        values=await asyncio.gather(store.take("flow"),store.take("flow"))
        assert values.count("value")==1 and values.count(None)==1
        await store.close()


async def test_feishu_pkce_exchange_uses_backend_secret_and_checks_tenant():
    settings=Settings(_env_file=None, news_sync_enabled=False,feishu_app_id="cli_test",feishu_app_secret="private",feishu_allowed_tenants=["allowed"])
    requests=[]
    def handler(request):
        requests.append(request)
        if request.url.path=="/open-apis/authen/v2/oauth/token":
            data=json.loads(request.content)
            assert data["client_secret"]=="private" and data["code_verifier"]=="verifier"
            assert data["redirect_uri"]==settings.feishu_redirect_uri
            return httpx.Response(200,json={"code":0,"access_token":"private-user-token"})
        assert request.headers["authorization"]=="Bearer private-user-token"
        return httpx.Response(200,json={"code":0,"data":{"open_id":"ou_test","tenant_key":"allowed","name":"Test"}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        provider=FeishuIdentityProvider(transport,settings)
        user=await provider.exchange_code("code","verifier")
        assert user.roles==["member"] and user.user_id=="feishu:cli_test:ou_test"
        settings.feishu_allowed_tenants=["another"]
        with pytest.raises(AppError) as error:
            await provider.exchange_code("code","verifier")
        assert error.value.code.value=="FORBIDDEN"


@pytest.mark.parametrize("payload",[{"code":20003,"error":"invalid_grant","error_description":"secret"},{"code":20010},{"code":0},[]])
async def test_provider_failures_never_issue_identity(payload):
    settings=Settings(_env_file=None, news_sync_enabled=False,feishu_app_id="cli_test",feishu_app_secret="private")
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,json=payload))) as transport:
        with pytest.raises(AppError):
            await FeishuIdentityProvider(transport,settings).exchange_code("code","verifier")


def test_deployment_page_requires_login_and_preserves_return_path(client):
    assert safe_next('/deploy.html') == '/deploy.html'
    response = client.get('/deploy.html', follow_redirects=False)
    assert response.status_code == 303
    from urllib.parse import urlsplit, parse_qs
    assert parse_qs(urlsplit(response.headers['location']).query)['next'] == ['/deploy.html']
