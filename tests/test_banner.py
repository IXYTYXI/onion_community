import asyncio
import io
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from fakeredis.aioredis import FakeRedis
from PIL import Image
from pydantic import SecretStr

from app.core.errors import AppError
from app.integrations.feishu_directory import FeishuDirectorySource
from app.repositories.store import RedisStore
from app.schemas.banner import Banner
from app.services.banner import BannerService, BANNER_FIELDS
from conftest import DEV_KEY


def rows():
    return [
        {'record_id': 'blank', 'created_time': 1000, 'fields': {'标题': '  '}},
        {'record_id': 'first', 'created_time': 3000, 'fields': {'标题': [{'text': '社区活动'}], '描述': '欢迎参加',
         '封面': [{'file_token': 'private-token', 'url': 'https://open.feishu.cn/?extra=private'}],
         '链接': {'link': 'https://example.com/event'}}},
        {'record_id': 'second', 'created_time': 2000, 'fields': {'标题': '下一期'}},
    ]


@pytest.fixture
def service(settings, store, tmp_path):
    settings.banner_table_id = 'tbl_banner'
    settings.banner_view_id = 'vew_banner'
    settings.media_root = tmp_path
    source = AsyncMock()
    source.records.return_value = rows()
    return BannerService(store, source, settings)


async def test_shared_24h_ttl_expiry_and_empty_table(service, settings):
    redis = FakeRedis(decode_responses=True)
    service.store = RedisStore(redis, 'test')
    first = await service.read()
    assert first.item.id == 'first'
    assert first.item.title == '社区活动'
    assert first.item.url == 'https://example.com/event'
    assert 86395 <= await redis.ttl('test:' + service.key + ':fresh') <= 86400
    assert 604795 <= await redis.ttl('test:' + service.key + ':snapshot') <= 604800
    await redis.expire('test:' + service.key + ':fresh', 123)
    other_worker = BannerService(service.store, service.source, settings)
    assert (await other_worker.read()).item == first.item
    assert await redis.ttl('test:' + service.key + ':fresh') <= 123  # No sliding expiration.
    assert service.source.records.await_count == 1
    await service.store.delete(service.key + ':fresh')
    service.source.records.return_value = []
    assert (await service.read()).item is None  # Deliberate removal replaces the old banner.
    assert service.source.records.await_count == 2
    await service.store.close()


def test_optional_title_fields_and_unsafe_link(service):
    result, media = service.normalize(rows()[2:])
    assert result.item.summary == '' and result.item.image is None and result.item.url is None
    assert media == {}
    data = rows()
    data[1]['fields']['链接'] = {'link': 'javascript:alert(1)'}
    assert service.normalize(data)[0].item.url is None
    assert service.normalize(rows()[:1])[0].item.title == ''
    assert Banner(id='x', title='').title == ''


async def test_concurrent_miss_only_fetches_once(service):
    async def slow():
        await asyncio.sleep(.15)
        return rows()
    service.source.records.side_effect = slow
    results = await asyncio.gather(*(service.read() for _ in range(12)))
    assert all(result.item.id == 'first' for result in results)
    assert service.source.records.await_count == 1


async def test_failure_retains_good_snapshot_and_cold_failure_is_error(service, store):
    original = await service.read()
    await store.delete(service.key + ':fresh')
    service.source.records.side_effect = httpx.ConnectError('failure')
    stale = await service.read()
    assert stale.stale and stale.item == original.item
    assert (await service.read()).stale
    assert service.source.records.await_count == 2
    await store.delete(service.key + ':snapshot')
    await store.delete(service.key + ':cooldown')
    with pytest.raises(AppError):
        await service.read()
    assert await store.get(service.key + ':snapshot') is None


