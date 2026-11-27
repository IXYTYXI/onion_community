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


def test_enqueue_hook_rolls_back_new_app_and_job(deploy):
    actor = deploy.actor(person(1))
    payload = {"repository": "https://github.com/team/demo.git", "subdomain": "demo", "ref": "main"}

    def reject(db, app_id, fresh_actor):
        assert app_id and fresh_actor["id"] == actor["id"]
        raise RuntimeError("synthetic failure")

    with pytest.raises(RuntimeError, match="synthetic failure"):
        deploy.store.enqueue(payload, "atomic-reject", actor=actor, on_app_ready=reject)
    with deploy.store._connection() as db:
        assert db.execute("SELECT count(*) FROM apps").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0


def test_preflight_reads_manifest_references_and_skips_empty_configuration(deploy, monkeypatch):
    from awesome_deploy.source import GitSource

    manifest = {"app": {"subdomain": "demo"}, "services": {
        "web": {"secretRefs": {"MODEL_API_KEY": "PROVIDER_KEY", "MASTER_KEY": "DATA_MASTER"}},
        "worker": {"secretRefs": {"BACKEND_KEY": "PROVIDER_KEY"}},
    }}
    monkeypatch.setattr(GitSource, "inspect", lambda self, repository, ref="main", **kwargs: {
        "repository": "https://github.com/team/demo.git", "commit": "a" * 40,
        "manifest": manifest,
    })
    result = deploy.preflight(person(1), "https://github.com/team/demo")
    assert result["commit"] == "a" * 40
    assert result["subdomain"] == "demo"
    assert result["canPreconfigure"] is False
    assert result["items"] == [
        {"name": "DATA_MASTER", "uses": [{"service": "web", "environmentVariable": "MASTER_KEY"}],
         "state": "missing", "managed": True},
        {"name": "PROVIDER_KEY", "uses": [
            {"service": "web", "environmentVariable": "MODEL_API_KEY"},
            {"service": "worker", "environmentVariable": "BACKEND_KEY"}],
         "state": "missing", "managed": False},
    ]
    manifest["services"] = {"web": {"secretRefs": {}}}
    assert deploy.preflight(person(1), "https://github.com/team/demo")["items"] == []


def test_submit_rechecks_preflight_commit_and_pins_new_job(deploy, monkeypatch):
    from awesome_deploy.source import GitSource

    manifest = {"app": {"subdomain": "demo"}, "services": {"web": {"secretRefs": {}}}}
    monkeypatch.setattr(GitSource, "inspect", lambda self, repository, ref="main", **kwargs: {
        "repository": "https://github.com/team/demo.git", "commit": "a" * 40,
        "manifest": manifest,
    })
    deploy.settings.deploy_execution_enabled = True
    monkeypatch.setattr(deploy, "executor_ready", lambda: True)
    with pytest.raises(DeployError) as error:
        deploy.submit(person(1), "https://github.com/team/demo", "demo", "preflight-stale",
                      commit="b" * 40, values={})
    assert error.value.code == "PREFLIGHT_STALE"
    assert deploy.store.list_jobs() == []
    accepted = deploy.submit(person(1), "https://github.com/team/demo", "demo", "preflight-good",
                             commit="a" * 40, values={})
    assert deploy.store.get(accepted["id"])["input"]["ref"] == "main"
    assert deploy.store.get(accepted["id"])["input"]["expectedCommit"] == "a" * 40


def test_legacy_backend_never_accepts_preflight_secret_values(deploy, monkeypatch):
    from awesome_deploy.source import GitSource

    monkeypatch.setattr(GitSource, "inspect", lambda self, repository, ref="main", **kwargs: {
        "repository": "https://github.com/team/demo.git", "commit": "a" * 40,
        "manifest": {"app": {"subdomain": "demo"}, "services": {
            "web": {"secretRefs": {"MODEL_KEY": "API_KEY"}}}},
    })
    deploy.settings.deploy_execution_enabled = True
    monkeypatch.setattr(deploy, "executor_ready", lambda: True)
    with pytest.raises(DeployError) as error:
        deploy.submit(person(1), "https://github.com/team/demo", "demo", "legacy-key",
                      commit="a" * 40, values={"API_KEY": "fixture-only"})
    assert error.value.code == "SECRET_PRECONFIGURATION_UNAVAILABLE"
    assert deploy.store.list_jobs() == []


