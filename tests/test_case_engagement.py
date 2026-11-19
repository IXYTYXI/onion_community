import asyncio
from copy import deepcopy
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.repositories.case_interactions import CaseInteractionDB
from app.repositories.store import MemoryStore
from app.schemas.auth import Principal
from app.schemas.cases import Case, CaseDirectory
from app.services.case_engagement import (
    ACCOUNT, CASE, FAVORITE as FAVORITE_FIELD, FAVORITED_AT, KEY, LIKE as LIKE_FIELD, LIKED_AT,
    CaseEngagementService, digest,
)
from app.services.cases import CaseService
from app.services.browser_auth import SESSION_COOKIE, csrf_token

URL = '/api/v1/cases/engagement'
LIKE = '/api/v1/cases/a/engagement/like'
FAVORITE = '/api/v1/cases/a/engagement/favorite'


class FakeTable:
    def __init__(self):
        self.rows = []
        self.timeout_after_create = False
        self.failure = False
        self.creates = 0
        self.scans = 0
        self.lookups = []
        self.writes = []

    async def all_records(self, *, record_filter=None):
        if record_filter is None:
            self.scans += 1
        else:
            self.lookups.append(deepcopy(record_filter))
        if self.failure:
            raise httpx.ConnectError('offline')
        if record_filter is None:
            return deepcopy(self.rows)
        [condition] = record_filter['conditions']
        assert condition['operator'] == 'is'
        [value] = condition['value']
        return deepcopy([row for row in self.rows if row['fields'].get(condition['field_name']) == value])

    async def create_once(self, fields, client_token):
        if self.failure:
            raise httpx.ConnectError('offline')
        self.creates += 1
        row = {'record_id': f'rec{self.creates}', 'fields': deepcopy(fields)}
        self.rows.append(row)
        if self.timeout_after_create:
            raise httpx.ReadTimeout('response lost')
        return row

    async def write(self, records, *, update=False):
        assert update
        if self.failure:
            raise httpx.ConnectError('offline')
        self.writes.extend(deepcopy(records))
        for change in records:
            row = next(r for r in self.rows if r['record_id'] == change['record_id'])
            row['fields'].update(change['fields'])
        return deepcopy(records)


@pytest.fixture
def configured(settings):
    settings.feishu_app_id = 'app'
    settings.feishu_app_secret = SecretStr('test')
    settings.feishu_bitable_app_token = SecretStr('base')
    settings.cases_table_id = 'source'
    settings.cases_view_id = 'view'
    settings.cases_source_tenant = 'tenant'
    settings.cases_engagement_table_id = 'interactions'
    return settings


@pytest.fixture
def table(configured, client, app, store):
    source = AsyncMock()
    source.records.return_value = [
        {'record_id': case, 'fields': {'作品名': case, '敏感风控': visibility}}
        for case, visibility in [('a', '公开'), ('b', '需申请权限'), ('secret', '暂不公开')]
    ]
    app.state.cases = CaseService(store, source, configured)
    table = FakeTable()
    app.state.case_engagement.writer = table
    return table


@pytest.fixture
def login(client, app):
    def issue(account='ou_one', tenant='tenant'):
        principal = Principal(user_id=account, tenant_id=tenant, identity_source='feishu', display_name='同名成员')
        result = client.portal.call(app.state.auth.issue, principal)
        return {'Authorization': f'Bearer {result.access_token}'}
    return issue


def test_list_configuration(settings, monkeypatch):
    args = dict(_env_file=None, news_sync_enabled=False)
    for value in ('00', '01', '10', '11'):
        monkeypatch.setenv('OWS_COMMUNITY_CASE_PERSONAL_LISTS', value)
        assert Settings(**args).case_personal_lists == value
    monkeypatch.setenv('OWS_COMMUNITY_CASE_PERSONAL_LISTS', '1')
    with pytest.raises(ValidationError):
        Settings(**args)


