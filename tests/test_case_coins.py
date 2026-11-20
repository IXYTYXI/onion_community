import asyncio
import sqlite3
from contextlib import closing
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr

from app.repositories.case_interactions import CaseInteractionDB
from app.services.case_coins import AMOUNT, AUTHOR, BALANCE, CASE, FAVORITES, KEY, LIKES, NAME, SEQ, WHEN, CaseCoins


async def add_event(db, scope, likes, favorites, author='ou_one', name='甲', case='a'):
    await db.is_initialized(scope)
    with closing(sqlite3.connect(db.path)) as conn, conn:
        conn.execute('''INSERT INTO case_coin_events
                        (scope,case_id,title,author_id,author_name,likes,favorites,happened_at)
                        VALUES(?,?,?,?,?,?,?,?)''',
                     (scope, case, '作品 ' + case, author or '', name, likes, favorites, 1900000000000))


async def drain(worker):
    while await worker.flush():
        pass


class Ledger:
    def __init__(self):
        self.rows = []
        self.attempts = []
        self.unavailable = self.lose_ack = self.lag = False

    async def all_records(self, *, record_filter):
        if self.unavailable:
            raise httpx.ConnectError('unavailable')
        case_id, = record_filter['conditions'][0]['value']
        return [] if self.lag else deepcopy([r for r in self.rows if r['fields'][CASE] == case_id])

    async def create_once(self, fields, token):
        await asyncio.sleep(.002)
        self.attempts.append((deepcopy(fields), token))
        row = next((row for row in self.rows if row['record_id'] == token), None)
        if row is None:
            row = {'record_id': token, 'fields': deepcopy(fields)}
            self.rows.append(row)
        assert row['fields'] == fields
        if self.lose_ack:
            raise httpx.ReadTimeout('response lost')
        return deepcopy(row)


@pytest.fixture
def coins(settings, tmp_path):
    settings.coin_base_token = SecretStr('independent-base')
    settings.coin_table_id = 'ledger'
    settings.cases_table_id = 'source'
    settings.cases_engagement_table_id = 'interactions'
    db = CaseInteractionDB(tmp_path / 'interactions.sqlite3')
    cases = AsyncMock()
    cases.read.return_value = SimpleNamespace(stale=False, items=[])
    ledger = Ledger()

    def worker():
        return CaseCoins(CaseInteractionDB(db.path), ledger, cases, settings)

    return db, ledger, cases, worker


async def test_ordered_sqlite_replay_after_outage_across_blue_green_workers(coins):
    db, ledger, _, worker = coins
    one, two = worker(), worker()
    for likes, favorites, author in [(5, 4, 'ou_one'), (5, 5, 'ou_one'), (10, 10, 'ou_two'),
                                     (9, 10, 'ou_two'), (4, 10, 'ou_two'), (5, 10, 'ou_two')]:
        await add_event(db, one.scope, likes, favorites, author=author)
    ledger.unavailable = True
    assert await one.flush() == 0
    assert len(await db.pending_coins()) == 1  # only the head per case is available
    ledger.unavailable = False
    await asyncio.gather(drain(one), drain(two))
    assert not await db.pending_coins()
    assert not await worker().flush()
    fields = [r['fields'] for r in ledger.rows]
    assert [(r[AMOUNT], r[BALANCE], r[AUTHOR], r[LIKES], r[FAVORITES]) for r in fields] == [
        (2, 2, 'ou_one', 5, 5), (2, 4, 'ou_two', 10, 10), (-2, 2, 'ou_two', 9, 10),
        (-2, 0, 'ou_one', 4, 10), (2, 2, 'ou_two', 5, 10)]
    assert [r[SEQ] for r in fields] == list(range(1, 6))
    assert len({r[KEY] for r in fields}) == len(ledger.attempts) == 5
    assert all(r[WHEN] == 1900000000000 for r in fields)


async def test_ambiguous_first_author_resolution_replays_exact_request_after_restart(coins):
    db, ledger, cases, worker = coins
    service = worker()
    await add_event(db, service.scope, 10, 10, author='', name='')
    cases.read.return_value.items = [SimpleNamespace(id='a', author='甲',
        contact_url='https://applink.feishu.cn/client/chat/open?openId=ou_resolved')]
    ledger.lose_ack = True
    assert await service.flush() == 0
    assert len(ledger.rows) == 1 and len(await db.pending_coins()) == 1
    ledger.lose_ack, ledger.lag = False, True
    cases.read.return_value.items = [SimpleNamespace(id='a', author='乙',
        contact_url='https://applink.feishu.cn/client/chat/open?openId=ou_later')]
    assert await worker().flush() == 1
    assert ledger.attempts[0] == ledger.attempts[1]
    assert not await db.pending_coins()
    assert [r['fields'][AUTHOR] for r in ledger.rows] == ['ou_resolved', 'ou_resolved']