def test_encrypted_preflight_secrets_and_job_commit_atomically(tmp_path, monkeypatch):
    import base64
    import os
    import sqlite3
    from awesome_deploy.config import Settings as EngineSettings
    from awesome_deploy.source import GitSource
    from awesome_deploy.vault_format import ensure_schema, set_format
    from awesome_deploy.secret_vault import SecretVault

    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    key_dir = tmp_path / "credentials"
    key_dir.mkdir(mode=0o700)
    key = key_dir / "root.json"
    key.write_text(json.dumps({"format": 1, "active": "k1", "keys": {
        "k1": base64.b64encode(os.urandom(32)).decode()}}))
    key.chmod(0o600)
    engine = EngineSettings(state_dir=state, auth_mode="feishu",
                            feishu_app_id="cli_aa04dd8797f8dbd1", feishu_tenant_key="tenant-test",
                            secret_backend="encrypted", secret_kek_file=key)
    with sqlite3.connect(engine.database_path, isolation_level=None) as db:
        db.row_factory = sqlite3.Row
        ensure_schema(db)
        db.execute("BEGIN IMMEDIATE")
        set_format(db, engine, phase="active", migration_id="test")
        db.commit()
    monkeypatch.setattr("app.deployment.service.load_settings", lambda _: engine)
    settings = Settings(_env_file=None, news_sync_enabled=False, deploy_state_root=state,
                        deploy_engine_config=tmp_path / "engine.json", deploy_execution_enabled=True,
                        feishu_app_id="cli_aa04dd8797f8dbd1", deploy_tenant_id="tenant-test")
    service = DeploymentService(settings)
    monkeypatch.setattr(service, "executor_ready", lambda: True)
    manifest = {"app": {"subdomain": "demo"}, "services": {"web": {
        "secretRefs": {"MODEL_KEY": "API_KEY", "MASTER_KEY": "DATA_MASTER"}}}}
    monkeypatch.setattr(GitSource, "inspect", lambda self, repository, ref="main", **kwargs: {
        "repository": "https://github.com/team/demo.git", "commit": "a" * 40,
        "manifest": manifest,
    })
    with pytest.raises(DeployError):
        service.submit(person(1), "https://github.com/team/demo", "demo", "bad-values",
                       commit="a" * 40, values={"UNDECLARED": "fixture-only"})
    assert service.store.list_jobs() == []
    with service.store._connection() as db:
        assert db.execute("SELECT count(*) FROM apps").fetchone()[0] == 0
    result = service.submit(person(1), "https://github.com/team/demo", "demo", "good-values",
                            commit="a" * 40, values={"API_KEY": "fixture-only"})
    again = service.submit(person(1), "https://github.com/team/demo", "demo", "good-values",
                           commit="a" * 40, values={})
    assert again["id"] == result["id"]
    with service.store._connection() as db:
        app_id = service.store.get(result["id"])["app_id"]
        vault = SecretVault(service.engine)
        assert {item["name"] for item in vault.metadata(db, app_id)} == {"API_KEY", "DATA_MASTER"}
        assert b"fixture-only" not in engine.database_path.read_bytes()
    service.store.fail(result["id"], {"code": "SYNTHETIC", "message": "test only"})
    status = service.preflight(person(1), "https://github.com/team/demo", app_id)
    assert {item["state"] for item in status["items"]} == {"configured"}
    with pytest.raises(DeployError) as error:
        service.submit(person(1), "https://github.com/team/demo", "demo", "cannot-overwrite", app_id,
                       commit="a" * 40, values={"API_KEY": "replacement"})
    assert error.value.code == "SECRET_ALREADY_CONFIGURED"
    assert len(service.store.list_jobs()) == 1


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


def test_preflight_api_requires_login_and_returns_only_metadata(deploy, monkeypatch):
    import asyncio
    from fastapi.testclient import TestClient
    from app.main import create_app

    app = create_app(deploy.settings, MemoryStore())
    with TestClient(app) as client:
        monkeypatch.setattr(app.state.deployment, "preflight", lambda user, repository, app_id=None: {
            "repository": "https://github.com/team/demo.git", "commit": "a" * 40,
            "subdomain": "demo", "canPreconfigure": True,
            "items": [{"name": "API_KEY", "uses": [{"service": "web", "environmentVariable": "MODEL_KEY"}],
                       "state": "missing", "managed": False}],
        })
        payload = {"repository": "https://github.com/team/demo"}
        assert client.post("/api/v1/deployment/preflight", json=payload).status_code == 401
        token = asyncio.run(app.state.auth.issue(person(1))).access_token
        response = client.post("/api/v1/deployment/preflight", json=payload,
                               headers={"Authorization": "Bearer " + token})
        assert response.status_code == 200
        assert response.json()["data"]["items"][0]["name"] == "API_KEY"
        assert "value" not in response.text.lower()


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


