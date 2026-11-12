import copy
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from fakeredis.aioredis import FakeRedis

from app.core.errors import AppError
from app.repositories.store import RedisStore
from app.services.news import NewsService
from app.services.news_sync import NewsSync, source_fields, UpstreamWait


def item(ident='one', **overrides):
    return dict(id=ident, title='测试资讯', originalTitle=None, summary='摘要',
                source={'name': '发布方'}, links={'original': 'https://example.com/news', 'aihot': 'https://aihot.news/news/one'},
                publishedAt=None, discoveredAt='2026-10-26T00:00:00Z', category='ai-models', score=None,
                selected=True, attribution={'name': 'AIHOT', 'url': 'https://aihot.news'}, **overrides)


class Table:
    def __init__(self):
        self.rows = []
        self.writes = []
        self.fail = False

    async def records(self):
        return copy.deepcopy(self.rows)

    async def write(self, rows, *, update=False):
        if self.fail:
            raise httpx.ReadTimeout('ambiguous write')
        self.writes.append(copy.deepcopy(rows))
        result = []
        for row in rows:
            if update:
                saved = next(x for x in self.rows if x['record_id'] == row['record_id'])
                saved['fields'].update(copy.deepcopy(row['fields']))
            else:
                saved = {'record_id': f'rec{len(self.rows)}', 'fields': copy.deepcopy(row['fields'])}
                self.rows.append(saved)
            result.append(copy.deepcopy(saved))
        return result


@pytest.fixture
def rig(settings, store, tmp_path):
    settings.news_table_id = 'news'
    settings.news_view_id = 'view'
    settings.news_sync_state_root = tmp_path / 'state'
    settings.media_root = tmp_path / 'media'
    table = Table()
    news = NewsService(store, table, settings)
    sync = NewsSync(None, table, news, settings)
    return sync, table, news


def envelope(**data):
    return {'schemaVersion': 1, 'fields': 'default', **data}


async def test_snapshot_incremental_restart_and_manual_fields(rig):
    sync, table, news = rig
    calls = []
    def initial(request):
        calls.append(request)
        if request.url.path.endswith('snapshot'):
            if request.url.params.get('page'):
                assert request.url.params['page'] == 'second'
                return httpx.Response(200, json=envelope(cursor='watermark', items=[item('two')], hasMore=False))
            return httpx.Response(200, json=envelope(cursor='watermark', items=[item()], hasMore=True, nextPage='second'))
        assert request.url.params['cursor'] == 'watermark'
        return httpx.Response(200, json=envelope(cursor='next', changes=[], hasMore=False))
    async with httpx.AsyncClient(transport=httpx.MockTransport(initial)) as client:
        sync.client = client
        result = await sync.sync(force=True)
    assert result['created'] == 2 and result['visible'] == 2
    assert sync.load_state()['cursor'] == 'next'
    table.rows[0]['fields'].update({'人工标题': '人工文案', '首页推荐': True, '封面': [{'file_token': 'photo'}]})
    changed = item(); changed['title'] = '更新的标题'
    def delta(request):
        assert request.url.path.endswith('changes')
        assert request.url.params['cursor'] == 'next'
        return httpx.Response(200, json=envelope(cursor='last', changes=[{'op': 'upsert', 'item': changed}, {'op': 'remove', 'id': 'two'}], hasMore=False))
    # A restarted worker resumes the checkpoint, never repeats bootstrap.
    restarted = NewsSync(None, table, news, sync.settings)
    async with httpx.AsyncClient(transport=httpx.MockTransport(delta)) as client:
        restarted.client = client
        result = await restarted.sync(force=True)
    assert result['created'] == 0 and result['updated'] == 2 and result['visible'] == 1
    visible = (await news.read()).items[0]
    assert visible.title == '人工文案' and visible.featured and '/news/media/' in visible.image
    assert table.rows[0]['fields']['标题'] == '更新的标题'
    assert table.rows[1]['fields']['同步状态'] == '已撤选'
    assert await restarted.sync() == {'status': 'not_due'}


