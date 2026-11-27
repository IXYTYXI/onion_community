"""SQLite source of truth for OWS install-prompt copy counts with Feishu Bitable projection."""
import asyncio
import fcntl
import hashlib
import json
import logging
import time
from uuid import UUID

from app.core.config import PROJECT_ROOT
from app.core.error_codes import ErrorCode
from app.core.errors import AppError
from app.integrations.bitable_writer import BitablePermissionError
from app.repositories.case_interactions import CaseInteractionDB
from app.services.case_engagement import activation_confirmed
from app.services.officers import text_value

NAME_FIELD = "姓名"
DEPT_FIELD = "所属部门"
COUNT_FIELD = "累计复制次数"
VERSION_FIELD = "最近复制版本"
FIRST_AT_FIELD = "首次复制时间"
LAST_AT_FIELD = "最近复制时间"
KEY_FIELD = "业务唯一键"
ACCOUNT_FIELD = "飞书账号标识"
OWS_COPY_FIELDS = [
    NAME_FIELD,
    DEPT_FIELD,
    COUNT_FIELD,
    VERSION_FIELD,
    FIRST_AT_FIELD,
    LAST_AT_FIELD,
    KEY_FIELD,
    ACCOUNT_FIELD,
]
LOGGER = logging.getLogger("ows_community")


