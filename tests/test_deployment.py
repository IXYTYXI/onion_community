import json

import pytest
from awesome_deploy.errors import DeployError

from app.core.config import Settings
from app.deployment.service import DeploymentService
from app.deployment.sync import DeploymentSync
from app.repositories.store import MemoryStore
from app.schemas.auth import Principal


@pytest.fixture
def deploy(tmp_path):
    s = Settings(
        _env_file=None,
        news_sync_enabled=False,
        deploy_state_root=tmp_path,
        feishu_app_id="cli_aa04dd8797f8dbd1",
        deploy_tenant_id="tenant-test",
    )
    return DeploymentService(s)


def person(number):
    return Principal(
        user_id="feishu:cli_aa04dd8797f8dbd1:ou_" + str(number) * 32,
        tenant_id="tenant-test",
        display_name="测试用户",
        identity_source="feishu",
    )


def queued(s, number=1, key="test"):
    actor = s.actor(person(number))
    return s.store.enqueue(
        {
            "repository": "https://github.com/team/demo.git",
            "subdomain": "demo",
            "ref": "main",
        },
        key,
        actor=actor,
    )


def test_ownership_idempotency_and_revocation(deploy):
    job = queued(deploy)
    assert queued(deploy)["id"] == job["id"]
    assert deploy.get_job(person(1), job["id"])["status"] == "queued"
    with pytest.raises(DeployError, match="permission"):
        deploy.get_job(person(2), job["id"])
    actor = deploy.actor(person(1))
    deploy.identity.set_user(actor["id"], enabled=False)
    with pytest.raises(DeployError):
        deploy.get_job(person(1), job["id"])


def test_no_executor_no_job(deploy):
    with pytest.raises(DeployError) as error:
        deploy.submit(person(1), "https://github.com/team/demo", "demo", "id")
    assert error.value.code == "EXECUTOR_UNAVAILABLE"
    assert deploy.store.list_jobs() == []


def test_transaction_rolls_back_sync_intent(deploy):
    job = queued(deploy)
    with deploy.store._connection() as db:
        before = db.execute(
            "SELECT revision FROM community_sync WHERE kind='job' AND entity_id=? AND target='redis'",
            (job["id"],),
        ).fetchone()[0]
    with pytest.raises(RuntimeError), deploy.store._connection(write=True) as db:
        db.execute("UPDATE jobs SET phase='build' WHERE id=?", (job["id"],))
        raise RuntimeError()
    with deploy.store._connection() as db:
        assert (
            db.execute(
                "SELECT revision FROM community_sync WHERE kind='job' AND entity_id=? AND target='redis'",
                (job["id"],),
            ).fetchone()[0]
            == before
        )
    assert deploy.store.get(job["id"])["phase"] == "queued"


@pytest.mark.asyncio
async def test_feishu_failure_does_not_block_redis_and_retry_survives_restart(deploy):
    job = queued(deploy)
    cache = MemoryStore()
    sync = DeploymentSync(deploy, cache, None)
    await sync.once()
    assert json.loads(await cache.get("deploy:job:" + job["id"]))["status"] == "queued"
    with deploy.store._connection() as db:
        r = dict(
            db.execute(
                "SELECT * FROM community_sync WHERE kind='job' AND target='feishu'"
            ).fetchone()
        )
        assert r["attempts"] == 1 and r["done_revision"] == 0
    restarted = DeploymentService(deploy.settings)
    with restarted.store._connection() as db:
        assert (
            db.execute(
                "SELECT attempts FROM community_sync WHERE kind='job' AND target='feishu'"
            ).fetchone()[0]
            == 1
        )


@pytest.mark.asyncio
async def test_newer_change_during_delivery_remains_pending(deploy):
    queued(deploy)
    sync = DeploymentSync(deploy, MemoryStore(), None)

    async def delivery(kind, entity, data):
        if kind == "job":
            deploy.store.checkpoint(entity, phase="build")

    sync.deliver_feishu = delivery
    await sync.once()
    with deploy.store._connection() as db:
        r = db.execute(
            "SELECT revision,done_revision FROM community_sync WHERE kind='job' AND target='feishu'"
        ).fetchone()
        assert r[0] > r[1]


def test_development_identity_denied(deploy):
    user = person(1)
    user.identity_source = "development"
    with pytest.raises(DeployError):
        deploy.actor(user)


