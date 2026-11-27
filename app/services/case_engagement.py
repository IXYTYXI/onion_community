"""Serve interactions from SQLite and deliver committed revisions to the Feishu projection."""
import asyncio
import fcntl
import hashlib
import json
import logging
from contextlib import AsyncExitStack
from uuid import UUID, uuid4

from app.core.config import PROJECT_ROOT
from app.core.error_codes import ErrorCode
from app.core.errors import AppError
from app.integrations.bitable_writer import BitableLinkError
from app.schemas.cases import EngagementDirectory
from app.services.case_coins import recipient
from app.services.officers import text_value

KEY, CASE, ACCOUNT = '业务唯一键', '案例ID', '飞书账号标识'
CASE_LINK = '关联案例'
LIKE, FAVORITE = '是否点赞', '是否收藏'
LIKED_AT, FAVORITED_AT = '点赞时间', '收藏时间'
ENGAGEMENT_FIELDS = [KEY, CASE, ACCOUNT, LIKE, FAVORITE, LIKED_AT, FAVORITED_AT]
LOGGER = logging.getLogger('ows_community')


def digest(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def legacy_timestamp(value):
    return value if type(value) is int and value > 0 else None


def activation_confirmed(source):
    # Non-CI installations do not use the blue/green release marker.
    if source.name != 'source' or source.parent.parent.name != '.releases':
        return True
    try:
        commit = (source / '.release-commit').read_text().strip()
        return bool(commit) and commit == (source.parents[2] / '.release-commit').read_text().strip()
    except OSError:
        return False


def case_metadata(item):
    author_id, author_name = recipient(item)
    return {'title': item.title, 'author_id': author_id, 'author_name': author_name}


class CaseEngagementService:
    def __init__(self, store, writer, settings, db, site=None):
        self.site = site
        self.store, self.writer, self.settings, self.db = store, writer, settings, db
        self.import_lock = asyncio.Lock()
        self.after = None

    def scope(self):
        return digest('case-engagement/v1', self.settings.feishu_app_id,
                      self.settings.feishu_bitable_app_token.get_secret_value(), self.settings.cases_table_id)

    def identity(self, user):
        if user.identity_source != 'feishu' or not user.user_id or not user.tenant_id:
            raise AppError(ErrorCode.FORBIDDEN)
        if not all((self.settings.feishu_app_id, self.settings.cases_table_id,
                    self.settings.feishu_bitable_app_token.get_secret_value(), self.settings.cases_engagement_table_id)):
            raise AppError(ErrorCode.SERVICE_UNAVAILABLE)
        scope = self.scope()
        return scope, digest(scope, user.tenant_id, user.user_id)

    @staticmethod
    async def visible_cases(cases):
        directory = await cases.read()
        if directory.stale:
            raise AppError(ErrorCode.SNAPSHOT_NOT_READY)
        return {item.id: item for item in directory.items}

    async def import_existing(self, scope, visible):
        if await self.db.is_initialized(scope):
            return
        async with self.import_lock, AsyncExitStack() as leases:
            if await self.db.is_initialized(scope):
                return
            # Bootstrap is initiated through the routed API. Drain old-slot writes using
            # the previous release's per-case lease before taking the one-time snapshot.
            if self.settings.environment == 'production':
                if not activation_confirmed(PROJECT_ROOT):
                    raise AppError(ErrorCode.SNAPSHOT_NOT_READY)
                owner = uuid4().hex
                async with asyncio.timeout(175):
                    for case in sorted(visible):
                        key = 'case-engagement:lock:' + digest(scope, self.settings.cases_engagement_table_id, case)
                        while not await self.store.acquire(key, owner, 300):
                            if await self.db.is_initialized(scope):
                                return
                            await asyncio.sleep(.2)
                        leases.push_async_callback(self.store.release, key, owner)
                # The old writer waits up to eight seconds before abandoning its queued write.
                await asyncio.sleep(8.1)
            async with asyncio.timeout(65):
                rows = await self.writer.all_records()
            imported = []
            for row in rows:
                fields = row['fields']
                case_id, account = text_value(fields.get(CASE)), text_value(fields.get(ACCOUNT))
                if not case_id or not account or text_value(fields.get(KEY)) != digest(scope, case_id, account):
                    continue
                if any(fields.get(flag) is not None and type(fields[flag]) is not bool for flag in (LIKE, FAVORITE)):
                    raise AppError(ErrorCode.UPSTREAM_ERROR)
                imported.append({'case_id': case_id, 'account': account, 'liked': bool(fields.get(LIKE)),
                                 'favorited': bool(fields.get(FAVORITE)), 'liked_at': legacy_timestamp(fields.get(LIKED_AT)),
                                 'favorited_at': legacy_timestamp(fields.get(FAVORITED_AT))})
            await self.db.import_rows(scope, imported, {k: case_metadata(v) for k, v in visible.items()})

    async def directory(self, cases, user, personal=None):
        scope, account = self.identity(user)
        switches = (await self.site.current()).personal if self.site else self.settings.case_personal_lists
        if personal and switches[0 if personal == 'like' else 1] == '0':
            raise AppError(ErrorCode.NOT_FOUND)
        visible = await self.visible_cases(cases)
        await self.import_existing(scope, visible)
        items = await self.db.directory(scope, account, visible)
        if personal:
            flag, date = ('liked', 'liked_at') if personal == 'like' else ('favorited', 'favorited_at')
            selected = [(case, item) for case, item in items.items() if getattr(item, flag)]
            items = dict(sorted(selected, key=lambda entry: (-(getattr(entry[1], date) or 0), entry[0])))
        return EngagementDirectory(personal_lists=switches, items=items)

    async def set_active(self, cases, user, case, action, active):
        scope, account = self.identity(user)
        visible = await self.visible_cases(cases)
        if case not in visible:
            raise AppError(ErrorCode.NOT_FOUND)
        await self.import_existing(scope, visible)
        return await self.db.set_active(scope, account, case, action, active, case_metadata(visible[case]))

    async def _write_batches(self, records, payload):
        updates = [{'record_id': item['record_id'], 'fields': payload} for item in records]
        for start in range(0, len(updates), 200):
            await self.writer.write(updates[start:start + 200], update=True)

    async def project(self, scope, row):
        case, account = row['case_id'], row['account']
        key = digest(scope, case, account)
        projection = {LIKE: row['liked'], FAVORITE: row['favorited'],
                      LIKED_AT: row['liked_at'], FAVORITED_AT: row['favorited_at']}
        linked_projection = {**projection, CASE_LINK: [case]}
        matches = await self.writer.all_records(record_filter={'conjunction': 'and', 'conditions': [
            {'field_name': KEY, 'operator': 'is', 'value': [key]}]})
        if matches:
            if any(text_value(match['fields'].get(KEY)) != key for match in matches):
                raise AppError(ErrorCode.UPSTREAM_ERROR)
            try:
                await self._write_batches(matches, linked_projection)
            except BitableLinkError:
                await self._write_batches(matches, projection)
        else:
            # Feishu can replay a previous create acknowledgement after an ambiguous
            # timeout. Verify acknowledged values before clearing this local revision.
            used_projection = linked_projection
            try:
                created = await self.writer.create_once(
                    {KEY: key, CASE: case, ACCOUNT: account, **linked_projection},
                    str(UUID(hex=key[:32], version=4)),
                )
            except BitableLinkError:
                used_projection = projection
                fallback_key = digest('case-engagement/no-link/v1', key)
                created = await self.writer.create_once(
                    {KEY: key, CASE: case, ACCOUNT: account, **projection},
                    str(UUID(hex=fallback_key[:32], version=4)),
                )
            ack = created.get('fields', {})
            if not created.get('record_id') or text_value(ack.get(KEY)) != key:
                raise AppError(ErrorCode.UPSTREAM_ERROR)
            if any(bool(ack.get(f)) != projection[f] for f in (LIKE, FAVORITE)) or any(
                    ack.get(f) != projection[f] for f in (LIKED_AT, FAVORITED_AT)):
                try:
                    await self.writer.write([{'record_id': created['record_id'], 'fields': used_projection}], update=True)
                except BitableLinkError:
                    await self.writer.write([{'record_id': created['record_id'], 'fields': projection}], update=True)
        return await self.db.ack_sync(scope, case, account, row['revision'])

    async def sync_once(self):
        scope = self.scope()
        if not await self.db.is_initialized(scope):
            return 0
        completed = 0
        with self.db.path.with_suffix('.mirror.lock').open('a+b') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return 0
            batch = await self.db.pending_sync(scope, after=self.after)
            if not batch and self.after is not None:
                self.after = None
                batch = await self.db.pending_sync(scope)
            for row in batch:
                self.after = (row['case_id'], row['account'])
                try:
                    async with asyncio.timeout(110):
                        completed += await self.project(scope, row)
                except Exception as exc:
                    LOGGER.warning('case_projection_deferred', extra={'exception_type': type(exc).__name__})
                    break
        return completed

    async def run(self):
        while True:
            try:
                if await self.sync_once():
                    continue
            except Exception as exc:
                LOGGER.warning('case_projection_unavailable', extra={'exception_type': type(exc).__name__})
            await asyncio.sleep(5)
