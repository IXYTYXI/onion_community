import asyncio
import sqlite3
from concurrent.futures import ProcessPoolExecutor
from contextlib import closing
from multiprocessing import get_context

import pytest

from app.core.error_codes import ErrorCode
from app.core.errors import AppError
from app.repositories.case_interactions import CaseInteractionDB

META = {'title': '案例', 'author_id': 'ou_author', 'author_name': '作者'}


def row(account, case='a', liked=True, favorited=True, liked_at=10, favorited_at=20):
    return dict(case_id=case, account=str(account), liked=liked, favorited=favorited,
                liked_at=liked_at, favorited_at=favorited_at)


async def test_import_merges_duplicate_actions_filters_visible_and_is_one_time(tmp_path):
    path = tmp_path / 'db' / 'interactions.sqlite3'
    db = CaseInteractionDB(path)
    assert db.path == path and not await db.is_initialized('prod')
    rows = [row('me', liked_at=15, favorited=False), row('me', liked_at=1, favorited_at=None),
            row('me', liked=False, liked_at=900, favorited_at=17), row('other', liked_at=None),
            row('me', case='hidden')]
    assert await db.import_rows('prod', rows, {'a': META})
    assert not await CaseInteractionDB(path).import_rows('prod', [row('third')], {})
    visible = await db.directory('prod', 'me', {'a', 'empty'})
    assert visible['a'].model_dump() == dict(liked=True, favorited=True, liked_at=15,
                                             favorited_at=17, like_count=2, favorite_count=2)
    assert visible['empty'].like_count == 0 and not visible['empty'].liked
    assert set(visible) == {'a', 'empty'}
    assert not await db.pending_coins() and not await db.pending_sync('prod')
    assert await db.import_rows('test', [], {})
    assert (await db.directory('test', 'me', {'a'}))['a'].like_count == 0


async def test_requires_complete_import_and_reports_unavailable_file(tmp_path):
    db = CaseInteractionDB(tmp_path / 'interactions.sqlite')
    with pytest.raises(AppError) as exc:
        await db.set_active('prod', 'member', 'a', 'like', True, META)
    assert exc.value.code is ErrorCode.SNAPSHOT_NOT_READY
    with pytest.raises(AppError) as exc:
        await db.directory('prod', 'member', set())
    assert exc.value.code is ErrorCode.SNAPSHOT_NOT_READY
    with pytest.raises(KeyError):
        await db.import_rows('prod', [row('one'), {}], {})
    assert not await db.is_initialized('prod')
    await db.import_rows('prod', [], {})
    assert (await db.directory('prod', 'one', {'a'}))['a'].like_count == 0
    with pytest.raises(AppError) as exc:
        await CaseInteractionDB(tmp_path).is_initialized('prod')
    assert exc.value.code is ErrorCode.SERVICE_UNAVAILABLE


async def test_mirror_coalesces_and_delayed_ack_cannot_consume_new_revision(tmp_path):
    path = tmp_path / 'interactions.sqlite'
    db = CaseInteractionDB(path)
    await db.import_rows('s', [], {})
    await db.set_active('s', 'u', 'a', 'like', False, META)
    assert not await db.pending_sync('s')
    first = await db.set_active('s', 'u', 'a', 'like', True, META)
    [queued] = await db.pending_sync('s')
    assert queued['liked_at'] == first.liked_at and first.liked_at > 10**12
    assert await db.set_active('s', 'u', 'a', 'like', True, META) == first
    assert await db.pending_sync('s') == [queued]
    await db.ack_sync('s', 'a', 'u', queued['revision'])
    await db.set_active('s', 'u', 'a', 'favorite', True, META)
    await db.set_active('s', 'u', 'a', 'like', False, META)
    await db.ack_sync('s', 'a', 'u', queued['revision'])
    [latest] = await CaseInteractionDB(path).pending_sync('s')
    assert not latest['liked'] and latest['liked_at'] is None
    assert latest['favorited'] and latest['favorited_at'] > 10**12
    assert latest['revision'] > queued['revision']
    await db.ack_sync('s', 'a', 'u', latest['revision'])
    assert not await db.pending_sync('s')