def test_auth_visibility_retry_and_account_isolation(client, app, login, table, token):
    client.cookies.clear()
    assert client.get(URL).status_code == 401
    dev = {'Authorization': f'Bearer {token}'}
    assert client.get(URL, headers=dev).status_code == 403
    assert client.put(LIKE, headers=dev, json={'active': True}).status_code == 403
    one, two = login(), login('ou_two')
    outsider = login(tenant='different')
    assert client.get(URL, headers=outsider).status_code == 403
    assert client.put(LIKE, headers=outsider, json={'active': True}).status_code == 403
    assert table.scans == 0
    listing = client.get(URL, headers=one).json()['data']
    assert listing['personal_lists'] == '01' and set(listing['items']) == {'a', 'b'}
    assert listing['items']['a'] == dict(liked=False, favorited=False, like_count=0,
                                       favorite_count=0, liked_at=None, favorited_at=None)
    assert client.put(LIKE.replace('/a/', '/secret/'), json={'active': True}, headers=one).status_code == 404
    assert client.put(LIKE, json={'active': 'false'}, headers=one).status_code == 422
    assert client.put(LIKE, json={'active': True, 'user_id': 'ou_two'}, headers=one).status_code == 422
    cookie = one['Authorization'].split()[1]
    client.cookies.set(SESSION_COOKIE, cookie)
    origin = {'Origin': app.state.settings.site_origin}
    assert client.put(LIKE, json={'active': True}, headers=origin).status_code == 403
    table.failure = True
    item = client.put(LIKE, json={'active': True}, headers={**origin, 'X-CSRF-Token': csrf_token(cookie)}).json()['data']
    assert item['like_count'] == 1 and item['liked'] and item['liked_at'] > 10**12
    assert client.put(LIKE, json={'active': True}, headers=one).json()['data'] == item
    assert table.creates == 0 and not table.lookups and not table.writes
    favorite = client.put(FAVORITE, json={'active': True}, headers=one).json()['data']
    assert favorite['liked_at'] == item['liked_at'] and favorite['favorite_count'] == 1
    assert client.get(URL + '?personal=like', headers=one).status_code == 404
    assert list(client.get(URL + '?personal=favorite', headers=one).json()['data']['items']) == ['a']
    other = client.get(URL, headers=two).json()['data']['items']['a']
    assert other == {**item, 'liked': False, 'liked_at': None, 'favorite_count': 1}
    assert client.get(URL + '?personal=favorite', headers=two).json()['data']['items'] == {}
    assert client.put(LIKE, json={'active': True}, headers=two).json()['data']['like_count'] == 2
    off = client.put(LIKE, json={'active': False}, headers=one).json()['data']
    assert not off['liked'] and off['liked_at'] is None and off['like_count'] == 1
    assert off['favorited'] and off['favorite_count'] == 1
    assert client.get(URL, headers=one).json()['data']['items']['a'] == off


def test_source_failure_blocks_private_reads_and_writes(client, app, login, table, store):
    headers = login()
    assert client.get(URL, headers=headers).status_code == 200
    table.failure = True
    assert client.get(URL, headers=headers).status_code == 200
    assert client.put(LIKE, headers=headers, json={'active': True}).json()['data']['liked']
    cases = app.state.cases
    client.portal.call(store.delete, cases.key + ':fresh')
    cases.source.records.side_effect = httpx.ConnectError('offline')
    assert client.get('/api/v1/cases', headers=headers).json()['data']['stale']
    assert client.get(URL, headers=headers).status_code == 503
    assert client.put(LIKE, json={'active': False}, headers=headers).status_code == 503
    cases.source.records.side_effect = None
    client.portal.call(store.delete, cases.key + ':cooldown')
    assert client.get(URL, headers=headers).json()['data']['items']['a']['liked']
    assert table.rows == []


def test_missing_table_still_allows_directory(client, app, login, table, configured):
    configured.cases_engagement_table_id = ''
    headers = login()
    assert client.get('/api/v1/cases', headers=headers).status_code == 200
    assert client.get(URL, headers=headers).status_code == 503


def test_personal_sort_switches_and_removal(client, configured, table, login):
    headers = login()
    configured.case_personal_lists = '11'
    # Import two dated historical likes on the first request.
    first, second = 1700000000000, 1700000001000
    table.rows.extend([historical(configured, 'first', 'a', liked_at=first),
                       historical(configured, 'second', 'b', liked_at=second)])
    assert list(client.get(URL + '?personal=like', headers=headers).json()['data']['items']) == ['b', 'a']
    client.put(LIKE, json={'active': False}, headers=headers).raise_for_status()
    assert list(client.get(URL + '?personal=like', headers=headers).json()['data']['items']) == ['b']
    configured.case_personal_lists = '10'
    assert client.get(URL + '?personal=favorite', headers=headers).status_code == 404
    configured.case_personal_lists = '00'
    assert client.get(URL + '?personal=like', headers=headers).status_code == 404
    assert client.put(FAVORITE, json={'active': True}, headers=headers).json()['data']['favorited']