async def test_failed_write_preserves_cursor_and_cache_then_retry(rig):
    sync, table, news = rig
    table.rows = [{'record_id': 'r', 'fields': source_fields(item())}]
    await news.read()
    sync.save_state({'cursor': 'before'})
    changed = item(); changed['title'] = '更新'
    def response(request):
        return httpx.Response(200, json=envelope(cursor='after', hasMore=False, changes=[{'op': 'upsert', 'item': changed}]))
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        sync.client = client
        table.fail = True
        with pytest.raises(httpx.ReadTimeout):
            await sync.sync(force=True)
        assert sync.load_state()['cursor'] == 'before'
        await news.store.delete(news.key + ':fresh')
        assert (await news.read()).stale
        assert (await news.read()).items[0].title == '测试资讯'
        assert await sync.store.get(sync.key + ':lock') is None
        assert await sync.store.get(news.key + ':lock') is None
        table.fail = False
        assert (await sync.sync(force=True))['updated'] == 1
        assert (await sync.sync(force=True))['updated'] == 0  # replay is idempotent
    assert len(table.rows) == 1


async def test_409_resnapshot_reconciles_removals_and_304_refreshes_editor_changes(rig):
    sync, table, news = rig
    table.rows = [{'record_id': 'old', 'fields': source_fields(item('old'))}]
    sync.save_state({'cursor': 'expired'})
    def response(request):
        if request.url.path.endswith('snapshot'):
            return httpx.Response(200, json=envelope(cursor='fresh', items=[item()], hasMore=False))
        if request.url.params['cursor'] == 'expired':
            return httpx.Response(409)
        return httpx.Response(304)
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        sync.client = client
        result = await sync.sync(force=True)
        assert result['created'] == 1 and result['updated'] == 1 and result['visible'] == 1
        table.rows[1]['fields']['隐藏'] = True
        assert (await sync.sync(force=True))['visible'] == 0
    assert sync.load_state()['cursor'] == 'fresh'


async def test_public_cache_ttls_same_key_and_sync_lease(rig):
    sync, table, news = rig
    redis = FakeRedis(decode_responses=True)
    news.store = sync.store = RedisStore(redis, 'test')
    table.rows = [{'record_id': 'r', 'fields': source_fields(item())}]
    await news.read()
    assert 595 < await redis.ttl('test:' + news.key + ':fresh') <= 600
    assert 86395 < await redis.ttl('test:' + news.key + ':snapshot') <= 86400
    other = NewsService(news.store, table, sync.settings)
    assert other.key == news.key
    await news.store.acquire(sync.key + ':lock', 'another-worker', 900)
    assert (await other.read()).stale
    assert await sync.sync(force=True) == {'status': 'busy'}
    await news.store.release(sync.key + ':lock', 'another-worker')
    # A cache fill in progress prevents the writer from modifying Feishu underneath it.
    await news.store.acquire(news.key + ':lock', 'reader', 60)
    assert await sync.sync(force=True) == {'status': 'busy'}
    assert await news.store.get(sync.key + ':lock') is None
    await news.store.close()