async def test_historical_backfill_and_crossings_replay_in_order_per_case(tmp_path):
    db = CaseInteractionDB(tmp_path / 'interactions.sqlite')
    rows = [row(i, case) for case in ['a', 'b', 'hidden'] for i in range(10)]
    cases = {'a': META, 'b': META}
    await db.import_rows('s', rows, cases)
    other_meta = {**META, 'author_id': 'ou_changed'}
    await db.set_active('s', '0', 'a', 'like', False, other_meta)
    await db.set_active('s', '0', 'a', 'like', False, other_meta)
    await db.set_active('s', '0', 'a', 'like', True, other_meta)
    heads = await db.pending_coins()
    assert len(heads) == 2 and {r['case_id'] for r in heads} == {'a', 'b'}
    assert heads == sorted(heads, key=lambda e: e['event_id'])
    assert all((e['likes'], e['favorites'], e['author_id'], e['title']) ==
               (10, 10, 'ou_author', META['title']) for e in heads)
    assert all(e['happened_at'] > 10**12 for e in heads)
    for event in heads:
        await db.ack_coin(event['event_id'])
    for likes in (9, 10):
        [event] = await db.pending_coins()
        assert (event['case_id'], event['likes'], event['favorites'], event['author_id']) == (
            'a', likes, 10, 'ou_changed')
        await db.ack_coin(event['event_id'])
    assert await db.pending_coins() == []


def seed_and_write(path, start):
    async def run():
        db = CaseInteractionDB(path)
        seeded = await db.import_rows('s', [row('old')], {'a': META})
        for i in range(start, start + 5):
            for action in ('like', 'favorite'):
                await db.set_active('s', str(i), 'a', action, True, META)
        return seeded
    return asyncio.run(run())


async def test_independent_processes_cannot_reseed_or_lose_writes(tmp_path):
    path = tmp_path / 'nested' / 'interactions.sqlite'
    with ProcessPoolExecutor(max_workers=3, mp_context=get_context('spawn')) as workers:
        seeds = await asyncio.gather(*(asyncio.get_running_loop().run_in_executor(
            workers, seed_and_write, path, batch * 5) for batch in range(3)))
    assert seeds.count(True) == 1
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    db = CaseInteractionDB(path)
    item = (await db.directory('s', 'old', {'a'}))['a']
    assert (item.like_count, item.favorite_count) == (16, 16)
    assert len(await db.pending_sync('s')) == 15
    thresholds = []
    while events := await db.pending_coins():
        thresholds.append(min(events[0]['likes'], events[0]['favorites']))
        await db.ack_coin(events[0]['event_id'])
    assert thresholds == [5, 10, 15]


async def test_stale_sync_ack_and_cursor_allow_other_accounts_to_progress(tmp_path):
    db = CaseInteractionDB(tmp_path / 'interactions.sqlite')
    await db.import_rows('s', [], {})
    for case, account in [('b', 'z'), ('a', 'x'), ('b', 'a'), ('a', 'y')]:
        await db.set_active('s', account, case, 'like', True, META)
    first = await db.pending_sync('s', limit=1)
    assert [(r['case_id'], r['account']) for r in first] == [('a', 'x')]
    later = await db.pending_sync('s', limit=2, after=('a', 'x'))
    assert [(r['case_id'], r['account']) for r in later] == [('a', 'y'), ('b', 'a')]
    assert await db.pending_sync('s', after=('b', 'z')) == []
    revision = first[0]['revision']
    await db.set_active('s', 'x', 'a', 'favorite', True, META)
    assert await db.ack_sync('s', 'a', 'x', revision) is False
    assert await db.ack_sync('s', 'a', 'x', revision + 1) is True
    assert await db.ack_sync('s', 'a', 'x', revision + 1) is False


async def test_coin_cursor_skips_blocked_case_without_releasing_its_later_event(tmp_path):
    db = CaseInteractionDB(tmp_path / 'interactions.sqlite')
    for scope in ['other', 'prod']:
        await db.import_rows(scope, [row(i, case) for case in ['a', 'b', 'c'] for i in range(5)],
                             {case: META for case in ['a', 'b', 'c']})
    await db.set_active('prod', '0', 'a', 'like', False, META)
    [blocked] = await db.pending_coins(limit=1, scope='prod')
    assert blocked['case_id'] == 'a' and blocked['scope'] == 'prod'
    later = await db.pending_coins(scope='prod', after=blocked['event_id'])
    assert [event['case_id'] for event in later] == ['b', 'c']
    assert await db.pending_coins(scope='prod', after=later[-1]['event_id']) == []
    await db.ack_coin(blocked['event_id'])
    [reversal] = await db.pending_coins(scope='prod', after=later[-1]['event_id'])
    assert (reversal['case_id'], reversal['likes'], reversal['favorites']) == ('a', 4, 5)