async def test_cover_cached_once_and_new_attachment_gets_new_url(service, store):
    buffer = io.BytesIO()
    with Image.new('RGB', (3000, 1000), 'blue') as image:
        image.save(buffer, format='PNG')
    service.source.download.return_value = buffer.getvalue()
    first = await service.read()
    image_id = first.item.image.rsplit('/', 1)[1]
    path = await service.image(image_id)
    with Image.open(path) as image:
        assert image.format == 'WEBP' and image.size == (2400, 800)
    assert await service.image(image_id) == path
    assert service.source.download.await_count == 1
    await store.delete(service.key + ':fresh')
    service.source.records.return_value[1]['fields']['封面'][0]['file_token'] = 'new-token'
    assert (await service.read()).item.image != first.item.image
    with pytest.raises(AppError):
        await service.image('../.env')
    with pytest.raises(AppError):
        await service.image('f' * 64)


def test_api_authentication_and_no_attachment_credentials(client, app, service):
    app.state.banner = service
    assert client.get('/api/v1/banner').status_code == 401
    assert client.get('/api/v1/banner/media/' + 'a' * 64).status_code == 401
    client.post('/api/v1/auth/dev', headers={'X-Dev-Login-Key': DEV_KEY})
    response = client.get('/api/v1/banner')
    assert response.status_code == 200 and response.json()['data']['item']['title'] == '社区活动'
    assert 'file_token' not in response.text and 'private-token' not in response.text
    assert 'open.feishu.cn' not in response.text
    buffer = io.BytesIO()
    Image.new('RGB', (20, 10), 'blue').save(buffer, format='PNG')
    service.source.download.return_value = buffer.getvalue()
    response = client.get(response.json()['data']['item']['image'])
    assert response.status_code == 200 and response.headers['content-type'] == 'image/webp'


async def test_source_uses_only_banner_view_and_fields(settings, store):
    settings.feishu_app_id = 'cli_test'
    settings.feishu_app_secret = SecretStr('secret')
    settings.feishu_bitable_app_token = SecretStr('base')
    def handler(request):
        if request.url.host == 'accounts.feishu.cn':
            return httpx.Response(200, json={'access_token': 'secret', 'expires_in': 7200})
        assert request.url.path.endswith('/tables/tbl_banner/records/search')
        assert json.loads(request.content) == {'view_id': 'vew_banner', 'field_names': BANNER_FIELDS, 'automatic_fields': True}
        return httpx.Response(200, json={'data': {'items': rows(), 'has_more': False}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = FeishuDirectorySource(client, settings, store, table_id='tbl_banner',
                                       view_id='vew_banner', fields=BANNER_FIELDS, automatic_fields=True)
        assert len(await source.records()) == 3


def test_newest_created_record_wins_even_without_title(service):
    data = rows()
    data[0]['created_time'] = 4000
    data[1]['last_modified_time'] = 9999
    result, _ = service.normalize(data)
    assert result.item.id == 'blank' and result.item.title == ''
    assert service.normalize(list(reversed(data)))[0].item.id == 'blank'


async def test_missing_creation_time_does_not_replace_good_cache(service, store):
    original = await service.read()
    await store.delete(service.key + ':fresh')
    del service.source.records.return_value[0]['created_time']
    result = await service.read()
    assert result.stale and result.item == original.item


async def test_replaced_banner_image_is_denied_even_when_file_is_cached(service, store):
    original = await service.read()
    image_id = original.item.image.rsplit('/', 1)[-1]
    service.root.mkdir(parents=True, exist_ok=True)
    (service.root / (image_id + '.webp')).write_bytes(b'old cached image')
    service.source.records.return_value = []
    await store.delete(service.key + ':fresh')
    await service.read()
    with pytest.raises(AppError) as error:
        await service.image(image_id)
    assert error.value.code.definition.status == 404
    service.source.download.assert_not_awaited()


def test_media_rate_limit_shared_across_tables(service, settings, store):
    from app.services.cases import CaseService
    other = CaseService(store, AsyncMock(), settings)
    assert service.key != other.key
    assert service.media_rate_key == other.media_rate_key