@pytest.mark.parametrize('override', [None, 'separate-ledger-base'])
async def test_bitable_transport_preserves_search_projection_and_create_token(configured, store, override):
    import json
    from uuid import uuid4
    from app.integrations.bitable_writer import BitableWriter
    from app.services.case_engagement import ENGAGEMENT_FIELDS

    token = str(uuid4())
    fields = {'案例ID': 'a', '是否点赞': True, '点赞时间': 1700000000000}
    record_filter = {'conjunction': 'and', 'conditions': [{'field_name': KEY, 'operator': 'is', 'value': ['key']}]}
    searches = []

    def reply(request):
        if request.url.host == 'accounts.feishu.cn':
            assert b'bitable%3Aapp' in request.content
            return httpx.Response(200, json={'access_token': 'demo', 'expires_in': 7200})
        assert request.headers['Authorization'] == 'Bearer demo'
        assert f'/apps/{override or "base"}/tables/interactions/records' in request.url.path
        body = json.loads(request.content)
        if request.url.path.endswith('/search'):
            searches.append(body)
            return httpx.Response(200, json={'code': 0, 'data': {'items': [], 'has_more': False}})
        assert request.url.params['client_token'] == token and body == {'fields': fields}
        return httpx.Response(200, json={'code': 0, 'data': {'record': {'record_id': 'r', 'fields': fields}}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        writer = BitableWriter(client, configured, store, table_id='interactions', fields=ENGAGEMENT_FIELDS,
                               base_token=SecretStr(override) if override else None)
        assert await writer.all_records() == []
        assert await writer.all_records(record_filter=record_filter) == []
        assert searches == [{'field_names': ENGAGEMENT_FIELDS},
                            {'field_names': ENGAGEMENT_FIELDS, 'filter': record_filter}]
        assert (await writer.create_once(fields, token))['fields'] == fields


def test_known_case_table_uses_its_provisioned_engagement_table(monkeypatch):
    args = dict(_env_file=None, news_sync_enabled=False)
    monkeypatch.setenv('OWS_COMMUNITY_CASES_TABLE_ID', 'tbldtSGzcfa6twD0')
    monkeypatch.setenv('OWS_COMMUNITY_CASES_ENGAGEMENT_TABLE_ID', '')
    assert Settings(**args).cases_engagement_table_id == 'tblUTQgRmYHxdiuh'
    monkeypatch.setenv('OWS_COMMUNITY_CASES_ENGAGEMENT_TABLE_ID', 'tblCustom')
    assert Settings(**args).cases_engagement_table_id == 'tblCustom'
    monkeypatch.setenv('OWS_COMMUNITY_CASES_TABLE_ID', 'tblOther')
    assert Settings(**args).cases_engagement_table_id == 'tblCustom'
    monkeypatch.delenv('OWS_COMMUNITY_CASES_ENGAGEMENT_TABLE_ID')
    assert Settings(**args).cases_engagement_table_id == ''


def historical(settings, record_id, case, *, liked_at=None, favorited_at=None, account='ou_one'):
    scope = digest('case-engagement/v1', settings.feishu_app_id,
                   settings.feishu_bitable_app_token.get_secret_value(), settings.cases_table_id)
    owner = digest(scope, 'tenant', account)
    return {'record_id': record_id, 'fields': {
        KEY: digest(scope, case, owner), CASE: case, ACCOUNT: owner, LIKE_FIELD: liked_at is not None,
        LIKED_AT: liked_at, FAVORITE_FIELD: favorited_at is not None, FAVORITED_AT: favorited_at,
    }}


def worker(configured, table):
    return CaseEngagementService(MemoryStore(), table, configured, CaseInteractionDB(configured.case_interactions_db))


@pytest.fixture
def cases():
    cases = AsyncMock()
    cases.read.return_value = CaseDirectory(items=[Case(id='a', title='A', access='公开')], updated_at=datetime.now(UTC))
    return cases


@pytest.fixture
def member():
    return Principal(user_id='ou_one', tenant_id='tenant', display_name='A', identity_source='feishu')


def test_first_put_merges_historical_copies_and_mirror_updates_only_matching_key(client, app, configured, login, table):
    old = 1700000000000
    liked = historical(configured, 'liked', 'a', liked_at=old)
    favorite = historical(configured, 'favorite', 'a', liked_at=old + 1, favorited_at=old + 2)
    other = historical(configured, 'other', 'a', liked_at=old, account='ou_two')
    forged = historical(configured, 'forged', 'a', liked_at=old, account='ou_three')
    forged['fields'][KEY] = 'unrelated-key'
    table.rows.extend([liked, favorite, other, forged])
    headers = login()
    same = client.put(LIKE, headers=headers, json={'active': True}).json()['data']
    assert same == dict(liked=True, favorited=True, like_count=2, favorite_count=1,
                        liked_at=old + 1, favorited_at=old + 2)
    off = client.put(LIKE, headers=headers, json={'active': False}).json()['data']
    assert off == {**same, 'liked': False, 'like_count': 1, 'liked_at': None}
    assert table.scans == 1 and not table.lookups and not table.writes and table.creates == 0
    assert client.portal.call(app.state.case_engagement.sync_once) == 1
    assert table.lookups == [{'conjunction': 'and', 'conditions': [
        {'field_name': KEY, 'operator': 'is', 'value': [liked['fields'][KEY]]}]}]
    assert {write['record_id'] for write in table.writes} == {'liked', 'favorite'}
    for row in [liked, favorite]:
        assert row['fields'][LIKE_FIELD] is False and row['fields'][LIKED_AT] is None
        assert row['fields'][FAVORITE_FIELD] is True and row['fields'][FAVORITED_AT] == old + 2
    assert other['fields'][LIKE_FIELD] and forged['fields'][LIKE_FIELD]
    # External edits after import cannot overwrite the website's committed state.
    table.rows.clear()
    assert client.get(URL, headers=headers).json()['data']['items']['a'] == off
    assert client.portal.call(app.state.case_engagement.sync_once) == 0
    assert table.scans == 1


def test_failed_initial_import_is_retried_without_publishing_empty_state(client, configured, login, table):
    headers = login()
    table.failure = True
    assert client.get(URL, headers=headers).status_code in (502, 503)
    assert client.put(LIKE, headers=headers, json={'active': True}).status_code in (502, 503)
    table.failure = False
    table.rows.append(historical(configured, 'seed', 'a', favorited_at=1700000000000))
    item = client.get(URL, headers=headers).json()['data']['items']['a']
    assert not item['liked'] and item['favorited_at'] == 1700000000000


async def test_offline_edits_survive_restart_and_retry_ambiguous_create(configured, cases, member):
    table = FakeTable()
    first = worker(configured, table)
    await first.directory(cases, member)
    table.failure = True
    liked = await first.set_active(cases, member, 'a', 'like', True)
    assert liked.liked and liked.like_count == 1
    assert await first.set_active(cases, member, 'a', 'like', True) == liked
    assert not table.lookups and not table.creates

    restarted = worker(configured, table)
    assert (await restarted.directory(cases, member)).items['a'] == liked
    another_tenant = member.model_copy(update={'tenant_id': 'elsewhere'})
    private = (await restarted.directory(cases, another_tenant)).items['a']
    assert not private.liked and private.like_count == 1
    assert await restarted.sync_once() == 0
    table.failure, table.timeout_after_create = False, True
    assert await restarted.sync_once() == 0
    assert len(table.rows) == table.creates == 1

    table.timeout_after_create = False
    recovered = worker(configured, table)
    assert await recovered.sync_once() == 1
    assert await recovered.sync_once() == 0
    assert table.scans == table.creates == 1
    assert (await recovered.directory(cases, member)).items['a'] == liked
    assert table.rows[0]['fields'][LIKED_AT] == liked.liked_at
    assert member.user_id not in str(table.rows)


async def test_edit_during_mirror_remains_pending_for_next_revision(configured, cases, member):
    table = FakeTable()
    mirror, site = worker(configured, table), worker(configured, table)
    await site.set_active(cases, member, 'a', 'like', True)
    started, resume = asyncio.Event(), asyncio.Event()
    create = table.create_once

    async def slow_create(fields, client_token):
        started.set()
        await resume.wait()
        return await create(fields, client_token)

    table.create_once = slow_create
    delivery = asyncio.create_task(mirror.sync_once())
    try:
        await asyncio.wait_for(started.wait(), 3)
        latest = await asyncio.wait_for(site.set_active(cases, member, 'a', 'favorite', True), 3)
        assert latest.liked and latest.favorited
    finally:
        resume.set()
        acknowledged = await delivery
    assert acknowledged == 0
    assert await mirror.sync_once() == 1
    assert await mirror.sync_once() == 0
    [row] = table.rows
    assert row['fields'][LIKE_FIELD] and row['fields'][FAVORITE_FIELD]
    assert row['fields'][FAVORITED_AT] == latest.favorited_at
    assert table.scans == table.creates == 1


def test_blue_green_first_import_waits_until_rollback_window_has_closed(tmp_path):
    from app.services.case_engagement import activation_confirmed

    source = tmp_path / '.releases' / 'ci-test.stage' / 'source'
    source.mkdir(parents=True)
    (source / '.release-commit').write_text('new')
    assert activation_confirmed(tmp_path / 'standalone')
    assert not activation_confirmed(source)
    marker = tmp_path / '.release-commit'
    marker.write_text('old')
    assert not activation_confirmed(source)
    marker.write_text('new')
    assert activation_confirmed(source)


def test_import_keeps_like_when_legacy_date_is_malformed(client, configured, login, table):
    row = historical(configured, 'first', 'a', liked_at=123)
    row['fields'][LIKED_AT] = {'invalid': True}
    table.rows.append(row)
    item = client.get(URL, headers=login()).json()['data']['items']['a']
    assert item['liked'] and item['like_count'] == 1 and item['liked_at'] is None
