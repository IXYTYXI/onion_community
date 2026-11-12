import httpx
import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.integrations.feishu import FeishuIdentityProvider, PROFILE_SCOPES
from conftest import DEV_KEY


def test_future_endpoints_default_to_authenticated_and_csrf(app):
    calls = []
    router = APIRouter()
    async def future():
        calls.append(True)
        return {"ok": True}
    # Neither registration style has an explicit authentication dependency.
    app.add_api_route('/future', future, methods=['GET', 'POST'])
    router.add_api_route('/api/v2/items', future, methods=['GET', 'POST'])
    router.add_api_route('/api/v1/auth/future', future, methods=['GET'])
    router.add_api_route('/health/private', future, methods=['GET'])
    app.include_router(router)
    with TestClient(app) as client:
        for path in ['/future', '/api/v2/items', '/api/v1/auth/future', '/health/private']:
            assert client.get(path).status_code == 401
        assert not calls
        token = client.post('/api/v1/auth/dev', headers={'X-Dev-Login-Key': DEV_KEY}).json()['data']['access_token']
        assert client.get('/future').status_code == 200
        assert client.post('/api/v2/items').status_code == 403
        csrf = client.get('/api/v1/auth/session').json()['data']['csrf_token']
        assert client.post('/api/v2/items', headers={'Origin':'http://127.0.0.1:8765','X-CSRF-Token':csrf}).status_code == 200
        assert client.get('/future', headers={'Authorization':'Bearer wrong'}).status_code == 401
        assert client.post('/api/v1/auth/logout', headers={'Authorization':f'Bearer {token}'}).status_code == 200
        assert client.get('/future', headers={'Authorization':f'Bearer {token}'}).status_code == 401


async def test_profile_reads_only_signed_in_user_and_all_departments():
    paths = []
    def handler(request):
        paths.append(request.url.path)
        assert request.headers['Authorization'] == 'Bearer private'
        assert request.url.params['department_id_type'] == 'open_department_id'
        if '/users/' in request.url.path:
            assert request.url.path.endswith('/ou_self')
            return httpx.Response(200,json={'code':0,'data':{'user':{'email':'user@example.test','department_ids':['od-a','od-b','od-a']}}})
        return httpx.Response(200,json={'code':0,'data':{'department':{'name':'部门 A' if request.url.path.endswith('od-a') else '部门 B'}}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        email, departments, status = await FeishuIdentityProvider(client,Settings(_env_file=None, news_sync_enabled=False)).profile('private',{'open_id':'ou_self','enterprise_email':'work@example.test'})
    assert email == 'work@example.test'
    assert [d.name for d in departments] == ['部门 A','部门 B']
    assert status == 'complete' and len(paths) == 3


@pytest.mark.parametrize('failure', ['permission','timeout','malformed'])
async def test_optional_profile_failure_preserves_identity_email(failure):
    def handler(request):
        if failure == 'timeout':
            raise httpx.ReadTimeout('secret', request=request)
        if failure == 'malformed':
            return httpx.Response(200,text='invalid')
        return httpx.Response(403,json={'code':99991672,'msg':'private upstream details'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        email, departments, status = await FeishuIdentityProvider(client,Settings(_env_file=None, news_sync_enabled=False)).profile('private',{'open_id':'ou_self','email':'user@example.test'})
    assert email == 'user@example.test' and not departments and status == 'partial'


def test_profile_survives_session_and_me(client, app):
    from app.schemas.auth import Principal, Department
    user = Principal(user_id='self',tenant_id='tenant',display_name='成员',identity_source='feishu',
                     email='member@example.test',departments=[Department(department_id='od-a',name='技术部')],profile_status='complete')
    issued = client.portal.call(app.state.auth.issue, user)
    for path in ['/api/v1/me','/api/v1/auth/session']:
        response=client.get(path,headers={'Authorization':f'Bearer {issued.access_token}'})
        body=response.json()['data']
        data=body.get('user',body)
        assert data['email']=='member@example.test' and data['departments'][0]['name']=='技术部'
        assert 'private' not in response.text


def test_oauth_requests_profile_scopes_only_when_enabled(client, app):
    from urllib.parse import urlsplit, parse_qs
    from pydantic import SecretStr
    app.state.settings.feishu_app_id='cli_test'
    app.state.settings.feishu_app_secret=SecretStr('test')
    path='/api/v1/auth/feishu/start'
    query=parse_qs(urlsplit(client.get(path,follow_redirects=False).headers['location']).query)
    assert 'scope' not in query
    app.state.settings.feishu_profile_enabled=True
    query=parse_qs(urlsplit(client.get(path,follow_redirects=False).headers['location']).query)
    assert set(query['scope'][0].split()) == set(PROFILE_SCOPES)


async def test_exchange_enriches_verified_identity():
    def handler(request):
        if request.url.path.endswith('/oauth/token'):
            return httpx.Response(200,json={'code':0,'access_token':'private'})
        if request.url.path.endswith('/user_info'):
            return httpx.Response(200,json={'code':0,'data':{'open_id':'ou_self','tenant_key':'tenant','name':'成员'}})
        if '/users/' in request.url.path:
            return httpx.Response(200,json={'code':0,'data':{'user':{'email':'self@example.test','department_ids':['od-a']}}})
        return httpx.Response(200,json={'code':0,'data':{'department':{'name':'研发部'}}})
    settings=Settings(_env_file=None, news_sync_enabled=False,feishu_app_id='cli_test',feishu_app_secret='secret',feishu_profile_enabled=True)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        principal=await FeishuIdentityProvider(client,settings).exchange_code('once','verifier')
    assert principal.email=='self@example.test'
    assert principal.departments[0].name=='研发部'
    assert principal.profile_status=='complete'
    assert principal.roles==['member']