async def test_missing_author_pauses_only_own_case_and_reverses_original_recipient(coins):
    db, ledger, cases, worker = coins
    service = worker()
    await add_event(db, service.scope, 5, 5, author=None, name='')
    await add_event(db, service.scope, 4, 5, author=None, name='')
    await add_event(db, service.scope, 5, 5, case='b')
    assert await service.flush() == 1
    assert [r['fields'][CASE] for r in ledger.rows] == ['b']
    cases.read.return_value.items = [SimpleNamespace(id='a', author='补录作者',
        contact_url='https://applink.feishu.cn/client/chat/open?openId=ou_verified')]
    await drain(worker())
    assert not await db.pending_coins()
    assert [(r['fields'][AMOUNT], r['fields'][AUTHOR], r['fields'][NAME]) for r in ledger.rows[1:]] == [
        (2, 'ou_verified', '补录作者'), (-2, 'ou_verified', '补录作者')]


async def test_stale_ledger_reads_cannot_ack_or_duplicate_the_next_event(coins):
    db, ledger, _, worker = coins
    service = worker()
    await add_event(db, service.scope, 5, 5)
    assert await service.flush() == 1
    await add_event(db, service.scope, 4, 5)
    ledger.lag = True
    assert await worker().flush() == 0
    assert len(await db.pending_coins()) == 1 and len(ledger.attempts) == 1
    ledger.lag = False
    assert await worker().flush() == 1
    assert [r['fields'][AMOUNT] for r in ledger.rows] == [2, -2]


async def test_other_process_holding_coin_lock_does_not_lock_sqlite_writes(coins):
    import subprocess
    import sys

    db, ledger, _, worker = coins
    service = worker()
    await add_event(db, service.scope, 5, 5)
    lock_path = db.path.with_name(db.path.name + '.coins.lock')
    script = """import fcntl, sys
with open(sys.argv[1], 'a+b') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    print('locked', flush=True)
    sys.stdin.readline()
"""
    with subprocess.Popen([sys.executable, '-c', script, str(lock_path)], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, text=True) as process:
        try:
            assert process.stdout.readline().strip() == 'locked'
            assert await service.flush() == 0
            await add_event(db, service.scope, 4, 5)
            assert len(await db.pending_coins()) == 1 and not ledger.rows
        finally:
            process.communicate(input='release\n', timeout=5)
    await drain(service)
    assert not await db.pending_coins()
    assert [r['fields'][AMOUNT] for r in ledger.rows] == [2, -2]


async def test_sqlite_import_and_live_changes_flow_through_actual_transaction_outbox(coins):
    db, ledger, _, worker = coins
    service = worker()
    meta = {'title': '历史作品', 'author_id': 'ou_author', 'author_name': '作者'}
    rows = [{'case_id': 'old', 'account': str(i), 'liked': True, 'favorited': True,
             'liked_at': 1650000000000, 'favorited_at': 1650000000000} for i in range(5)]
    assert await db.import_rows(service.scope, rows, {'old': meta})
    ledger.unavailable = True
    assert await db.set_active(service.scope, '4', 'old', 'favorite', False, meta)
    await db.set_active(service.scope, '4', 'old', 'favorite', False, meta)
    await db.set_active(service.scope, '4', 'old', 'favorite', True, meta)
    assert await service.flush() == 0
    ledger.unavailable = False
    await drain(worker())
    assert [(r['fields'][AMOUNT], r['fields'][BALANCE]) for r in ledger.rows] == [(2, 2), (-2, 0), (2, 2)]
    assert not await db.pending_coins()


async def test_scope_and_cursor_skip_blocked_page_then_retry_repaired_case(coins):
    db, ledger, cases, worker = coins
    service = worker()
    await add_event(db, 'unrelated-scope', 5, 5, case='other')
    for index in range(100):
        await add_event(db, service.scope, 5, 5, author='', case=f'blocked-{index}')
    await add_event(db, service.scope, 4, 5, case='blocked-0')
    await add_event(db, service.scope, 5, 5, case='eligible')
    assert await service.flush() == 0
    assert await service.flush() == 1
    assert [row['fields'][CASE] for row in ledger.rows] == ['eligible']
    cases.read.return_value.items = [SimpleNamespace(id='blocked-0', author='补录',
        contact_url='https://applink.feishu.cn/client/chat/open?openId=ou_verified')]
    assert await service.flush() == 1
    assert await service.flush() == 1
    assert [(row['fields'][CASE], row['fields'][AMOUNT]) for row in ledger.rows] == [
        ('eligible', 2), ('blocked-0', 2), ('blocked-0', -2)]
    assert len(await db.pending_coins(scope='unrelated-scope')) == 1