async def test_upstream_backoff_leaves_existing_cache(rig):
    sync, table, news = rig
    sync.save_state({'cursor': 'same'})
    table.rows = [{'record_id': 'r', 'fields': source_fields(item())}]
    await news.read()
    calls = []
    def limited(request):
        calls.append(request)
        return httpx.Response(429, headers={'Retry-After': '1200'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(limited)) as client:
        sync.client = client
        with pytest.raises(UpstreamWait) as exc:
            await sync.sync(force=True)
    assert exc.value.seconds == 1200 and len(calls) == 1
    assert sync.load_state()['cursor'] == 'same'
    assert (await news.read()).items[0].title == '测试资讯'
    assert await sync.sync() == {'status': 'not_due'}


def test_mapping_nullable_dates_and_excludes_editor_fields():
    fields = source_fields(item())
    assert fields['原文发布时间'] is None and fields['来源评分'] is None
    assert fields['分类'] == 'AI 模型'
    assert not {'封面', '隐藏', '首页推荐', '人工标题', '人工摘要', '排序权重'} & fields.keys()


def test_news_routes_require_identity(client):
    for path in ['/api/v1/news', '/api/v1/news/media/' + 'a' * 64]:
        assert client.get(path).status_code == 401


def test_news_route_envelope(client, app, token):
    app.state.news.read = AsyncMock()
    from app.schemas.news import NewsDirectory
    from datetime import datetime, UTC
    app.state.news.read.return_value = NewsDirectory(items=[], updated_at=datetime.now(UTC))
    result = client.get('/api/v1/news', headers={'Authorization': 'Bearer ' + token})
    assert result.status_code == 200 and result.json()['data']['items'] == []

async def test_pending_write_race_is_rechecked_inside_cache_lease(rig, monkeypatch):
    sync, table, news = rig
    table.rows = [{'record_id': 'r', 'fields': source_fields(item())}]
    await news.read()
    await news.store.delete(news.key + ':fresh')
    acquire = news.store.acquire
    async def interleaved(key, owner, ttl):
        # A failed writer leaves pending after the request's initial precheck.
        await news.store.set(sync.key + ':pending', '1')
        return await acquire(key, owner, ttl)
    monkeypatch.setattr(news.store, 'acquire', interleaved)
    table.rows[0]['fields']['标题'] = '尚未完成的写入'
    result = await news.read()
    assert result.stale and result.items[0].title == '测试资讯'


async def test_unchanged_feed_reads_feishu_once_and_refreshes_manual_edits(rig):
    sync, table, news = rig
    table.rows = [{'record_id': 'r', 'fields': source_fields(item())}]
    await news.read()
    table.rows[0]['fields']['人工标题'] = '运营修改'
    sync.save_state({'cursor': 'saved'})
    table.records = AsyncMock(wraps=table.records)
    sync.fetch = AsyncMock(return_value=(None, None))
    result = await sync.sync(force=True)
    assert result['created'] == result['updated'] == 0
    assert table.records.await_count == 1
    assert (await news.read()).items[0].title == '运营修改'


async def test_sync_run_sleeps_until_due_and_can_be_cancelled(rig, monkeypatch):
    import asyncio
    sync, _, _ = rig
    monkeypatch.setattr('app.services.news_sync.time.time', lambda: 1000)
    await sync.store.set(sync.key + ':next', '1600')
    sync.sync = AsyncMock(return_value={'status': 'not_due'})
    sleep = AsyncMock(side_effect=asyncio.CancelledError)
    monkeypatch.setattr('app.services.news_sync.asyncio.sleep', sleep)
    with pytest.raises(asyncio.CancelledError):
        await sync.run()
    sync.sync.assert_awaited_once()
    sleep.assert_awaited_once_with(600)


@pytest.mark.parametrize('outcome,delay', [('busy', 30), ('backoff', 1200), ('failure', 600)])
async def test_sync_run_backoff_and_lock_contention(rig, monkeypatch, outcome, delay):
    import asyncio
    sync, _, _ = rig
    sync.sync = AsyncMock(return_value={'status': 'busy'})
    if outcome != 'busy':
        sync.sync.side_effect = UpstreamWait(1200) if outcome == 'backoff' else ConnectionError()
    sleep = AsyncMock(side_effect=asyncio.CancelledError)
    monkeypatch.setattr('app.services.news_sync.asyncio.sleep', sleep)
    with pytest.raises(asyncio.CancelledError):
        await sync.run()
    sleep.assert_awaited_once_with(delay)


def test_sync_defaults_on_and_environment_switch(monkeypatch):
    from app.core.config import Settings
    monkeypatch.delenv('OWS_COMMUNITY_NEWS_SYNC_ENABLED', raising=False)
    settings = Settings(_env_file=None, store_backend='redis', news_table_id='table', news_view_id='view')
    assert settings.news_sync_enabled is True
    assert settings.news_sync_interval_seconds == 600
    monkeypatch.setenv('OWS_COMMUNITY_NEWS_SYNC_ENABLED', 'false')
    assert Settings(_env_file=None).news_sync_enabled is False


@pytest.mark.parametrize('enabled', [True, False])
def test_sync_lifecycle_starts_only_when_enabled_and_cancels(settings, store, monkeypatch, enabled):
    import asyncio
    from fastapi.testclient import TestClient
    from app.main import create_app
    started, cancelled = [], []

    async def run(self):
        started.append(True)
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    monkeypatch.setattr(NewsSync, 'run', run)
    settings.news_sync_enabled = enabled
    with TestClient(create_app(settings, store)) as client:
        client.get('/health')
        assert bool(started) is enabled
    assert bool(cancelled) is enabled
