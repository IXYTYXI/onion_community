"""Feishu is the source of truth for both personal actions and public case totals."""
import asyncio
import hashlib
import json
import secrets
import time
from uuid import UUID

import httpx

from app.core.error_codes import ErrorCode
from app.core.errors import AppError
from app.schemas.cases import CaseEngagement, EngagementDirectory
from app.services.officers import text_value

KEY, CASE, ACCOUNT = '业务唯一键', '案例ID', '飞书账号标识'
LIKE, FAVORITE = '是否点赞', '是否收藏'
LIKED_AT, FAVORITED_AT = '点赞时间', '收藏时间'
ENGAGEMENT_FIELDS = [KEY, CASE, ACCOUNT, LIKE, FAVORITE, LIKED_AT, FAVORITED_AT]
SUMMARY_TTL_SECONDS = 30


def digest(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def timestamp(rows, flag, date):
    values = [r['fields'].get(date) for r in rows if r['fields'].get(flag) is True]
    return max((v for v in values if type(v) is int and v > 0), default=None)


def aggregate(accounts):
    members = {}
    like_count = favorite_count = 0
    for account, rows in accounts.items():
        liked = any(r['fields'].get(LIKE) is True for r in rows)
        favorited = any(r['fields'].get(FAVORITE) is True for r in rows)
        if liked or favorited:
            members[account] = {'liked': liked, 'favorited': favorited,
                                'liked_at': timestamp(rows, LIKE, LIKED_AT),
                                'favorited_at': timestamp(rows, FAVORITE, FAVORITED_AT)}
            like_count += liked
            favorite_count += favorited
    return {'like_count': like_count, 'favorite_count': favorite_count, 'members': members}


def personal_item(summary, account):
    if not summary:
        return CaseEngagement()
    return CaseEngagement(like_count=summary['like_count'], favorite_count=summary['favorite_count'],
                          **summary['members'].get(account, {}))


class CaseEngagementService:
    def __init__(self, store, writer, settings):
        self.store, self.writer, self.settings = store, writer, settings

    def identity(self, user):
        settings = self.settings
        if user.identity_source != 'feishu' or not user.user_id or not user.tenant_id:
            raise AppError(ErrorCode.FORBIDDEN)
        base = settings.feishu_bitable_app_token.get_secret_value()
        if not all((settings.cases_engagement_table_id, settings.cases_table_id, base,
                    settings.feishu_app_id, settings.feishu_app_secret.get_secret_value())):
            raise AppError(ErrorCode.SERVICE_UNAVAILABLE)
        scope = digest('case-engagement/v1', settings.feishu_app_id, base, settings.cases_table_id)
        return scope, digest(scope, user.tenant_id, user.user_id)

    @staticmethod
    async def visible_cases(cases):
        directory = await cases.read()
        if directory.stale:
            raise AppError(ErrorCode.SNAPSHOT_NOT_READY)
        return {item.id for item in directory.items}

    async def records(self, scope, case_id=None):
        record_filter = None
        if case_id is not None:
            record_filter = {'conjunction': 'and', 'conditions': [
                {'field_name': CASE, 'operator': 'is', 'value': [case_id]}]}
        try:
            async with asyncio.timeout(45):
                rows = await self.writer.all_records(record_filter=record_filter)
            result = {}
            for row in rows:
                fields = row['fields']
                case, account = text_value(fields.get(CASE)), text_value(fields.get(ACCOUNT))
                if not case or (case_id is not None and case_id != case):
                    continue
                if not account or text_value(fields.get(KEY)) != digest(scope, case, account):
                    continue
                if not row.get('record_id') or any(
                    fields.get(flag) is not None and type(fields[flag]) is not bool for flag in (LIKE, FAVORITE)
                ):
                    raise ValueError('Invalid case engagement record')
                result.setdefault(case, {}).setdefault(account, []).append(row)
            return result
        except TimeoutError:
            raise AppError(ErrorCode.UPSTREAM_TIMEOUT) from None
        except (KeyError, ValueError, TypeError, AttributeError):
            raise AppError(ErrorCode.UPSTREAM_ERROR) from None

    def version_key(self, scope):
        return 'case-engagement:summary:' + digest(scope, self.settings.cases_engagement_table_id)

    async def shared_summary(self, scope):
        version_key = self.version_key(scope)
        owner = secrets.token_hex(16)
        try:
            async with asyncio.timeout(55):
                while True:
                    version = await self.store.get(version_key)
                    if version is None:
                        version = secrets.token_hex(16)
                        if not await self.store.acquire(version_key, version, 86400):
                            continue
                    key = version_key + ':' + version
                    raw = await self.store.get(key)
                    if raw is not None:
                        return json.loads(raw)
                    if not await self.store.acquire(key + ':lock', owner, 60):
                        await asyncio.sleep(.1)
                        continue
                    try:
                        # Another reader may already have filled this version.
                        raw = await self.store.get(key)
                        if raw is not None:
                            return json.loads(raw)
                        rows = await self.records(scope)
                        result = {case: aggregate(accounts) for case, accounts in rows.items()}
                        if await self.store.get(version_key) == version:
                            # The version is part of the key. A racing write cannot
                            # let an older reader replace the new version's aggregate.
                            await self.store.set(key, json.dumps(result, separators=(',', ':')), ttl=SUMMARY_TTL_SECONDS)
                            return result
                    finally:
                        await self.store.release(key + ':lock', owner)
        except TimeoutError:
            raise AppError(ErrorCode.SERVICE_UNAVAILABLE) from None

    async def directory(self, cases, user, personal=None):
        scope, account = self.identity(user)
        switches = self.settings.case_personal_lists
        if personal and switches[0 if personal == 'like' else 1] == '0':
            raise AppError(ErrorCode.NOT_FOUND)
        visible = await self.visible_cases(cases)
        summary = await self.shared_summary(scope) if visible else {}
        items = {case: personal_item(summary.get(case), account) for case in visible}
        if personal:
            flag, date = ('liked', 'liked_at') if personal == 'like' else ('favorited', 'favorited_at')
            selected = [(case, item) for case, item in items.items() if getattr(item, flag)]
            items = dict(sorted(selected, key=lambda entry: (-(getattr(entry[1], date) or 0), entry[0])))
        return EngagementDirectory(personal_lists=switches, items=items)

    async def set_active(self, cases, user, case, action, active):
        scope, account = self.identity(user)
        if case not in await self.visible_cases(cases):
            raise AppError(ErrorCode.NOT_FOUND)
        # Serialize changes to a case so different workers can also return consistent totals.
        lock = 'case-engagement:lock:' + digest(scope, self.settings.cases_engagement_table_id, case)
        owner = secrets.token_hex(16)
        try:
            async with asyncio.timeout(8):
                while not await self.store.acquire(lock, owner, 180):
                    await asyncio.sleep(.05)
        except TimeoutError:
            raise AppError(ErrorCode.CONFLICT, headers={'Retry-After': '1'}) from None
        try:
            # Bound the entire operation below the lease lifetime, including reconciliation.
            async with asyncio.timeout(160):
                if case not in await self.visible_cases(cases):
                    raise AppError(ErrorCode.NOT_FOUND)
                return await self.apply(scope, account, case, action, active)
        except TimeoutError:
            raise AppError(ErrorCode.UPSTREAM_TIMEOUT) from None
        finally:
            await self.store.release(lock, owner)

    async def apply(self, scope, account, case, action, active):
        flag, date = (LIKE, LIKED_AT) if action == 'like' else (FAVORITE, FAVORITED_AT)
        accounts = (await self.records(scope, case)).get(case, {})
        own = accounts.get(account, [])
        if all(bool(row['fields'].get(flag)) == active for row in own) and (own or not active):
            return personal_item(aggregate(accounts), account)

        when = (timestamp(own, flag, date) or time.time_ns() // 1_000_000) if active else None
        change = {flag: active, date: when}
        try:
            async with asyncio.timeout(50):
                if own:
                    # Historical duplicates represent one account. Update every copy of
                    # the action, preserving the other action and its timestamp.
                    updates = [{'record_id': row['record_id'], 'fields': change} for row in own]
                    await self.writer.write(updates, update=True)
                    for row in own:
                        row['fields'].update(change)
                else:
                    key = digest(scope, case, account)
                    fields = {KEY: key, CASE: case, ACCOUNT: account, **change}
                    token = str(UUID(hex=key[:32], version=4))
                    row = await self.writer.create_once(fields, token)
                    if (not row.get('record_id') or row['fields'].get(flag) is not active
                            or text_value(row['fields'].get(KEY)) != key):
                        raise ValueError('Incomplete creation acknowledgement')
                    accounts[account] = [row]
        except (AppError, httpx.HTTPError, TimeoutError, ValueError, KeyError, TypeError, AttributeError) as exc:
            # A lost response may hide a successful commit. Never issue a second
            # write here; retrying clients use the same create idempotency token.
            latest = (await self.records(scope, case)).get(case, {})
            matched = latest.get(account, [])
            if matched and all(bool(row['fields'].get(flag)) == active for row in matched):
                return personal_item(aggregate(latest), account)
            if isinstance(exc, (AppError, httpx.HTTPError)):
                raise
            if isinstance(exc, TimeoutError):
                raise AppError(ErrorCode.UPSTREAM_TIMEOUT) from None
            raise AppError(ErrorCode.UPSTREAM_ERROR) from None
        finally:
            # Also rotate after ambiguous acknowledgements or cancellation: the
            # server may already have committed the change.
            await self.store.set(self.version_key(scope), secrets.token_hex(16), ttl=86400)
        return personal_item(aggregate(accounts), account)
