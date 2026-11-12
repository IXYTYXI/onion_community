import asyncio
import io
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from PIL import Image
from fastapi.testclient import TestClient

from app.core.errors import AppError
from app.core.error_codes import ErrorCode
from app.services.officers import OfficerService
from app.repositories.store import MemoryStore, RedisStore
from app.integrations.feishu_directory import FeishuDirectorySource
from conftest import DEV_KEY


def rows():
    return [{'record_id':str(i),'fields':{'人员':[{'name':name}], 'title':{'value':[{'text':title}]},
            '团队':{'value':['研发团队']},'定位':{'value':[{'text':'产品团队 AI 官'}]},'tag':{'value':['AI 技术专家','AI PMO']},'个性签名':'<script>text</script>',
            '形象':[{'file_token':'photo'+str(i),'url':'https://open.feishu.cn/download?extra=permission'}]}}
            for i,name,title in [(1,'成员 A','业务 AI 先锋'),(2,'成员 B','组织效能团队'),(3,'成员 C','组织效能团队')]]


@pytest.fixture
def service(store,settings,tmp_path):
    settings.media_root=tmp_path
    source=AsyncMock()
    source.records.return_value=rows()
    return OfficerService(store,source,settings)


async def test_hit_expiry_refresh_and_title_order(service,store):
    first=await service.read()
    assert [p.name for p in first.items]==['成员 B','成员 C','成员 A']
    assert first.items[0].tags==['AI 技术专家','AI PMO']
    cached=await service.read()
    assert cached.items[0].position == first.items[0].position == '产品团队 AI 官'
    assert cached.items[0].team == '研发团队'
    assert service.source.records.await_count==1
    await store.delete(service.key+':fresh')
    service.source.records.return_value=[]
    assert (await service.read()).items==[]
    assert service.source.records.await_count==2


async def test_contact_link_uses_person_id_and_is_cached(service):
    service.source.records.return_value[0]['fields']['人员'][0]['id']='ou_member_a'
    first=await service.read()
    person=next(p for p in first.items if p.id=='1')
    assert person.chat_url=='https://applink.feishu.cn/client/chat/open?openId=ou_member_a'
    cached=await service.read()
    assert next(p for p in cached.items if p.id=='1').chat_url==person.chat_url
    assert service.source.records.await_count==1


@pytest.mark.parametrize('people', [
    [{'name':'A'}], [{'name':'A','id':'not-an-open-id'}],
    [{'name':'A','id':'ou_a&redirect=https://example.com'}],
    [{'name':'A','id':'ou_a'},{'name':'B','id':'ou_b'}],
])
def test_contact_link_missing_invalid_or_ambiguous_is_unavailable(service,people):
    records=rows()
    records[0]['fields']['人员']=people
    result,_=service.normalize(records)
    assert next(p for p in result.items if p.id=='1').chat_url is None


async def test_concurrent_miss_fetches_once(service):
    async def slow():
        await asyncio.sleep(.15)
        return rows()
    service.source.records.side_effect=slow
    results=await asyncio.gather(*(service.read() for _ in range(12)))
    assert all(len(r.items)==3 for r in results)
    assert service.source.records.await_count==1


async def test_refresh_failure_keeps_last_good_and_cools_down(service,store):
    await service.read()
    await store.delete(service.key+':fresh')
    service.source.records.side_effect=AppError(ErrorCode.UPSTREAM_ERROR)
    assert (await service.read()).stale
    assert (await service.read()).stale
    assert service.source.records.await_count==2
    assert await store.get(service.key+':snapshot')


async def test_cold_failure_does_not_publish_empty(service,store):
    service.source.records.side_effect=httpx.ConnectError('private')
    with pytest.raises(AppError): await service.read()
    assert await store.get(service.key+':snapshot') is None


async def test_private_images_download_once_and_cannot_traverse(service):
    buffer=io.BytesIO();Image.new('RGB',(20,20),'blue').save(buffer,format='PNG')
    service.source.download.return_value=buffer.getvalue()
    directory=await service.read()
    image_id=directory.items[0].image.rsplit('/',1)[-1]
    path=await service.image(image_id)
    assert path.is_file() and Image.open(path).format=='WEBP'
    assert await service.image(image_id)==path
    assert service.source.download.await_count==1
    with pytest.raises(AppError): await service.image('../.env')
    with pytest.raises(AppError): await service.image('f'*64)


