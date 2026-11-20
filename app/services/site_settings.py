"""Shared site switches and anonymous aggregate visitor counts for both API slots."""
import asyncio
import fcntl
import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.error_codes import ErrorCode
from app.core.errors import AppError
from app.repositories.case_interactions import CaseInteractionDB
from app.services.officers import text_value

FIELDS = ["配置名称", "访客统计展示", "账本同步", "个人列表展示"]
SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class Switches:
    visitors: bool
    ledger: bool
    personal: str


class SiteState(CaseInteractionDB):
    def __init__(self, settings, source):
        super().__init__(settings.case_interactions_db)
        self.source = source
        self.settings = settings
        self.scope = json.dumps([settings.feishu_app_id, settings.coin_base_token.get_secret_value(),
                                 settings.site_switch_table_id], separators=(",", ":"))
        self.ready = False

    async def prepare(self):
        if self.ready:
            return
        def create(conn):
            conn.execute("CREATE TABLE IF NOT EXISTS site_switches (scope TEXT PRIMARY KEY, value TEXT NOT NULL)")
            conn.execute("""CREATE TABLE IF NOT EXISTS site_visitors
                         (account TEXT PRIMARY KEY, last_seen INTEGER NOT NULL) WITHOUT ROWID""")
            conn.execute("CREATE INDEX IF NOT EXISTS site_seen ON site_visitors(last_seen)")
        await self._run(create, write=True)
        self.ready = True

    async def current(self):
        if self.source is None:
            return Switches(False, True, self.settings.case_personal_lists)
        await self.prepare()
        row = await self._run(lambda c: c.execute("SELECT value FROM site_switches WHERE scope=?", (self.scope,)).fetchone())
        if row is None:
            return Switches(False, False, self.settings.case_personal_lists)
        return Switches(**json.loads(row[0]))

    async def refresh(self):
        if self.source is None:
            raise AppError(ErrorCode.SERVICE_UNAVAILABLE)
        await self.prepare()
        # Serialize fetch AND publication across workers, including during blue/green overlap.
        with self.path.with_suffix(".switches.lock").open("a+b") as lock:
            async with asyncio.timeout(55):
                while True:
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        await asyncio.sleep(.1)
                records = await self.source.all_records()
                rows = [r["fields"] for r in records if text_value(r["fields"].get(FIELDS[0])) == "生产配置"]
                if len(rows) != 1:
                    raise AppError(ErrorCode.UPSTREAM_ERROR)
                visitors, ledger, personal = [text_value(rows[0].get(k)) for k in FIELDS[1:]]
                if visitors not in {"0", "1"} or ledger not in {"0", "1"} or personal not in {"00","01","10","11"}:
                    raise AppError(ErrorCode.UPSTREAM_ERROR)
                flags = Switches(visitors == "1", ledger == "1", personal)
                await self._run(lambda c: c.execute("INSERT OR REPLACE INTO site_switches VALUES (?,?)",
                                                    (self.scope, json.dumps(asdict(flags)))), write=True)
                return flags

    async def bootstrap(self):
        while True:
            try:
                await self.refresh()
                return
            except Exception:
                logging.getLogger("ows_community").warning("site_switch_bootstrap_deferred")
                await asyncio.sleep(60)

    async def visitors(self, user, active, now=None):
        flags = await self.current()
        now = int(time.time()) if now is None else now
        midnight = int(datetime.fromtimestamp(now, SHANGHAI).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        account = hashlib.sha256(json.dumps([self.settings.feishu_app_id, user.tenant_id, user.user_id],
                                            separators=(",", ":")).encode()).hexdigest()
        await self.prepare()
        def collect(conn):
            if active and user.identity_source == "feishu" and user.tenant_id and user.user_id:
                conn.execute("""INSERT INTO site_visitors VALUES (?,?) ON CONFLICT(account) DO UPDATE
                             SET last_seen=MAX(site_visitors.last_seen, excluded.last_seen)""", (account, now))
            if not flags.visitors:
                return None
            return dict(conn.execute("""SELECT (SELECT COUNT(*) FROM site_visitors) total,
                        (SELECT COUNT(*) FROM site_visitors WHERE last_seen>=?) today,
                        (SELECT COUNT(*) FROM site_visitors WHERE last_seen>?) online""", (midnight, now-300)).fetchone())
        return {"counts": await self._run(collect, write=active), "personal_lists": flags.personal}
