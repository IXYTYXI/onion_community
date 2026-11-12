import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from fakeredis.aioredis import FakeRedis

from app.core.errors import AppError
from app.core.error_codes import ErrorCode
from app.repositories.store import RedisStore
from app.services.cases import CaseService, CASE_FIELDS
from app.integrations.feishu_directory import FeishuDirectorySource
from conftest import DEV_KEY


def rows():
    return [{'record_id':key,'fields':{'作品名':[{'text':name,'type':'text'}],
             '一句话描述':[{'text':'真实简介'}],'所属团队':'研发团队','第一作者':[{'id':'ou_author','name':'作者'}],
             '作品tag':['数据类','技术开发类'],'产物类型':'Skill','案例来源':'组织效能','案例编号':'001',
             '敏感风控':access,'文档 / 链接':{'link':'https://example.com/private/'+key}}}
            for key,name,access in [('b','案例 B','需申请权限'),('a','案例 A','无敏感可公开'),
                                    ('c','案例 C','无敏感可公开'),('d','案例 D','暂不公开')]]


@pytest.fixture
def service(store,settings):
    settings.cases_table_id='tbl_cases';settings.cases_view_id='vew_cases'
    source=AsyncMock();source.records.return_value=rows()
    return CaseService(store,source,settings)


async def test_shared_cache_order_and_no_sliding_ttl(service,settings):
    redis=FakeRedis(decode_responses=True)
    service.store=RedisStore(redis,'test')
    first=await service.read()
    assert [c.id for c in first.items]==['b','a','c']
    assert first.items[0].url=='https://example.com/private/b'
    assert first.items[1].url=='https://example.com/private/a'
    assert first.items[0].author=='作者'
    assert first.items[0].contact_url.endswith('openId=ou_author')
    raw=await service.store.get(service.key+':snapshot')
    assert '/private/b' in raw and '案例 D' not in raw
    assert 1795 <= await redis.ttl('test:'+service.key+':fresh') <= 1800
    assert 604795 <= await redis.ttl('test:'+service.key+':snapshot') <= 604800
    await redis.expire('test:'+service.key+':fresh',100)
    other_worker=CaseService(service.store,service.source,settings)
    await other_worker.read()
    assert await redis.ttl('test:'+service.key+':fresh') <= 100
    assert service.source.records.await_count==1
    await service.store.delete(service.key+':fresh')
    service.source.records.return_value=rows()[1:]
    assert (await service.read()).items[0].id=='a'
    assert service.source.records.await_count==2
    await service.store.close()


async def test_expired_cache_concurrent_refresh_once(service,store):
    await service.read()
    await store.delete(service.key+':fresh')
    async def slow():
        await asyncio.sleep(.15)
        return rows()
    service.source.records.side_effect=slow
    results=await asyncio.gather(*(service.read() for _ in range(12)))
    assert all(len(r.items)==3 for r in results)
    assert service.source.records.await_count==2


async def test_stale_failure_cooldown_and_recovery(service,store):
    await service.read()
    await store.delete(service.key+':fresh')
    service.source.records.side_effect=httpx.ConnectError('upstream unavailable')
    assert (await service.read()).stale
    assert (await service.read()).stale
    assert service.source.records.await_count==2
    await store.delete(service.key+':cooldown')
    service.source.records.side_effect=None
    assert not (await service.read()).stale


async def test_empty_cold_error_not_published(service,store):
    service.source.records.side_effect=AppError(ErrorCode.UPSTREAM_ERROR)
    with pytest.raises(AppError):await service.read()
    assert await store.get(service.key+':snapshot') is None


async def test_missing_visibility_does_not_replace_last_good_snapshot(service,store):
    original=await service.read()
    await store.delete(service.key+':fresh')
    del service.source.records.return_value[0]['fields']['敏感风控']
    result=await service.read()
    assert result.stale and result.items==original.items


async def test_bad_url_missing_fields_and_valid_empty(service):
    data=rows();data[1]['fields']['文档 / 链接']={'link':'javascript:alert(1)'}
    del data[1]['fields']['一句话描述']
    result,_=service.normalize(data)
    assert result.items[1].url is None and result.items[1].summary==''
    assert service.normalize([])[0].items==[]
    with pytest.raises(ValueError):service.normalize([data[0],data[0]])