def test_list_jobs_marks_personal_ownership_and_excludes_superseded_app_updates(deploy):
    owner_user = person(1)
    admin_user = person(2)
    owner_actor = deploy.actor(owner_user)
    admin_actor = deploy.actor(admin_user)
    deploy.identity.set_user(admin_actor["id"], is_admin=True)

    # Person 1 creates 'upic', which goes online, then goes offline, and Person 2 creates a new 'upic'.
    old_job = deploy.store.enqueue(
        {"repository": "https://github.com/team/upic.git", "subdomain": "upic", "ref": "main"},
        "upic-old",
        actor=owner_actor,
    )
    terminal_state(deploy, old_job["id"], status="succeeded")
    with deploy.store._connection(write=True) as db:
        db.execute(
            "INSERT INTO offline_operations(id,idempotency_key,app_id,target_release_id,status,phase,created_at,updated_at) "
            "VALUES('off-upic','off-upic-k',?,?,'succeeded','complete',9999999999,9999999999)",
            (old_job["app_id"], old_job["id"]),
        )
        db.execute("DELETE FROM community_names WHERE name='upic'")

    new_job = deploy.store.enqueue(
        {"repository": "https://github.com/team/upic2.git", "subdomain": "upic", "ref": "main"},
        "upic-new",
        actor=deploy.actor(admin_user),
    )
    terminal_state(deploy, new_job["id"], status="succeeded")
    with deploy.store._connection(write=True) as db:
        db.execute("UPDATE apps SET subdomain='upic', active_release_id=? WHERE id=?", (new_job["id"], new_job["app_id"]))

    admin_list = {item["id"]: item for item in deploy.list_jobs(admin_user)}
    assert admin_list[new_job["id"]]["mine"] is True
    assert admin_list[new_job["id"]]["appOnline"] is True
    assert admin_list[new_job["id"]]["appUpdatable"] is True
    assert admin_list[old_job["id"]]["mine"] is False
    assert admin_list[old_job["id"]]["appOnline"] is False
    assert admin_list[old_job["id"]]["appUpdatable"] is False


def test_community_service_supports_both_github_and_internal_gitlab_with_proxy_bypass(deploy):
    from awesome_deploy.source import validate_repository

    assert "github.com" in deploy.engine.git_hosts
    assert "gitlab.yc345.tv" in deploy.engine.git_hosts
    assert "gitlab.yc345.tv" in deploy.engine.git_no_proxy_hosts
    assert (
        validate_repository("https://gitlab.yc345.tv/fengyang1/owsc", deploy.engine)
        == "https://gitlab.yc345.tv/fengyang1/owsc.git"
    )
    assert (
        validate_repository("https://github.com/IXYTYXI/onion_community", deploy.engine)
        == "https://github.com/IXYTYXI/onion_community.git"
    )


def test_git_askpass_helper_is_strictly_scoped_to_internal_gitlab(tmp_path):
    import subprocess
    from app.core.config import PROJECT_ROOT

    script = (PROJECT_ROOT / "deploy/deployment/git-askpass.sh").read_text(encoding="utf-8")
    token_file = tmp_path / "gitlab-git-token"
    token_file.write_text("glpat-test-readonly-token\n", encoding="utf-8")
    local_script = tmp_path / "git-askpass.sh"
    local_script.write_text(
        script.replace("/etc/awesome-deploy/gitlab-git-token", str(token_file)),
        encoding="utf-8",
    )
    local_script.chmod(0o755)

    gh = subprocess.run(
        [str(local_script), "Password for 'https://oauth2@github.com': "],
        capture_output=True,
        text=True,
        check=False,
    )
    assert gh.returncode != 0
    assert gh.stdout == ""

    gl_user = subprocess.run(
        [str(local_script), "Username for 'https://gitlab.yc345.tv': "],
        capture_output=True,
        text=True,
        check=False,
    )
    assert gl_user.returncode == 0
    assert gl_user.stdout.strip() == "oauth2"

    gl_pass = subprocess.run(
        [str(local_script), "Password for 'https://oauth2@gitlab.yc345.tv': "],
        capture_output=True,
        text=True,
        check=False,
    )
    assert gl_pass.returncode == 0
    assert gl_pass.stdout.strip() == "glpat-test-readonly-token"
