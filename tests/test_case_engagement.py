import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.schemas.auth import Principal
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

    async def all_records(self, *, record_filter=None):
        if record_filter is None:
            self.scans += 1
        if self.failure:
            raise httpx.ConnectError('offline')
        await asyncio.sleep(.002)
        return deepcopy(self.rows)

    async def create_once(self, fields, client_token):
        self.creates += 1
        row = {'record_id': f'rec{self.creates}', 'fields': deepcopy(fields)}
        self.rows.append(row)
        if self.timeout_after_create:
            raise httpx.ReadTimeout('response lost')
        return row

    async def write(self, records, *, update=False):
        assert update
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


def test_auth_visibility_retry_and_account_isolation(client, app, login, table):
    assert client.get(URL).status_code == 401
    one, two = login(), login('ou_two')
    assert client.get(URL, headers=login(tenant='different')).status_code == 403
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
    table.timeout_after_create = True
    item = client.put(LIKE, json={'active': True}, headers={**origin, 'X-CSRF-Token': csrf_token(cookie)}).json()['data']
    assert item['like_count'] == 1 and item['liked'] and item['liked_at'] > 10**12
    assert client.put(LIKE, json={'active': True}, headers=one).json()['data'] == item
    assert table.creates == 1 and 'ou_one' not in str(table.rows)
    favorite = client.put(FAVORITE, json={'active': True}, headers=one).json()['data']
    assert favorite['liked_at'] == item['liked_at'] and favorite['favorite_count'] == 1
    assert client.get(URL + '?personal=like', headers=one).status_code == 404
    assert list(client.get(URL + '?personal=favorite', headers=one).json()['data']['items']) == ['a']
    other = client.get(URL, headers=two).json()['data']['items']['a']
    assert other == {**item, 'liked': False, 'liked_at': None, 'favorite_count': 1}
    assert client.get(URL + '?personal=favorite', headers=two).json()['data']['items'] == {}
    table.rows.append({**deepcopy(table.rows[0]), 'record_id': 'duplicate'})
    assert client.put(LIKE, json={'active': True}, headers=two).json()['data']['like_count'] == 2
    off = client.put(LIKE, json={'active': False}, headers=one).json()['data']
    assert not off['liked'] and off['liked_at'] is None and off['like_count'] == 1
    assert off['favorited'] and off['favorite_count'] == 1
    assert client.get(URL, headers=one).json()['data']['items']['a'] == off


def test_source_failure_blocks_private_reads_and_writes(client, app, login, table, store):
    headers = login()
    assert client.get(URL, headers=headers).status_code == 200
    table.failure = True
    assert client.get(URL, headers=headers).status_code == 200  # Fresh cached aggregate.
    assert client.put(LIKE, headers=headers, json={'active': True}).status_code == 502
    cases = app.state.cases
    client.portal.call(store.delete, cases.key + ':fresh')
    cases.source.records.side_effect = httpx.ConnectError('offline')
    assert client.get('/api/v1/cases', headers=headers).json()['data']['stale']
    assert client.get(URL, headers=headers).status_code == 503
    assert client.put(LIKE, json={'active': True}, headers=headers).status_code == 503
    assert table.rows == []


def test_missing_table_still_allows_directory(client, app, login, table, configured):
    configured.cases_engagement_table_id = ''
    headers = login()
    assert client.get('/api/v1/cases', headers=headers).status_code == 200
    assert client.get(URL, headers=headers).status_code == 503


@pytest.mark.asyncio
async def test_workers_share_lease_and_state_survives_redis_loss(configured):
    from fakeredis import FakeServer
    from fakeredis.aioredis import FakeRedis
    from app.repositories.store import RedisStore
    from app.services.case_engagement import CaseEngagementService
    from app.schemas.cases import Case, CaseDirectory
    from datetime import UTC, datetime

    server, table = FakeServer(), FakeTable()
    stores = [RedisStore(FakeRedis(server=server, decode_responses=True), 'site') for _ in range(2)]
    workers = [CaseEngagementService(store, table, configured) for store in stores]
    user = Principal(user_id='ou_member', tenant_id='one', display_name='M', identity_source='feishu')
    cases = AsyncMock()
    cases.read.return_value = CaseDirectory(items=[Case(id='a', title='A', access='公开')], updated_at=datetime.now(UTC))
    try:
        await asyncio.gather(*(workers[i % 2].set_active(cases, user, 'a', action, True)
                               for i, action in enumerate(['like', 'favorite'] * 3)))
        assert len(table.rows) == 1
        await stores[0].client.flushdb()
        rebuilt = CaseEngagementService(stores[0], table, configured)
        item = (await rebuilt.directory(cases, user)).items['a']
        assert item.liked and item.favorited and item.like_count == item.favorite_count == 1
        other_tenant = user.model_copy(update={'tenant_id': 'two'})
        other = (await rebuilt.directory(cases, other_tenant)).items['a']
        assert not other.liked and not other.favorited
        assert other.like_count == other.favorite_count == 1
        await rebuilt.set_active(cases, other_tenant, 'a', 'like', True)
        assert (await rebuilt.directory(cases, user)).items['a'].like_count == 2
        assert len({r['fields']['飞书账号标识'] for r in table.rows}) == 2
    finally:
        for store in stores:
            await store.close()