def test_high_resolution_camera_photo_is_reduced_and_oriented(tmp_path):
    buffer = io.BytesIO()
    original = Image.new('RGB', (6400, 4000), 'blue')
    exif = original.getexif()
    exif[274] = 6  # Rotate a landscape camera raster into a portrait.
    original.save(buffer, format='JPEG', exif=exif)
    original.close()
    target = tmp_path / 'photo.webp'
    OfficerService.save_image(buffer.getvalue(), target)
    with Image.open(target) as result:
        assert result.format == 'WEBP'
        assert result.width < result.height <= 1200
        assert result.width <= 960
        assert not result.getexif()


def test_camera_mpo_uses_primary_photo(tmp_path):
    buffer = io.BytesIO()
    with Image.new('RGB', (40, 30), 'red') as primary, Image.new('RGB', (40, 30), 'blue') as auxiliary:
        primary.save(buffer, format='MPO', save_all=True, append_images=[auxiliary])
    with Image.open(io.BytesIO(buffer.getvalue())) as source:
        assert source.format == 'MPO' and source.n_frames == 2
    target = tmp_path / 'primary.webp'
    OfficerService.save_image(buffer.getvalue(), target)
    with Image.open(target) as result:
        red, green, blue = result.getpixel((20, 15))
        assert red > 200 and green < 30 and blue < 30


@pytest.mark.parametrize('kind',['memory','redis'])
async def test_lease_release_cannot_delete_another_owner(kind):
    from fakeredis.aioredis import FakeRedis
    store=MemoryStore() if kind=='memory' else RedisStore(FakeRedis(decode_responses=True),'test')
    assert await store.acquire('lock','new',60)
    assert not await store.acquire('lock','old',60)
    await store.release('lock','old')
    assert await store.get('lock')=='new'
    await store.release('lock','new')
    assert await store.get('lock') is None
    await store.set_many({'snapshot':('ok',60),'fresh':('1',10)})
    assert await store.get('snapshot')=='ok'
    await store.close()


def test_api_and_images_require_auth(client,app,service):
    app.state.officers=service
    assert client.get('/api/v1/officers').status_code==401
    assert client.get('/api/v1/officers/media/'+'a'*64).status_code==401
    assert client.get('/officers.html',follow_redirects=False).status_code==303
    client.post('/api/v1/auth/dev',headers={'X-Dev-Login-Key':DEV_KEY})
    response=client.get('/api/v1/officers')
    assert response.status_code==200 and len(response.json()['data']['items'])==3
    assert 'file_token' not in response.text and 'open.feishu.cn' not in response.text
    assert client.get('/officers.html').status_code==200


async def test_source_paginates_and_preserves_view(settings,store):
    import json
    settings.feishu_app_id='cli_test'; settings.feishu_app_secret='secret'
    from pydantic import SecretStr
    settings.feishu_app_secret=SecretStr('secret');settings.feishu_bitable_app_token=SecretStr('base')
    settings.officers_table_id='tbl_test';settings.officers_view_id='vew_test'
    calls=[]
    def handler(request):
        calls.append(request)
        if request.url.host=='accounts.feishu.cn':
            return httpx.Response(200,json={'code':0,'access_token':'server-secret','expires_in':7200})
        body=json.loads(request.content)
        assert request.url.params['user_id_type']=='open_id'
        assert '定位' in body['field_names']
        assert body['view_id']=='vew_test' and 'filter' not in body and 'sort' not in body
        assert request.headers['Authorization']=='Bearer server-secret'
        second=request.url.params.get('page_token')=='next'
        return httpx.Response(200,json={'code':0,'data':{'items':[rows()[1 if second else 0]],'has_more':not second,'page_token':'next'}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source=FeishuDirectorySource(client,settings,store)
        result=await source.records()
    assert len(result)==2 and len(calls)==3


def test_missing_position_does_not_reuse_team(service):
    records = rows()
    del records[0]['fields']['定位']
    result, _ = service.normalize(records)
    assert next(p for p in result.items if p.id == '1').position == ''