def test_cases_require_auth_and_tenant(client,app,service):
    app.state.cases=service
    assert client.get('/api/v1/cases').status_code==401
    client.post('/api/v1/auth/dev',headers={'X-Dev-Login-Key':DEV_KEY})
    result=client.get('/api/v1/cases')
    assert result.status_code==200
    assert [item['id'] for item in result.json()['data']['items']][:3]==['b','a','c']
    assert 'file_token' not in result.text and '/private/d' not in result.text


async def test_source_uses_case_view_and_projection_without_sort_override(settings,store):
    from pydantic import SecretStr
    settings.feishu_app_id='cli_test';settings.feishu_app_secret=SecretStr('secret')
    settings.feishu_bitable_app_token=SecretStr('base')
    import json
    def handler(request):
        if request.url.host=='accounts.feishu.cn':
            return httpx.Response(200,json={'access_token':'test','expires_in':7200})
        assert request.url.path.endswith('/tables/tbl_cases/records/search')
        body=json.loads(request.content)
        assert body=={'view_id':'vew_cases','field_names':CASE_FIELDS}
        assert request.url.params['user_id_type']=='open_id'
        second=request.url.params.get('page_token')=='next'
        return httpx.Response(200,json={'code':0,'data':{'items':rows()[2:] if second else rows()[:2],
                                   'has_more':not second,'page_token':'next'}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source=FeishuDirectorySource(client,settings,store,table_id='tbl_cases',view_id='vew_cases',fields=CASE_FIELDS)
        assert [r['record_id'] for r in await source.records()]==['b','a','c','d']


def cover_rows():
    data = rows()
    data[0]['fields']['封面'] = [
        {'file_token': 'document', 'type': 'application/pdf'},
        {'file_token': 'private-cover', 'type': 'image/png', 'url': 'https://open.feishu.cn/?extra=private'},
        {'file_token': 'second-cover', 'type': 'image/jpeg'},
    ]
    data[3]['fields']['封面'] = [{'file_token': 'hidden-cover', 'type': 'image/png'}]
    return data


def image_bytes():
    import io
    from PIL import Image
    buffer = io.BytesIO()
    Image.new('RGB', (2400, 1350), 'blue').save(buffer, format='PNG')
    return buffer.getvalue()


def test_cover_projection_and_excluded_records(service):
    result, media = service.normalize(cover_rows())
    assert '封面' in CASE_FIELDS
    assert result.items[0].image.startswith('/api/v1/cases/media/')
    assert result.items[1].image is None
    assert list(media.values())[0]['file_token'] == 'private-cover'
    assert len(media) == 1
    assert 'private-cover' not in result.model_dump_json()
    assert 'hidden-cover' not in str(media)
    for bad in [None, '', {}, ['invalid'], [{'file_token': ''}], [{'url': 'https://evil.test/image.png'}]]:
        data = rows(); data[0]['fields']['封面'] = bad
        assert service.normalize(data)[0].items[0].image is None


async def test_cover_disk_cache_concurrent_miss_and_missing_disk_refetch(service, store, tmp_path):
    from PIL import Image
    service.root = tmp_path / 'cases'
    service.source.records.return_value = cover_rows()
    service.source.download.return_value = image_bytes()
    first = await service.read()
    image_id = first.items[0].image.rsplit('/', 1)[1]
    paths = await asyncio.gather(*(service.image(image_id) for _ in range(8)))
    assert len(set(paths)) == 1 and service.source.download.await_count == 1
    with Image.open(paths[0]) as image:
        assert image.format == 'WEBP' and image.size == (1600, 900)
    await service.image(image_id)
    assert service.source.records.await_count == 1
    assert service.source.download.await_count == 1
    paths[0].unlink()  # New host / cleared disk: recover from Feishu using Redis's index.
    await store.delete(service.media_rate_key)
    assert (await service.image(image_id)).is_file()
    assert service.source.download.await_count == 2


async def test_cover_replacement_removal_visibility_and_redis_rebuild(service, store, tmp_path):
    service.root = tmp_path / 'cases'
    service.source.records.return_value = cover_rows()
    service.source.download.return_value = image_bytes()
    first = (await service.read()).items[0].image
    old_id = first.rsplit('/', 1)[1]
    await service.image(old_id)
    await store.delete(service.key + ':fresh')
    service.source.records.return_value[0]['fields']['封面'][1]['file_token'] = 'replacement'
    second = (await service.read()).items[0].image
    assert second != first
    with pytest.raises(AppError):
        await service.image(old_id)
    new_id = second.rsplit('/', 1)[1]
    await store.delete(service.media_rate_key)
    path = await service.image(new_id)
    await store.delete(service.key + ':media:' + new_id)
    assert await service.image(new_id) == path  # Independently evicted index is rebuilt.
    # Redis loss: a fresh snapshot re-registers still-current attachments; disk is reused.
    await store.delete(service.key + ':media:' + new_id)
    await store.delete(service.key + ':snapshot')
    await store.delete(service.key + ':fresh')
    assert await service.image(new_id) == path
    assert service.source.download.await_count == 2
    await store.delete(service.key + ':fresh')
    service.source.records.return_value[0]['fields']['敏感风控'] = '暂不公开'
    assert all(item.id != 'b' for item in (await service.read()).items)
    with pytest.raises(AppError):
        await service.image(new_id)
    service.source.records.return_value[0]['fields']['敏感风控'] = '需申请权限'
    service.source.records.return_value[0]['fields']['封面'] = []
    await store.delete(service.key + ':fresh')
    assert (await service.read()).items[0].image is None


async def test_bad_cover_download_uses_cooldown_and_never_publishes_file(service, store, tmp_path):
    service.root = tmp_path / 'cases'
    service.source.records.return_value = cover_rows()
    service.source.download.return_value = b'not-an-image'
    image_id = (await service.read()).items[0].image.rsplit('/', 1)[1]
    for _ in range(2):
        with pytest.raises(AppError):
            await service.image(image_id)
    assert service.source.download.await_count == 1
    assert not list(service.root.glob('*.webp'))
    for invalid in ['../.env', 'f' * 64]:
        with pytest.raises(AppError):
            await service.image(invalid)


def test_cover_api_requires_auth_and_tenant_and_hides_tokens(client, app, service, tmp_path):
    from app.api.dependencies import current_user
    from app.schemas.auth import Principal
    app.state.cases = service
    service.root = tmp_path / 'cases'
    service.source.records.return_value = cover_rows()
    service.source.download.return_value = image_bytes()
    assert client.get('/api/v1/cases/media/' + 'a' * 64).status_code == 401
    client.post('/api/v1/auth/dev', headers={'X-Dev-Login-Key': DEV_KEY})
    result = client.get('/api/v1/cases')
    assert 'private-cover' not in result.text and 'file_token' not in result.text
    url = result.json()['data']['items'][0]['image']
    image = client.get(url)
    assert image.status_code == 200 and image.headers['content-type'] == 'image/webp'
    assert image.headers['cache-control'] == 'no-store'
    app.state.settings.cases_source_tenant = 'correct'
    app.dependency_overrides[current_user] = lambda: Principal(
        user_id='someone', display_name='Someone', identity_source='feishu', tenant_id='wrong')
    try:
        assert client.get('/api/v1/cases').status_code == 403
        assert client.get(url).status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_description_prefers_explicit_text_and_falls_back_to_lookup(service):
    data = rows()
    data[0]['fields']['一句话描述'] = [{'text': '直接填写的描述'}]
    data[0]['fields']['一句话简单描述'] = {'value': [{'text': '关联的描述'}]}
    data[1]['fields']['一句话描述'] = '   '
    data[1]['fields']['一句话简单描述'] = {'value': [{'text': '关联的描述'}]}
    result, _ = service.normalize(data)
    assert result.items[0].summary == '直接填写的描述'
    assert result.items[1].summary == '关联的描述'
    assert '一句话简单描述' in CASE_FIELDS


def test_formula_description_bridge_and_officer_lookup(service):
    data = rows()
    data[0]['fields'].pop('一句话描述', None)
    data[0]['fields']['网站案例描述'] = {'type': 1, 'value': [{'text': '来自扩展字段的描述'}]}
    data[0]['fields']['团队 AI 官'] = {'type': 11, 'value': [
        {'id': 'ou_first', 'name': '第一位', 'email': 'private@example.com'},
        {'id': 'ou_second', 'name': '第二位'},
        {'id': 'ou_first', 'name': '重复'},
        {'id': 'invalid', 'name': '无效'},
        {'name': '只有名字'},
    ]}
    result, _ = service.normalize(data)
    item = result.items[0]
    assert item.summary == '来自扩展字段的描述'
    assert [person.name for person in item.ai_officers] == ['第一位', '第二位']
    assert item.ai_officers[0].chat_url.endswith('openId=ou_first')
    assert 'private@example.com' not in result.model_dump_json()
    assert result.items[1].ai_officers == []