def test_api_auth_and_submission_contract(deploy):
    import asyncio

    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app(deploy.settings, MemoryStore())
    with TestClient(app) as client:
        assert client.get("/api/v1/deployment/jobs").status_code == 401
        token = asyncio.run(app.state.auth.issue(person(1))).access_token
        headers = {
            "Authorization": "Bearer " + token,
            "Idempotency-Key": "contract-test",
        }
        options = client.get("/api/v1/deployment/options", headers=headers)
        assert options.json()["data"]["executionEnabled"] is False
        response = client.post(
            "/api/v1/deployment/jobs",
            headers=headers,
            json={"repository": "https://github.com/team/demo", "name": "demo"},
        )
        assert response.status_code == 503
        assert response.json()["code"] == "DEPLOY_UNAVAILABLE"
        assert response.json()["timestamp"]
        job = queued(app.state.deployment)
        assert (
            client.get(
                "/api/v1/deployment/jobs/" + job["id"], headers=headers
            ).status_code
            == 200
        )
        other = asyncio.run(app.state.auth.issue(person(2))).access_token
        assert (
            client.get(
                "/api/v1/deployment/jobs/" + job["id"],
                headers={"Authorization": "Bearer " + other},
            ).status_code
            == 403
        )


def test_community_secret_entry_is_scoped_and_never_returns_values(deploy):
    import asyncio

    from fastapi.testclient import TestClient
    from awesome_deploy.manifest import load_manifest
    from awesome_deploy.secrets_store import SecretStore
    from app.main import create_app

    app = create_app(deploy.settings, MemoryStore())
    with TestClient(app) as client:
        service = app.state.deployment
        job = queued(service)
        manifest = load_manifest(json.dumps({
            "schemaVersion": 1,
            "app": {"name": "Demo", "description": "Test", "subdomain": "demo"},
            "services": {"web": {
                "kind": "web", "build": {"context": ".", "dockerfile": "Dockerfile"},
                "port": 8080, "healthcheck": {"type": "http", "path": "/health"},
                "secretRefs": {"MODEL_API_KEY": "MODEL_API_KEY"},
            }},
            "routes": [{"path": "/", "match": "prefix", "service": "web"}],
        }), service.engine)
        service.store.checkpoint(job["id"], phase="freeze", snapshot={
            "repository": job["input"]["repository"], "commit": "a" * 40,
            "source_dir": str(service.engine.state_dir / "sources" / job["id"]),
            "manifest": manifest,
        }, execution={"commit": "a" * 40})
        service.store.fail(job["id"], {"code": "SECRET_NOT_FOUND", "message": "Missing secret"})
        path = f"/api/v1/deployment/jobs/{job['id']}/secrets"
        owner = asyncio.run(app.state.auth.issue(person(1))).access_token
        other = asyncio.run(app.state.auth.issue(person(2))).access_token
        owner_headers = {"Authorization": f"Bearer {owner}"}
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"Authorization": f"Bearer {other}"}).status_code == 403
        requirements = client.get(path, headers=owner_headers)
        assert requirements.status_code == 200
        assert requirements.json()["data"]["items"] == [{
            "name": "MODEL_API_KEY", "uses": [{"service": "web", "environmentVariable": "MODEL_API_KEY"}],
            "state": "missing", "managed": False,
        }]
        secret = "provider-value-must-stay-private"
        assert client.post(path, json={"values": {"MODEL_API_KEY": secret}},
                           headers={"Authorization": f"Bearer {other}"}).status_code == 403
        saved = client.post(path, json={"values": {"MODEL_API_KEY": secret}}, headers=owner_headers)
        assert saved.status_code == 200
        assert saved.json()["data"]["items"][0]["state"] == "configured"
        assert secret not in saved.text + requirements.text
        assert SecretStore(service.engine).resolve(job["input"]["repository"], "demo",
                                                   {"MODEL_API_KEY": "MODEL_API_KEY"}) == {"MODEL_API_KEY": secret}
        assert client.post(path, json={"values": {"MODEL_API_KEY": "overwrite"}},
                           headers=owner_headers).status_code == 400


def terminal_state(deploy, job_id, *, status, phase="complete", error=None):
    """Simulate engine commits for projection/synchronization contract tests."""
    import time

    with deploy.store._connection(write=True) as db:
        db.execute(
            "UPDATE jobs SET status=?,phase=?,error=?,updated_at=? WHERE id=?",
            (status, phase, json.dumps(error) if error else None, time.time(), job_id),
        )