async def test_feishu_number_read_and_create_ack_support_integral_floats(coins):
    db, ledger, _, worker = coins
    service = worker()
    create = ledger.create_once

    async def float_ack(fields, token):
        record = await create(fields, token)
        for key in (SEQ, AMOUNT, BALANCE, LIKES, FAVORITES):
            ledger.rows[-1]['fields'][key] = record['fields'][key] = float(fields[key])
        return record

    ledger.create_once = float_ack
    await add_event(db, service.scope, 5, 5)
    await add_event(db, service.scope, 4, 5)
    await drain(service)
    assert not await db.pending_coins()
    assert [r['fields'][AMOUNT] for r in ledger.rows] == [2.0, -2.0]


@pytest.mark.parametrize(('source', 'overrides', 'expected'), [
    ('tbldtSGzcfa6twD0', {}, ('OyLfbjbNnah8bCsrmHEc18aSn3c', 'tblTlqxQN2L9QI90')),
    ('tbldtSGzcfa6twD0', {'coin_base_token': '', 'coin_table_id': ''},
     ('OyLfbjbNnah8bCsrmHEc18aSn3c', 'tblTlqxQN2L9QI90')),
    ('tbldtSGzcfa6twD0', {'coin_base_token': 'custom-base', 'coin_table_id': 'custom-table'},
     ('custom-base', 'custom-table')),
    ('tbldtSGzcfa6twD0', {'coin_table_id': 'table-only'}, ('', 'table-only')),
    ('tbldtSGzcfa6twD0', {'coin_base_token': 'base-only'}, ('base-only', '')),
    ('tbldtSGzcfa6twD0', {'coin_base_token': ''}, ('', '')),
    ('tbldtSGzcfa6twD0', {'cases_engagement_table_id': 'other-interactions'}, ('', '')),
    ('unrelated-source', {}, ('', '')),
])
def test_default_coin_destination_requires_matching_source_and_paired_configuration(source, overrides, expected):
    from app.core.config import Settings
    settings = Settings(_env_file=None, news_sync_enabled=False, cases_table_id=source, **overrides)
    assert (settings.coin_base_token.get_secret_value(), settings.coin_table_id) == expected


async def test_91403_pauses_whole_ledger_across_restart_and_recovers(coins, monkeypatch):
    from app.integrations.bitable_writer import BitableWriter
    from app.services import case_coins

    db, ledger, _, worker = coins
    one = worker()
    for case in ('a', 'b', 'c'):
        await add_event(db, one.scope, 5, 5, case=case)
    clock = [1200]
    monkeypatch.setattr(case_coins, 'time', lambda: clock[0])
    create = ledger.create_once
    calls = []

    async def forbidden(fields, token):
        calls.append((fields, token))
        return BitableWriter.payload(httpx.Response(200, json={'code': 91403, 'msg': 'Forbidden'}))

    ledger.create_once = forbidden
    assert await one.flush() == 0 and len(calls) == 1
    assert len(await db.pending_coins()) == 3
    clock[0] += 55
    assert await worker().flush() == 0 and len(calls) == 1
    clock[0] += 5
    assert await worker().flush() == 0 and len(calls) == 2
    assert calls[0] == calls[1]
    clock[0] += 110
    ledger.create_once = create
    assert await one.flush() == 0
    clock[0] += 10
    assert await worker().flush() == 3
    assert not await db.pending_coins()
    assert {r['fields'][CASE] for r in ledger.rows} == {'a', 'b', 'c'}
    assert worker().permission_backoff()[0] == 0

async def test_paused_ledger_keeps_milestones_and_replays_in_order(coins):
    from app.services.site_settings import Switches
    db, ledger, _, worker = coins
    service = worker()
    service.site = AsyncMock()
    service.site.current.return_value = Switches(True, False, "01")
    for likes, favorites in [(5, 5), (4, 5), (5, 5)]:
        await add_event(db, service.scope, likes, favorites)
    assert await service.flush() == 0
    assert not ledger.rows
    assert await db.pending_coins()
    service.site.current.return_value = Switches(True, True, "01")
    await drain(service)
    assert [row["fields"][AMOUNT] for row in ledger.rows] == [2, -2, 2]
    assert not await db.pending_coins()