def digest(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _positive_int(value) -> int | None:
    if type(value) is int and value > 0:
        return value
    if type(value) is float and value.is_integer() and value > 0:
        return int(value)
    return None


def _department_label(user) -> str:
    names = [d.name.strip() for d in (user.departments or []) if d.name and d.name.strip()]
    return " / ".join(dict.fromkeys(names))


class OwsCopyStatsService(CaseInteractionDB):
    def __init__(self, settings, path, writer=None):
        super().__init__(path)
        self.settings = settings
        self.writer = writer
        self.ready = False
        self.import_lock = asyncio.Lock()
        self.wakeup = asyncio.Event()
        self.after: str | None = None

    def scope(self) -> str:
        return digest(
            "ows-copy-stats/v1",
            self.settings.feishu_app_id,
            self.settings.feishu_bitable_app_token.get_secret_value(),
            self.settings.ows_copy_stats_table_id,
        )

    def account_key(self, scope: str, user) -> str:
        return digest(scope, user.identity_source, user.tenant_id, user.user_id)

    async def prepare(self):
        if self.ready:
            return

        def create(conn):
            conn.execute(
                """CREATE TABLE IF NOT EXISTS ows_copy_scopes (
                    scope TEXT PRIMARY KEY NOT NULL
                ) WITHOUT ROWID"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS ows_copy_stats (
                    scope TEXT NOT NULL,
                    account TEXT NOT NULL,
                    display_name TEXT NOT NULL DEFAULT '',
                    departments TEXT NOT NULL DEFAULT '',
                    copy_count INTEGER NOT NULL,
                    first_copied_at INTEGER NOT NULL,
                    last_copied_at INTEGER NOT NULL,
                    last_cli_version TEXT NOT NULL DEFAULT '',
                    revision INTEGER NOT NULL DEFAULT 0,
                    sync_pending INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (scope, account)
                ) WITHOUT ROWID"""
            )
            conn.execute(
                """CREATE INDEX IF NOT EXISTS ows_copy_sync_due
                   ON ows_copy_stats(scope, account)
                   WHERE sync_pending = 1"""
            )

        await self._run(create, write=True)
        self.ready = True

    async def _scope_initialized(self, scope: str) -> bool:
        await self.prepare()
        return await self._run(
            lambda c: c.execute("SELECT 1 FROM ows_copy_scopes WHERE scope=?", (scope,)).fetchone() is not None
        )

    async def ensure_initialized(self, scope: str):
        if await self._scope_initialized(scope):
            return
        async with self.import_lock:
            if await self._scope_initialized(scope):
                return
            imported = []
            if self.writer is not None:
                if self.settings.environment == "production" and not activation_confirmed(PROJECT_ROOT):
                    raise AppError(ErrorCode.SNAPSHOT_NOT_READY)
                async with asyncio.timeout(45):
                    rows = await self.writer.all_records()
                for row in rows:
                    fields = row.get("fields", {})
                    account = text_value(fields.get(ACCOUNT_FIELD))
                    count = _positive_int(fields.get(COUNT_FIELD))
                    if not account or not count or text_value(fields.get(KEY_FIELD)) != digest(scope, account):
                        continue
                    now_ms = time.time_ns() // 1_000_000
                    first_at = _positive_int(fields.get(FIRST_AT_FIELD)) or now_ms
                    last_at = _positive_int(fields.get(LAST_AT_FIELD)) or first_at
                    imported.append((
                        scope,
                        account,
                        text_value(fields.get(NAME_FIELD)),
                        text_value(fields.get(DEPT_FIELD)),
                        count,
                        first_at,
                        max(first_at, last_at),
                        text_value(fields.get(VERSION_FIELD)),
                    ))

            def seed(conn):
                if conn.execute("SELECT 1 FROM ows_copy_scopes WHERE scope=?", (scope,)).fetchone():
                    return
                if imported:
                    conn.executemany(
                        """INSERT INTO ows_copy_stats
                           (scope, account, display_name, departments, copy_count,
                            first_copied_at, last_copied_at, last_cli_version, revision, sync_pending)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0)
                           ON CONFLICT(scope, account) DO UPDATE SET
                             display_name = CASE WHEN excluded.display_name != '' THEN excluded.display_name ELSE ows_copy_stats.display_name END,
                             departments = CASE WHEN excluded.departments != '' THEN excluded.departments ELSE ows_copy_stats.departments END,
                             copy_count = MAX(ows_copy_stats.copy_count, excluded.copy_count),
                             first_copied_at = MIN(ows_copy_stats.first_copied_at, excluded.first_copied_at),
                             last_copied_at = MAX(ows_copy_stats.last_copied_at, excluded.last_copied_at),
                             last_cli_version = CASE WHEN excluded.last_cli_version != '' THEN excluded.last_cli_version ELSE ows_copy_stats.last_cli_version END""",
                        imported,
                    )
                conn.execute("INSERT INTO ows_copy_scopes(scope) VALUES (?)", (scope,))

            await self._run(seed, write=True)

    @staticmethod
    def _summary_query(conn, scope: str, account: str) -> dict[str, int]:
        totals = conn.execute(
            """SELECT COUNT(*) AS unique_users, COALESCE(SUM(copy_count), 0) AS total_copies
               FROM ows_copy_stats WHERE scope=?""",
            (scope,),
        ).fetchone()
        mine = conn.execute(
            "SELECT copy_count FROM ows_copy_stats WHERE scope=? AND account=?",
            (scope, account),
        ).fetchone()
        return {
            "unique_users": int(totals["unique_users"]),
            "total_copies": int(totals["total_copies"]),
            "my_copies": int(mine["copy_count"]) if mine else 0,
        }

    async def summary(self, user) -> dict[str, int]:
        scope = self.scope()
        await self.ensure_initialized(scope)
        account = self.account_key(scope, user)
        return await self._run(lambda c: self._summary_query(c, scope, account))

    async def record_copy(self, user, cli_version: str | None = None) -> dict[str, int]:
        scope = self.scope()
        await self.ensure_initialized(scope)
        account = self.account_key(scope, user)
        now = time.time_ns() // 1_000_000
        version = f"v{cli_version.lstrip('v')}" if cli_version and cli_version.strip() else ""
        should_sync = int(
            self.writer is not None
            and user.identity_source == "feishu"
            and bool(user.tenant_id and user.user_id)
        )
        name = (user.display_name or "").strip()
        depts = _department_label(user)

        def apply(conn):
            conn.execute(
                """INSERT INTO ows_copy_stats
                   (scope, account, display_name, departments, copy_count,
                    first_copied_at, last_copied_at, last_cli_version, revision, sync_pending)
                   VALUES (?, ?, ?, ?, 1, ?, ?, ?, 1, ?)
                   ON CONFLICT(scope, account) DO UPDATE SET
                     display_name = CASE WHEN excluded.display_name != '' THEN excluded.display_name ELSE ows_copy_stats.display_name END,
                     departments = CASE WHEN excluded.departments != '' THEN excluded.departments ELSE ows_copy_stats.departments END,
                     copy_count = ows_copy_stats.copy_count + 1,
                     last_copied_at = MAX(ows_copy_stats.last_copied_at, excluded.last_copied_at),
                     last_cli_version = CASE WHEN excluded.last_cli_version != '' THEN excluded.last_cli_version ELSE ows_copy_stats.last_cli_version END,
                     revision = ows_copy_stats.revision + 1,
                     sync_pending = MAX(ows_copy_stats.sync_pending, excluded.sync_pending)""",
                (scope, account, name, depts, now, now, version, should_sync),
            )
            return self._summary_query(conn, scope, account)

        result = await self._run(apply, write=True)
        if should_sync:
            self.wakeup.set()
        return result

    async def _pending_sync(self, scope: str, limit: int = 50, after: str | None = None) -> list[dict]:
        await self.prepare()

        def read(conn):
            cursor = " AND account > ?" if after is not None else ""
            params = (scope, after, limit) if after is not None else (scope, limit)
            rows = conn.execute(
                f"""SELECT account, display_name, departments, copy_count,
                           first_copied_at, last_copied_at, last_cli_version, revision
                    FROM ows_copy_stats
                    WHERE scope=? AND sync_pending=1{cursor}
                    ORDER BY account LIMIT ?""",
                params,
            )
            return [dict(row) for row in rows]

        return await self._run(read)

    async def _ack_sync(self, scope: str, account: str, revision: int) -> bool:
        def ack(conn):
            updated = conn.execute(
                """UPDATE ows_copy_stats SET sync_pending=0
                   WHERE scope=? AND account=? AND revision=? AND sync_pending=1""",
                (scope, account, revision),
            )
            return updated.rowcount == 1

        return await self._run(ack, write=True)

    async def project(self, scope: str, row: dict) -> bool:
        account = row["account"]
        key = digest(scope, account)
        projection = {
            NAME_FIELD: row["display_name"],
            DEPT_FIELD: row["departments"],
            COUNT_FIELD: row["copy_count"],
            VERSION_FIELD: row["last_cli_version"],
            FIRST_AT_FIELD: row["first_copied_at"],
            LAST_AT_FIELD: row["last_copied_at"],
        }
        matches = await self.writer.all_records(
            record_filter={"conjunction": "and", "conditions": [{"field_name": KEY_FIELD, "operator": "is", "value": [key]}]}
        )
        if matches:
            if any(text_value(m["fields"].get(KEY_FIELD)) != key for m in matches):
                raise AppError(ErrorCode.UPSTREAM_ERROR)
            updates = [{"record_id": m["record_id"], "fields": projection} for m in matches]
            for start in range(0, len(updates), 200):
                await self.writer.write(updates[start : start + 200], update=True)
        else:
            fields = {KEY_FIELD: key, ACCOUNT_FIELD: account, **projection}
            created = await self.writer.create_once(fields, str(UUID(hex=key[:32], version=4)))
            ack = created.get("fields", {})
            if not created.get("record_id") or text_value(ack.get(KEY_FIELD)) != key:
                raise AppError(ErrorCode.UPSTREAM_ERROR)
            if _positive_int(ack.get(COUNT_FIELD)) != projection[COUNT_FIELD] or _positive_int(
                ack.get(LAST_AT_FIELD)
            ) != projection[LAST_AT_FIELD]:
                await self.writer.write([{"record_id": created["record_id"], "fields": projection}], update=True)
        return await self._ack_sync(scope, account, row["revision"])

    async def sync_once(self) -> int:
        if self.writer is None:
            return 0
        scope = self.scope()
        if not await self._scope_initialized(scope):
            return 0
        completed = 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix(".ows-copy.lock").open("a+b") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return 0
            batch = await self._pending_sync(scope, after=self.after)
            if not batch and self.after is not None:
                self.after = None
                batch = await self._pending_sync(scope)
            for row in batch:
                self.after = row["account"]
                try:
                    async with asyncio.timeout(90):
                        completed += int(await self.project(scope, row))
                except BitablePermissionError as exc:
                    LOGGER.warning("ows_copy_projection_permission_denied", extra={"upstream_code": exc.upstream_code})
                    break
                except Exception as exc:
                    LOGGER.warning("ows_copy_projection_deferred", extra={"exception_type": type(exc).__name__})
                    break
        return completed

    async def run(self):
        while True:
            self.wakeup.clear()
            try:
                if await self.sync_once():
                    continue
            except Exception as exc:
                LOGGER.warning("ows_copy_projection_unavailable", extra={"exception_type": type(exc).__name__})
            try:
                await asyncio.wait_for(self.wakeup.wait(), timeout=5)
            except TimeoutError:
                pass