def test_concurrent_different_keys_claim_name_once(deploy):
    from concurrent.futures import ThreadPoolExecutor

    # Establish the actor once; real races happen in SQLite, not a mocked lock.
    deploy.actor(person(1))

    def attempt(n):
        try:
            return queued(deploy, key=f"parallel-{n}")["id"]
        except DeployError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(16)))
    assert results.count("DOMAIN_CONFLICT") == 15
    with deploy.store._connection() as db:
        assert db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM apps").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM community_names").fetchone()[0] == 1


def test_same_key_changed_payload_rejected(deploy):
    queued(deploy)
    with pytest.raises(DeployError) as exc:
        deploy.store.enqueue(
            {
                "repository": "https://github.com/team/other.git",
                "subdomain": "other",
                "ref": "main",
            },
            "test",
            actor=deploy.actor(person(1)),
        )
    assert exc.value.code == "IDEMPOTENCY_CONFLICT"


def test_update_queued_application_cannot_bypass_submission_guard(deploy):
    job = queued(deploy)
    payload = dict(job["input"], appId=job["app_id"])
    with pytest.raises(DeployError) as exc:
        deploy.store.enqueue(payload, "second", actor=deploy.actor(person(1)))
    assert exc.value.code == "DEPLOYMENT_CONFLICT"
    terminal_state(deploy, job["id"], status="failed", phase="source")
    assert (
        deploy.store.enqueue(payload, "retry", actor=deploy.actor(person(1)))["id"]
        != job["id"]
    )
    # Failed applications retain identity and can only be retried as existing apps.
    assert not deploy.name_available(person(2), "demo")
    assert deploy.name_available(person(1), "demo", job["app_id"])
    with pytest.raises(DeployError):
        deploy.name_available(person(2), "demo", job["app_id"])


def test_recovery_blocks_update_and_failed_rename_is_rejected(deploy):
    job = queued(deploy)
    terminal_state(deploy, job["id"], status="recovery_required", phase="cleanup")
    with pytest.raises(DeployError) as exc:
        deploy.store.enqueue(
            dict(job["input"], appId=job["app_id"]),
            "new",
            actor=deploy.actor(person(1)),
        )
    assert exc.value.code == "DEPLOYMENT_CONFLICT"
    terminal_state(deploy, job["id"], status="failed")
    with pytest.raises(DeployError) as exc:
        deploy.store.enqueue(
            dict(job["input"], appId=job["app_id"], subdomain="newname"),
            "rename",
            actor=deploy.actor(person(1)),
        )
    assert exc.value.code == "APP_IDENTITY_CONFLICT"


def test_success_url_and_failure_details(deploy):
    job = queued(deploy)
    terminal_state(deploy, job["id"], status="succeeded", phase="complete")
    assert deploy.get_job(person(1), job["id"])["url"].startswith("https://demo.")
    terminal_state(
        deploy,
        job["id"],
        status="failed",
        phase="build",
        error={
            "code": "BUILD_FAILED",
            "message": "镜像构建失败",
            "path": "services.web",
            "suggestion": "请检查 Dockerfile。",
        },
    )
    result = deploy.get_job(person(1), job["id"])
    assert result["url"] is None
    assert result["error"]["field"] == "services.web"
    assert result["error"]["suggestion"] == "请检查 Dockerfile。"


@pytest.mark.asyncio
async def test_sync_backoff_not_reset_by_state_changes(deploy):
    job = queued(deploy)
    await DeploymentSync(deploy, MemoryStore(), None).once()
    with deploy.store._connection() as db:
        before = db.execute(
            "SELECT retry_at FROM community_sync WHERE kind='job' AND target='feishu'"
        ).fetchone()[0]
    deploy.store.checkpoint(job["id"], phase="build")
    with deploy.store._connection() as db:
        assert (
            db.execute(
                "SELECT retry_at FROM community_sync WHERE kind='job' AND target='feishu'"
            ).fetchone()[0]
            == before
        )