def test_personal_sort_switches_and_removal(client, configured, table, login):
    headers = login()
    configured.case_personal_lists = '11'
    for case in ('a', 'b'):
        client.put(LIKE.replace('/a/', f'/{case}/'), json={'active': True}, headers=headers).raise_for_status()
    table.rows[0]['fields']['点赞时间'] = 1700000000000
    table.rows[1]['fields']['点赞时间'] = 1700000001000
    assert list(client.get(URL + '?personal=like', headers=headers).json()['data']['items']) == ['b', 'a']
    client.put(LIKE, json={'active': False}, headers=headers).raise_for_status()
    assert list(client.get(URL + '?personal=like', headers=headers).json()['data']['items']) == ['b']
    configured.case_personal_lists = '10'
    assert client.get(URL + '?personal=favorite', headers=headers).status_code == 404
    configured.case_personal_lists = '00'
    assert client.get(URL + '?personal=like', headers=headers).status_code == 404
    assert client.put(FAVORITE, json={'active': True}, headers=headers).json()['data']['favorited']


async def test_bitable_transport_preserves_search_projection_and_create_token(configured, store):
    import json
    from uuid import uuid4
    from app.integrations.bitable_writer import BitableWriter
    from app.services.case_engagement import ENGAGEMENT_FIELDS

    token = str(uuid4())
    fields = {'案例ID': 'a', '是否点赞': True, '点赞时间': 1700000000000}
    record_filter = {'conjunction': 'and', 'conditions': [{'field_name': '案例ID', 'operator': 'is', 'value': ['a']}]}

    def reply(request):
        if request.url.host == 'accounts.feishu.cn':
            assert b'bitable%3Aapp' in request.content
            return httpx.Response(200, json={'access_token': 'demo', 'expires_in': 7200})
        assert request.headers['Authorization'] == 'Bearer demo'
        assert '/apps/base/tables/interactions/records' in request.url.path
        body = json.loads(request.content)
        if request.url.path.endswith('/search'):
            assert body == {'field_names': ENGAGEMENT_FIELDS, 'filter': record_filter}
            return httpx.Response(200, json={'code': 0, 'data': {'items': [], 'has_more': False}})
        assert request.url.params['client_token'] == token and body == {'fields': fields}
        return httpx.Response(200, json={'code': 0, 'data': {'record': {'record_id': 'r', 'fields': fields}}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        writer = BitableWriter(client, configured, store, table_id='interactions', fields=ENGAGEMENT_FIELDS)
        assert await writer.all_records(record_filter=record_filter) == []
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


async def test_reader_cannot_refill_old_summary_after_write(configured, store):
    from datetime import UTC, datetime
    from app.schemas.cases import Case, CaseDirectory
    from app.services.case_engagement import CaseEngagementService

    table = FakeTable()
    workers = [CaseEngagementService(store, table, configured) for _ in range(2)]
    user = Principal(user_id='one', tenant_id='tenant', display_name='A', identity_source='feishu')
    other = user.model_copy(update={'user_id': 'two'})
    cases = AsyncMock()
    cases.read.return_value = CaseDirectory(items=[Case(id='a', title='A', access='公开')], updated_at=datetime.now(UTC))
    began, resume = asyncio.Event(), asyncio.Event()
    normal_search = table.all_records

    async def slow_first_scan(*, record_filter=None):
        rows = await normal_search(record_filter=record_filter)
        if record_filter is None and not began.is_set():
            began.set()
            await resume.wait()
        return rows

    table.all_records = slow_first_scan
    old = asyncio.create_task(workers[0].directory(cases, user))
    await asyncio.wait_for(began.wait(), timeout=1)
    # The remote service commits, but the original write response is lost.
    table.timeout_after_create = True
    await workers[1].set_active(cases, user, 'a', 'like', True)
    resume.set()
    await old
    results = await asyncio.gather(*(worker.directory(cases, other) for worker in workers))
    assert all(not result.items['a'].liked and result.items['a'].like_count == 1 for result in results)
    assert (await workers[0].directory(cases, user)).items['a'].liked
    assert table.scans == 2


def test_unconfirmed_write_discards_warm_summary(client, login, table):
    headers = login()
    before = client.get(URL, headers=headers).json()['data']['items']['a']
    assert before['like_count'] == 0
    normal_create = table.create_once

    async def lost_with_failed_reconciliation(fields, token):
        await normal_create(fields, token)
        table.failure = True
        raise httpx.ReadTimeout('lost acknowledgement')

    table.create_once = lost_with_failed_reconciliation
    assert client.put(LIKE, json={'active': True}, headers=headers).status_code == 502
    table.failure = False
    after = client.get(URL, headers=headers).json()['data']['items']['a']
    assert after['liked'] and after['like_count'] == 1 and table.scans == 2
