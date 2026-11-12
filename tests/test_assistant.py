import json
import time
from types import SimpleNamespace
from uuid import uuid4
import pytest
from app.repositories.store import MemoryStore
from app.services.assistant import AssistantService
from app.schemas.assistant import ChatInput
from app.schemas.auth import Principal
from app.core.errors import AppError


class Source:
    def __init__(self):
        self.starts = 0
        self.writes = []
    async def start(self, message, session_id):
        self.starts += 1
        return {'session_id': 'remote', 'agent_chat_id': 'chat'}
    async def result(self, chat_id):
        return {'status': 'Completed', 'content': [{'type': 'text', 'text': json.dumps({'answer': '是否提交？', 'ticket': {'title': '测试', 'category': '网站错误', 'description': '按钮无法点击'}})}]}
    async def ticket(self, ticket_id, fields):
        self.writes.append((ticket_id, fields))
        return 'record'


class FAQ:
    async def read(self):
        return SimpleNamespace(items=[])


def setup():
    store, source = MemoryStore(), Source()
    service = AssistantService(store, source, SimpleNamespace(), FAQ())
    user = Principal(user_id='a', tenant_id='tenant', display_name='A', identity_source='development')
    return service, source, user


async def test_fixed_expiration_and_owner_isolation():
    service, source, user = setup()
    first = await service.open(user)
    assert (await service.open(user))['id'] == first['id']
    assert (await service.open(user))['expires_at'] == first['expires_at']
    other = user.model_copy(update={'user_id': 'b'})
    with pytest.raises(AppError):
        await service.poll(other, first['id'])
    raw = await service.load(user)
    raw['expires_at'] = time.time() - 1
    await service.store.set(service.key(user), json.dumps(raw))
    with pytest.raises(AppError):
        await service.poll(user, first['id'])
    assert (await service.open(user))['id'] != first['id']


async def test_confirm_required_idempotency_and_cancel():
    service, source, user = setup()
    first = await service.open(user)
    message = ChatInput(session_id=first['id'], request_id=uuid4(), message='反馈一个错误')
    await service.send(user, message)
    await service.send(user, message)
    assert source.starts == 1
    answer = await service.poll(user, first['id'])
    assert not source.writes
    draft = answer['draft']['id']
    with pytest.raises(AppError):
        await service.decide(user, first['id'], uuid4(), True)
    await service.decide(user, first['id'], draft, True)
    await service.decide(user, first['id'], draft, True)
    assert len(source.writes) == 1
    assert source.writes[0][1]['提交人标识'] == 'tenant:a'


async def test_cancellation_cannot_later_submit():
    service, source, user = setup()
    first = await service.open(user)
    await service.send(user, ChatInput(session_id=first['id'], request_id=uuid4(), message='反馈错误'))
    answer = await service.poll(user, first['id'])
    await service.decide(user, first['id'], answer['draft']['id'], False)
    result = await service.decide(user, first['id'], answer['draft']['id'], True)
    assert result['draft']['status'] == 'cancelled'
    assert not source.writes


def test_malformed_model_response_cannot_create_ticket():
    assert AssistantService.parse('不是JSON')[1] is None
    assert AssistantService.parse('{"answer":"test","ticket":{"category":"任意写表"}}')[1] is None


async def test_upstream_failure_releases_capacity():
    service, source, user = setup()
    first = await service.open(user)
    async def fail(*args):
        raise TimeoutError()
    source.start = fail
    with pytest.raises(AppError) as error:
        await service.send(user, ChatInput(session_id=first['id'], request_id=uuid4(), message='问题'))
    assert error.value.code.value == 'UPSTREAM_TIMEOUT'
    for index in range(4):
        assert await service.store.acquire(f'assistant:slot:{index}', 'check', 1)
    assert not (await service.open(user))['pending']


async def test_global_concurrency_and_terminal_release():
    service, source, user = setup()
    sessions = []
    for index in range(4):
        owner = user.model_copy(update={'user_id': str(index)})
        session = await service.open(owner)
        await service.send(owner, ChatInput(session_id=session['id'], request_id=uuid4(), message='问题'))
        sessions.append((owner, session['id']))
    fifth = await service.open(user)
    with pytest.raises(AppError) as error:
        await service.send(user, ChatInput(session_id=fifth['id'], request_id=uuid4(), message='问题'))
    assert error.value.code.value == 'RATE_LIMITED'
    await service.poll(*sessions[0])
    assert (await service.send(user, ChatInput(session_id=fifth['id'], request_id=uuid4(), message='问题')))['pending']


def test_assistant_auth_disabled_and_csrf(client, app, token):
    from conftest import DEV_KEY
    client.cookies.clear()
    for method, path in [('GET', '/config'), ('POST', '/session'), ('POST', '/messages'), ('GET', '/session/' + str(uuid4())), ('POST', '/tickets/' + str(uuid4()) + '/decision')]:
        assert client.request(method, '/api/v1/assistant' + path).status_code == 401
    headers = {'Authorization': 'Bearer ' + token}
    assert client.get('/api/v1/assistant/config', headers=headers).json()['data']['enabled'] is False
    assert client.post('/api/v1/assistant/session', headers=headers).status_code == 503
    app.state.settings.assistant_enabled = True
    client.post('/api/v1/auth/dev', headers={'X-Dev-Login-Key': DEV_KEY})
    assert client.post('/api/v1/assistant/session').status_code == 403
    csrf = client.get('/api/v1/auth/session').json()['data']['csrf_token']
    assert client.post('/api/v1/assistant/session', headers={'Origin': 'https://evil.test', 'X-CSRF-Token': csrf}).status_code == 403
    assert client.post('/api/v1/assistant/session', headers={'Origin': app.state.settings.site_origin, 'X-CSRF-Token': csrf}).status_code == 200


def test_assistant_requires_complete_configuration():
    from app.core.config import Settings
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Settings(_env_file=None, news_sync_enabled=False, assistant_enabled=True)