@pytest.mark.asyncio
async def test_sync_delivers_url_and_detailed_failure(deploy):
    from types import SimpleNamespace

    job = queued(deploy)
    sync = DeploymentSync(deploy, MemoryStore(), None)
    sent = []

    async def write(rows, **kwargs):
        sent.extend(rows)
        return [{"record_id": "record-test"}]

    sync.tables["job"] = SimpleNamespace(table_id="table-test", write=write)
    with deploy.store._connection(write=True) as db:
        db.execute(
            "INSERT INTO community_sync_records VALUES('job',?,'table-test','record-test')",
            (job["id"],),
        )
    terminal_state(deploy, job["id"], status="succeeded", phase="complete")
    await sync.deliver_feishu(
        "job", job["id"], deploy.project_job(deploy.store.get(job["id"]))
    )
    assert sent[-1]["fields"]["访问地址"].startswith("https://demo.")
    terminal_state(
        deploy,
        job["id"],
        status="failed",
        phase="build",
        error={
            "code": "BUILD_FAILED",
            "message": "镜像构建失败",
            "suggestion": "检查配置",
        },
    )
    await sync.deliver_feishu(
        "job", job["id"], deploy.project_job(deploy.store.get(job["id"]))
    )
    assert "镜像构建失败" in sent[-1]["fields"]["错误摘要"]
    assert "检查配置" in sent[-1]["fields"]["错误摘要"]


@pytest.mark.asyncio
async def test_worker_failure_clears_readiness_and_closes_pool(deploy, monkeypatch):
    from app.deployment import worker

    class Cache(MemoryStore):
        closed = False

        async def close(self):
            self.closed = True

    class BrokenSync:
        def __init__(self, *args):
            pass

        async def run(self):
            raise RuntimeError("sync loop failure")

    cache = Cache()
    monkeypatch.setattr(worker, "Settings", lambda: deploy.settings)
    monkeypatch.setattr(worker, "DeploymentService", lambda _: deploy)
    monkeypatch.setattr(worker, "RedisStore", lambda *a: cache)
    monkeypatch.setattr(worker, "DeploymentSync", BrokenSync)
    with pytest.raises(RuntimeError, match="sync loop failure"):
        await worker.main()
    assert cache.closed
    assert not deploy.executor_ready()
    with deploy.store._connection() as db:
        assert (
            db.execute(
                "SELECT * FROM community_runtime WHERE key='heartbeat'"
            ).fetchone()
            is None
        )


def test_idempotent_retry_returns_existing_job_when_executor_stops(deploy):
    job = queued(deploy)
    result = deploy.submit(person(1), job["input"]["repository"], "demo", "test")
    assert result["id"] == job["id"]
    with pytest.raises(DeployError) as exc:
        deploy.submit(person(1), "https://github.com/team/changed.git", "demo", "test")
    assert exc.value.code == "IDEMPOTENCY_CONFLICT"


def test_readiness_requires_fresh_heartbeat(deploy):
    import time

    deploy.settings.deploy_execution_enabled = True
    assert not deploy.executor_ready()
    with deploy.store._connection(write=True) as db:
        db.execute("CREATE TABLE community_runtime(key TEXT PRIMARY KEY,value TEXT)")
        db.execute(
            "INSERT INTO community_runtime VALUES('heartbeat',?)",
            (str(time.time() - 31),),
        )
    assert not deploy.executor_ready()
    with deploy.store._connection(write=True) as db:
        db.execute("UPDATE community_runtime SET value=?", (str(time.time()),))
    assert deploy.executor_ready()


