import re
import secrets
import time
from dataclasses import replace

from awesome_deploy.access import AccessStore
from awesome_deploy.cli import load_settings
from awesome_deploy.config import Settings as EngineSettings
from awesome_deploy.deployment_secrets import DeploymentSecrets
from awesome_deploy.errors import DeployError
from awesome_deploy.identity import IdentityStore
from awesome_deploy.management import public_application
from awesome_deploy.source import GitSource, validate_repository
from awesome_deploy.secrets_store import SecretStore
from awesome_deploy.secret_vault import SecretVault

from app.deployment.store import CommunityDeploymentStore


class LazyEligibility:
    def __init__(self, settings):
        self.settings = settings

    def check_eligible(self, open_id):
        from awesome_deploy.feishu import FeishuProvider

        provider = FeishuProvider(self.settings)
        try:
            return provider.check_eligible(open_id)
        finally:
            provider.close()


class DeploymentService:
    def __init__(self, settings):
        self.settings = settings
        base = (
            load_settings(settings.deploy_engine_config)
            if settings.deploy_engine_config
            else EngineSettings(
                state_dir=settings.deploy_state_root,
                max_cpu=2,
                max_memory_mib=2048,
                required_free_mib=4096,
                port_start=22000,
                port_end=22999,
                builder_name="ows-deploy-builder",
            )
        )
        # Local development never executes Docker. Production config retains continuous
        # eligibility checks; the community login replaces only the OAuth entry point.
        tenant = settings.deploy_tenant_id or (
            settings.feishu_allowed_tenants[0]
            if settings.feishu_allowed_tenants
            else ""
        )
        if settings.deploy_engine_config and (
            base.auth_mode != "feishu"
            or base.feishu_app_id != settings.feishu_app_id
            or base.feishu_tenant_key != tenant
            or base.feishu_eligibility_mode not in ("continuous", "app_visibility")
        ):
            raise ValueError("部署引擎身份必须与社区一致，并启用 continuous 或 app_visibility 资格校验")
        self.engine = replace(
            base,
            auth_mode="feishu",
            feishu_app_id=settings.feishu_app_id,
            feishu_tenant_key=tenant,
        )
        if (
            base.port_start <= settings.port <= base.port_end
            or base.port_start <= settings.frontend_port <= base.port_end
            or any(base.port_start <= p <= base.port_end for p in (80, 443, 6379))
        ):
            raise ValueError("部署容器端口范围不能包含社区服务端口")
        self.store = CommunityDeploymentStore(self.engine)
        self.identity = IdentityStore(
            self.engine, provider=LazyEligibility(self.engine),
            shared_database_gid=settings.deploy_database_gid,
        )
        self.access = AccessStore(self.engine, identity=self.identity)
        self.secrets = DeploymentSecrets(self.engine, self.store)
        self.install_outbox()

    def install_outbox(self):
        with self.store._connection() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS community_sync (
              kind TEXT NOT NULL, entity_id TEXT NOT NULL, target TEXT NOT NULL,
              revision INTEGER NOT NULL DEFAULT 1, done_revision INTEGER NOT NULL DEFAULT 0,
              attempts INTEGER NOT NULL DEFAULT 0, retry_at REAL NOT NULL DEFAULT 0,
              PRIMARY KEY(kind,entity_id,target));
            CREATE INDEX IF NOT EXISTS community_sync_due ON community_sync(retry_at);
            CREATE TABLE IF NOT EXISTS community_sync_records (
              kind TEXT NOT NULL, entity_id TEXT NOT NULL, table_id TEXT NOT NULL, record_id TEXT NOT NULL,
              PRIMARY KEY(kind,entity_id,table_id));
            """)
            for table, kind in [("jobs", "job"), ("apps", "app")]:
                for event in ["INSERT", "UPDATE"]:
                    db.executescript(f"""
                    BEGIN IMMEDIATE;
                    DROP TRIGGER IF EXISTS community_{table}_{event.lower()};
                    CREATE TRIGGER community_{table}_{event.lower()}
                    AFTER {event} ON {table} BEGIN
                      INSERT INTO community_sync(kind,entity_id,target) VALUES('{kind}',NEW.id,'redis')
                      ON CONFLICT(kind,entity_id,target) DO UPDATE SET revision=revision+1;
                      INSERT INTO community_sync(kind,entity_id,target) VALUES('{kind}',NEW.id,'feishu')
                      ON CONFLICT(kind,entity_id,target) DO UPDATE SET revision=revision+1;
                    END;
                    COMMIT;""")
                for target in ["redis", "feishu"]:
                    db.execute(
                        f"INSERT OR IGNORE INTO community_sync(kind,entity_id,target) SELECT ?,id,? FROM {table}",
                        (kind, target),
                    )

    def actor(self, user):
        if (
            user.identity_source != "feishu"
            or not self.engine.feishu_tenant_key
            or user.tenant_id != self.engine.feishu_tenant_key
        ):
            raise DeployError("ACCESS_DENIED", "部署需要本组织的飞书身份。")
        if (
            self.settings.deploy_allowed_users
            and user.user_id not in self.settings.deploy_allowed_users
        ):
            raise DeployError("ACCESS_DENIED", "当前用户未开通部署权限。")
        prefix = f"feishu:{self.engine.feishu_app_id}:"
        if not user.user_id.startswith(prefix):
            raise DeployError("ACCESS_DENIED", "飞书应用身份不匹配。")
        open_id = user.user_id[len(prefix) :]
        with self.identity.connection() as db:
            row = db.execute(
                "SELECT * FROM auth_users WHERE app_id=? AND tenant_key=? AND open_id=?",
                (self.engine.feishu_app_id, user.tenant_id, open_id),
            ).fetchone()
        if row:
            actor = dict(row)
            if not actor["enabled"] or not actor["eligible"]:
                raise DeployError("ACCESS_DENIED", "部署账号已停用。")
            return actor
        return self.identity.login_user(
            {
                "open_id": open_id,
                "tenant_key": user.tenant_id,
                "name": user.display_name,
            }
        )

    def executor_ready(self):
        if not self.settings.deploy_execution_enabled:
            return False
        with self.store._connection() as db:
            row = (
                db.execute(
                    "SELECT value FROM community_runtime WHERE key='heartbeat'"
                ).fetchone()
                if db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='community_runtime'"
                ).fetchone()
                else None
            )
        return bool(row and 0 <= time.time() - float(row[0]) < 30)

    def validate_name(self, name):
        if (
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,5}[a-z0-9])?", name)
            or name in self.engine.reserved_names
            or any(w in name for w in self.engine.banned_words)
        ):
            raise DeployError("INVALID_SUBDOMAIN", "项目名称不符合规则或属于保留名称。")

    def name_available(self, user, name, app_id=None):
        actor = self.actor(user)
        self.validate_name(name)
        if app_id:
            self.access.require_app(actor, app_id, "deploy")
        with self.store._connection() as db:
            row = db.execute(
                "SELECT app_id FROM community_names WHERE name=?", (name,)
            ).fetchone()
            legacy = db.execute(
                "SELECT id FROM apps WHERE subdomain=?", (name,)
            ).fetchone()
        owner = row[0] if row else legacy[0] if legacy else None
        return owner is None or owner == app_id

    def preflight(self, user, repository, app_id=None):
        actor = self.actor(user)
        if not actor["can_deploy"]:
            raise DeployError("ACCESS_DENIED", "当前用户没有部署权限。")
        repository = validate_repository(repository, self.engine)
        previous = None
        if app_id:
            self.access.require_app(actor, app_id, "deploy")
            with self.store._connection() as db:
                app = db.execute("SELECT repository,subdomain FROM apps WHERE id=?", (app_id,)).fetchone()
            if not app or app["repository"] != repository:
                raise DeployError("APP_IDENTITY_CONFLICT", "所选应用与仓库不匹配。")
            release = self.store.active_release(app_id)
            previous = (release.get("snapshot") or {}).get("manifest") if release else None
        inspected = GitSource(self.engine).inspect(repository, previous=previous)
        manifest = inspected["manifest"]
        subdomain = manifest["app"]["subdomain"]
        if app_id and app["subdomain"] is not None and app["subdomain"] != subdomain:
            raise DeployError("APP_IDENTITY_CONFLICT", "所选应用与 awesome.yaml 的项目名称不一致。")
        uses = {}
        for service, definition in sorted(manifest["services"].items()):
            for variable, name in sorted(definition.get("secretRefs", {}).items()):
                uses.setdefault(name, []).append({"service": service, "environmentVariable": variable})
        existing = {}
        if app_id:
            if self.engine.secret_backend == "encrypted":
                with self.store._connection() as db:
                    existing = {item["name"]: item for item in self.secrets._vault().metadata(db, app_id)}
            else:
                existing = {name: {"state": self.secrets.secrets.inspect(repository, subdomain, name)}
                            for name in uses}
        items = []
        for name, locations in sorted(uses.items()):
            record = existing.get(name)
            declared_master = any(use["environmentVariable"] == "MASTER_KEY" for use in locations)
            if record and "kind" in record and declared_master and record["kind"] != "platform_managed_master":
                raise DeployError("SECRET_KIND_CONFLICT", "已有运行密钥不能改为数据主密钥。")
            managed = record.get("kind") == "platform_managed_master" if record and "kind" in record else declared_master
            if record and "versions" in record:
                current = next((version for version in record["versions"]
                                if version["version"] == record["current_version"]), None)
                state = "configured" if current and current["status"] == "active" else "unavailable"
            else:
                state = record["state"] if record else "missing"
            items.append({"name": name, "uses": locations, "state": state, "managed": managed})
        return {"repository": repository, "commit": inspected["commit"], "subdomain": subdomain,
                "canPreconfigure": self.engine.secret_backend == "encrypted", "items": items}

    def _save_preflight_values(self, db, app_id, actor, items, values):
        """Create only missing encrypted values inside the job admission transaction."""
        if not isinstance(values, dict) or len(values) > 2048:
            raise DeployError("INVALID_REQUEST", "密钥配置格式不正确。")
        declared = {item["name"]: item for item in items}
        if set(values) - declared.keys():
            raise DeployError("INVALID_REQUEST", "只能填写 awesome.yaml 声明的密钥。")
        vault = SecretVault(self.engine)
        existing = {item["name"]: item for item in vault.metadata(db, app_id)}
        pending = []
        for name, item in declared.items():
            record = existing.get(name)
            managed = item["managed"]
            if record:
                expected = "platform_managed_master" if managed else "runtime_secret"
                if record["kind"] != expected:
                    raise DeployError("SECRET_KIND_CONFLICT", "已有密钥类型与仓库声明不一致。")
                current = next((version for version in record["versions"]
                                if version["version"] == record["current_version"]), None)
                if not current or current["status"] != "active":
                    raise DeployError("SECRET_UNAVAILABLE", "已有密钥需要恢复，请联系管理员。")
                if name in values:
                    raise DeployError("SECRET_ALREADY_CONFIGURED", "已有密钥不能通过部署向导覆盖。")
                continue
            if managed:
                app = db.execute("SELECT active_release_id FROM apps WHERE id=?", (app_id,)).fetchone()
                prior = db.execute("SELECT 1 FROM jobs WHERE app_id=? LIMIT 1", (app_id,)).fetchone()
                if not app or app["active_release_id"] or prior:
                    raise DeployError("SECRET_UNAVAILABLE", "原有平台密钥需要恢复，不能生成替代值。")
                pending.append((name, secrets.token_hex(32), "platform_managed_master"))
            else:
                if name not in values:
                    raise DeployError("SECRET_NOT_FOUND", f"请填写 {name}。", "secretRefs")
                SecretStore.validate_value(values[name])
                pending.append((name, values[name], "runtime_secret"))
        for name, value, kind in pending:
            vault.create_missing(db, app_id, name, value, kind=kind, actor_id=actor["id"])

    def submit(self, user, repository, name, key, app_id=None, *, commit=None, values=None):
        actor = self.actor(user)
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", key):
            raise DeployError("INVALID_IDEMPOTENCY_KEY", "缺少有效的请求编号。")
        self.validate_name(name)
        if values is not None and not isinstance(values, dict):
            raise DeployError("INVALID_REQUEST", "密钥配置格式不正确。")
        if commit is None and values:
            raise DeployError("INVALID_REQUEST", "请先检查仓库配置。")
        if commit is not None and (not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit)):
            raise DeployError("INVALID_REQUEST", "仓库版本不正确，请重新检查。")
        payload = {
            "repository": validate_repository(repository, self.engine),
            "subdomain": name,
            "ref": "main",
        }
        if commit is not None:
            payload["expectedCommit"] = commit
        if app_id:
            payload["appId"] = app_id
        # Retrying an accepted request still returns its durable result while the
        # executor is stopped; readiness gates only creation of new work.
        with self.store._connection() as db:
            prior = db.execute(
                "SELECT id FROM jobs WHERE idempotency_key=?",
                (AccessStore.scoped_key(actor, "job", key),),
            ).fetchone()
        if prior:
            return self.project_job(self.store.enqueue(payload, key, actor=actor))
        inspected = None
        if commit is not None:
            inspected = self.preflight(user, repository, app_id)
            if inspected["commit"] != commit:
                raise DeployError("PREFLIGHT_STALE", "仓库 main 分支已更新，请重新检查配置。")
            if inspected["subdomain"] != name:
                raise DeployError("SUBDOMAIN_MISMATCH", "项目名称必须与 awesome.yaml 的 app.subdomain 一致。")
            if values and not inspected["canPreconfigure"]:
                raise DeployError("SECRET_PRECONFIGURATION_UNAVAILABLE", "当前密钥库不能在部署前保存密钥。")
            if values and not inspected["items"]:
                raise DeployError("INVALID_REQUEST", "awesome.yaml 未声明需要填写的密钥。")
        if not self.settings.deploy_execution_enabled:
            raise DeployError(
                "EXECUTOR_UNAVAILABLE", "部署执行环境尚未启用，未创建任务。"
            )
        if not self.executor_ready():
            raise DeployError(
                "EXECUTOR_UNAVAILABLE", "部署 Worker 未就绪，请稍后重试。"
            )
        if inspected and inspected["items"] and inspected["canPreconfigure"]:
            with self.secrets._worker_lock():
                job = self.store.enqueue(payload, key, actor=actor, on_app_ready=lambda db, app_id, fresh:
                    self._save_preflight_values(db, app_id, fresh, inspected["items"], values or {}))
        else:
            job = self.store.enqueue(payload, key, actor=actor)
        return self.project_job(job)

    def project_job(self, job):
        active = self.store.active_release(job["app_id"]) if job.get("app_id") else None
        return {
            "id": job["id"],
            "appId": job["app_id"],
            "status": job["status"],
            "phase": job["phase"],
            "terminal": job["status"]
            in ["succeeded", "failed", "recovery_required", "cancelled"],
            "repository": job["input"]["repository"],
            "subdomain": job["input"]["subdomain"],
            "commit": (job.get("snapshot") or {}).get("commit"),
            "updatedAt": job["updated_at"],
            "url": f"https://{job['input']['subdomain']}.{self.engine.base_domain}"
            if job["status"] == "succeeded" or (active and active["id"] == job["id"])
            else None,
            "error": {
                "code": job["error"]["code"],
                "message": job["error"].get("message", "部署失败"),
                "field": job["error"].get("path", ""),
                "suggestion": job["error"].get("suggestion", ""),
            }
            if job.get("error")
            else None,
        }

    def get_job(self, user, job_id):
        actor = self.actor(user)
        job = self.store.get(job_id)
        self.access.require_job(actor, job)
        return self.project_job(job)

    def secret_requirements(self, user, job_id):
        return self.secrets.describe(job_id, actor=self.actor(user))

    def save_secret_values(self, user, job_id, values):
        return self.secrets.save(job_id, values, actor=self.actor(user))

    def list_jobs(self, user):
        return [
            self.project_job(j) for j in self.store.list_jobs(actor=self.actor(user))
        ]

    def snapshot(self, kind, entity_id):
        if kind == "job":
            return self.project_job(self.store.get(entity_id))
        app = self.store.application_snapshot(entity_id)
        return public_application(app, self.engine.base_domain) if app else None
