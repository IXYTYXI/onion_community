from unittest.mock import AsyncMock
import httpx
import pytest
from fakeredis.aioredis import FakeRedis
from app.repositories.store import RedisStore
from app.services.faq import FAQService

@pytest.fixture
def service(settings, store):
    settings.faq_table_id = 'faq'
    settings.faq_view_id = 'view'
    source = AsyncMock()
    source.records.return_value = [
        {'record_id':'empty','fields':{}},
        {'record_id':'draft','fields':{'问题':'待回复'}},
        {'record_id':'first','fields':{'问题':'问题一','回复':'答复\n第二行'}},
        {'record_id':'second','fields':{'问题':[{'text':'问题二'}],'回复':'答复二'}},
    ]
    return FAQService(store, source, settings)

async def test_faq_skips_blanks_and_preserves_view_order(service):
    result = await service.read()
    assert [item.id for item in result.items] == ['first','second']
    assert result.items[0].answer == '答复\n第二行'
    assert service.normalize([{'record_id':'empty','fields':{}}])[0].items == []

async def test_shared_cache_and_expiry(service, settings):
    redis = FakeRedis(decode_responses=True)
    service.store = RedisStore(redis, 'test')
    await service.read()
    other = FAQService(service.store, service.source, settings)
    await other.read()
    assert service.source.records.await_count == 1
    assert 595 < await redis.ttl('test:'+service.key+':fresh') <= 600
    await service.store.delete(service.key+':fresh')
    service.source.records.return_value = []
    assert (await service.read()).items == []
    await service.store.close()

async def test_failed_refresh_keeps_previous_snapshot(service):
    await service.read()
    await service.store.delete(service.key+':fresh')
    service.source.records.side_effect = httpx.ReadTimeout('failed')
    result = await service.read()
    assert result.stale and len(result.items) == 2

def test_faq_requires_identity(client, app, token, service):
    client.cookies.clear()
    assert client.get('/api/v1/faq').status_code == 401
    app.state.faq = service
    response = client.get('/api/v1/faq', headers={'Authorization':'Bearer '+token})
    assert response.status_code == 200
    assert len(response.json()['data']['items']) == 2
