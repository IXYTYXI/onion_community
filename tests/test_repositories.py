from datetime import UTC, datetime

import fakeredis.aioredis
import pytest
from pydantic import ValidationError
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.errors import AppError
from app.repositories.snapshots import SnapshotRepository
from app.repositories.store import RedisStore
from app.schemas.auth import Principal
from app.schemas.content import ContentSnapshot
from app.services.auth import AuthService


@pytest.fixture
async def redis_store():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    store = RedisStore(client, "test")
    yield store
    await store.close()


async def test_snapshot_publication_has_no_ttl_and_keeps_complete_value(redis_store):
    repo = SnapshotRepository(redis_store)
    with pytest.raises(AppError) as exc:
        await repo.read()
    assert exc.value.code == "SNAPSHOT_NOT_READY"
    first = ContentSnapshot(version="v1", synced_at=datetime.now(UTC))
    await repo.publish(first)
    assert await redis_store.client.ttl("test:content:current") == -1
    assert (await repo.read()).version == "v1"
    second = ContentSnapshot(version="v2", synced_at=datetime.now(UTC))
    await repo.publish(second)
    assert (await repo.read()).version == "v2"


async def test_failed_publish_keeps_prior_snapshot(redis_store, monkeypatch):
    repo = SnapshotRepository(redis_store)
    await repo.publish(ContentSnapshot(version="v1", synced_at=datetime.now(UTC)))
    async def fail(*args, **kwargs):
        raise RedisConnectionError("unavailable")
    monkeypatch.setattr(redis_store, "set", fail)
    with pytest.raises(RedisConnectionError):
        await repo.publish(ContentSnapshot(version="v2", synced_at=datetime.now(UTC)))
    assert (await repo.read()).version == "v1"


async def test_sessions_are_shared_revocable_and_expiring(redis_store):
    one, two = AuthService(redis_store, 60), AuthService(redis_store, 60)
    principal = Principal(user_id="u1", tenant_id="t1", display_name="User", identity_source="development")
    issued = await one.issue(principal)
    assert (await two.authenticate(issued.access_token)).user_id == "u1"
    keys = await redis_store.client.keys("test:session:*")
    assert len(keys) == 1 and issued.access_token not in keys[0]
    assert 0 < await redis_store.client.ttl(keys[0]) <= 60
    await two.revoke(issued.access_token)
    with pytest.raises(AppError):
        await one.authenticate(issued.access_token)


def test_snapshot_rejects_duplicate_ids():
    item = dict(id="same", title="title", category="test", source="test", summary="test")
    with pytest.raises(ValidationError):
        ContentSnapshot(version="v1", synced_at=datetime.now(UTC), cases=[item, item])