def test_production_page_auth_and_built_assets(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app

    settings = Settings(
        _env_file=None,
        environment="production",
        store_backend="redis",
        news_sync_enabled=False,
        docs_enabled=False,
        cookie_secure=True,
        site_origin="https://community.example.com",
        deploy_state_root=tmp_path,
        allowed_hosts=["testserver", "community.example.com"],
    )
    with TestClient(create_app(settings, MemoryStore())) as client:
        assert client.get("/health/ready").status_code == 200
        assert client.get("/login.html").status_code == 200
        assert client.get("/deploy.html", follow_redirects=False).status_code == 303
        assert client.get("/api/v1/deployment/jobs").status_code == 401
        assert client.get("/docs").status_code == 404


def test_application_snapshot_includes_active_release_and_domain(deploy):
    job = queued(deploy)
    terminal_state(deploy, job["id"], status="succeeded")
    with deploy.store._connection(write=True) as db:
        db.execute(
            "UPDATE apps SET subdomain='demo',active_release_id=? WHERE id=?",
            (job["id"], job["app_id"]),
        )
    data = deploy.snapshot("app", job["app_id"])
    assert data["status"] == "online"
    assert data["url"] == "https://demo." + deploy.engine.base_domain
    assert data["activeReleaseId"] == job["id"]


def test_http_duplicate_name_and_idempotency_contract(deploy):
    import asyncio
    import time

    from fastapi.testclient import TestClient

    from app.main import create_app

    deploy.settings.deploy_execution_enabled = True
    app = create_app(deploy.settings, MemoryStore())
    with TestClient(app) as client:
        with app.state.deployment.store._connection(write=True) as db:
            db.execute(
                "CREATE TABLE community_runtime(key TEXT PRIMARY KEY,value TEXT)"
            )
            db.execute(
                "INSERT INTO community_runtime VALUES('heartbeat',?)",
                (str(time.time()),),
            )
        token = asyncio.run(app.state.auth.issue(person(1))).access_token
        headers = {"Authorization": "Bearer " + token, "Idempotency-Key": "submit-1"}
        body = {"repository": "https://github.com/team/demo.git", "name": "demo"}
        first = client.post("/api/v1/deployment/jobs", headers=headers, json=body)
        assert first.status_code == 202
        repeated = client.post("/api/v1/deployment/jobs", headers=headers, json=body)
        assert repeated.json()["data"]["id"] == first.json()["data"]["id"]
        headers["Idempotency-Key"] = "submit-2"
        conflict = client.post("/api/v1/deployment/jobs", headers=headers, json=body)
        assert conflict.status_code == 409
        assert conflict.json()["code"] == "DEPLOY_CONFLICT"
        assert "项目名称已存在" in conflict.json()["message"]
        assert (
            client.get(
                "/api/v1/deployment/name-availability?name=demo", headers=headers
            ).json()["data"]["available"]
            is False
        )


def test_shared_identity_database_requires_explicit_group_and_mode(deploy):
    import stat
    from awesome_deploy.identity import IdentityStore

    path = deploy.engine.database_path
    gid = path.stat().st_gid
    path.chmod(0o660)
    IdentityStore(deploy.engine, provider=object(), shared_database_gid=gid)
    assert stat.S_IMODE(path.stat().st_mode) == 0o660
    path.chmod(0o666)
    with pytest.raises(DeployError, match="共享身份数据库"):
        IdentityStore(deploy.engine, provider=object(), shared_database_gid=gid)
    IdentityStore(deploy.engine, provider=object())
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize("live,released,conflict", [(True, False, False), (False, True, False), (False, False, True)])
def test_legacy_name_migration_respects_current_binding_and_completed_offline(deploy, live, released, conflict):
    from app.deployment.store import CommunityDeploymentStore

    job = queued(deploy)
    terminal_state(deploy, job["id"], status="failed")
    with deploy.store._connection(write=True) as db:
        db.execute("DROP TRIGGER community_submit_guard")
        db.execute("DELETE FROM community_names")
        db.execute("INSERT INTO apps VALUES ('new-app','https://github.com/team/demo',?,NULL,10,10)", ("demo" if live else None,))
        db.execute("INSERT INTO jobs(id,idempotency_key,input,app_id,status,phase,created_at,updated_at) VALUES('new-job','new-key',?,'new-app','failed','complete',20,20)", (json.dumps({"subdomain":"demo"}),))
        if released:
            db.execute("INSERT INTO offline_operations(id,idempotency_key,app_id,target_release_id,status,phase,created_at,updated_at) VALUES('off','off-key',?,?,'succeeded','complete',9999999999,9999999999)", (job["app_id"],job["id"]))
    if conflict:
        migrated = CommunityDeploymentStore(deploy.engine)
        with migrated._connection() as db:
            assert db.execute("SELECT app_id FROM community_names WHERE name='demo'").fetchone()[0] == 'legacy-conflict:demo'
        with pytest.raises(DeployError) as error:
            queued(deploy, key="new-claim")
        assert error.value.code == "DOMAIN_CONFLICT"
    else:
        migrated = CommunityDeploymentStore(deploy.engine)
        with migrated._connection() as db:
            assert db.execute("SELECT app_id FROM community_names WHERE name='demo'").fetchone()[0] == 'new-app'
