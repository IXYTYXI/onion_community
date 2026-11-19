"""Replay committed SQLite case milestones into an append-only Feishu coin ledger."""
import asyncio
import fcntl
import hashlib
import json
import logging
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from time import time
from uuid import UUID

from app.integrations.bitable_writer import BitablePermissionError
from app.services.officers import text_value

KEY, CASE, TITLE, AUTHOR, NAME = '流水号', '案例ID', '案例名称', '作者标识', '作者姓名'
AMOUNT, BALANCE, LIKES, FAVORITES, WHEN, SEQ = (
    '变动币数', '结算后案例币数', '有效点赞数', '有效收藏数', '结算时间', '结算序号')
COIN_FIELDS = [KEY, CASE, TITLE, AUTHOR, NAME, AMOUNT, BALANCE, LIKES, FAVORITES, WHEN, SEQ]
PAGE_SIZE = 100
LOGGER = logging.getLogger('ows_community')
OPEN_ID = re.compile(r'ou_[A-Za-z0-9_]{1,128}')
CONTACT = re.compile(r'https://applink\.feishu\.cn/client/chat/open\?openId=(ou_[A-Za-z0-9_]{1,128})')


def ledger_integer(fields, key):
    value = fields.get(key)
    if type(value) is int or type(value) is float and value.is_integer():
        return int(value)
    raise ValueError('Invalid integer in case coin ledger')


def recipient(case):
    match = CONTACT.fullmatch(case.contact_url or '')
    return (match.group(1), case.author) if match else ('', '')


def digest(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


class CaseCoins:
    def __init__(self, db, writer, cases, settings):
        self.db, self.writer, self.cases = db, writer, cases
        self.path = Path(db.path)
        self.after = None
        self.scope = digest('case-engagement/v1', settings.feishu_app_id,
                            settings.feishu_bitable_app_token.get_secret_value(), settings.cases_table_id)
        self.namespace = digest(self.scope, settings.cases_engagement_table_id,
                                settings.coin_base_token.get_secret_value(), settings.coin_table_id)

    def progress(self, case_id, checkpoint=None, prepared=None):
        # Short local transactions only. Never retain a SQLite transaction across a network call.
        with closing(sqlite3.connect(self.path, timeout=5)) as conn, conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS case_coin_progress (
                namespace TEXT NOT NULL, case_id TEXT NOT NULL, checkpoint INTEGER NOT NULL,
                prepared TEXT, PRIMARY KEY(namespace, case_id))''')
            if checkpoint is None:
                row = conn.execute('SELECT checkpoint, prepared FROM case_coin_progress '
                                   'WHERE namespace=? AND case_id=?', (self.namespace, case_id)).fetchone()
                return (row[0], json.loads(row[1]) if row[1] else None) if row else (0, None)
            conn.execute('''INSERT INTO case_coin_progress(namespace, case_id, checkpoint, prepared)
                VALUES(?, ?, ?, ?) ON CONFLICT(namespace, case_id) DO UPDATE SET
                checkpoint=excluded.checkpoint, prepared=excluded.prepared''',
                         (self.namespace, case_id, checkpoint, json.dumps(prepared, ensure_ascii=False)
                          if prepared else None))

    def permission_backoff(self, delay=None):
        # Persist across service restarts and blue/green workers. A denial applies to the
        # app and ledger as a whole, so the next probe should send just one request.
        with closing(sqlite3.connect(self.path, timeout=5)) as conn, conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS case_coin_backoff (
                namespace TEXT PRIMARY KEY, delay INTEGER NOT NULL, retry_at REAL NOT NULL)''')
            if delay is None:
                row = conn.execute('SELECT delay, retry_at FROM case_coin_backoff WHERE namespace=?',
                                   (self.namespace,)).fetchone()
                return row or (0, 0)
            conn.execute('INSERT OR REPLACE INTO case_coin_backoff(namespace, delay, retry_at) VALUES(?, ?, ?)',
                         (self.namespace, delay, time() + delay))

    def operation(self, case_id, seq):
        return digest('case-coins/v1', self.namespace, case_id, seq)

    async def history(self, case_id):
        filters = {'conjunction': 'and', 'conditions': [
            {'field_name': CASE, 'operator': 'is', 'value': [case_id]}]}
        records = await self.writer.all_records(record_filter=filters)
        rows = [r['fields'] for r in records if text_value(r['fields'].get(CASE)) == case_id]
        rows.sort(key=lambda r: ledger_integer(r, SEQ))
        credits = []
        for seq, fields in enumerate(rows, 1):
            author = text_value(fields.get(AUTHOR))
            if (ledger_integer(fields, SEQ) != seq or text_value(fields.get(KEY)) != self.operation(case_id, seq)
                    or not OPEN_ID.fullmatch(author)):
                raise ValueError('Invalid case coin ledger sequence or recipient')
            amount = ledger_integer(fields, AMOUNT)
            if amount == 2:
                credits.append((author, text_value(fields.get(NAME))))
            elif amount == -2 and credits and credits[-1][0] == author:
                credits.pop()
            else:
                raise ValueError('Invalid case coin reversal')
            if ledger_integer(fields, BALANCE) != len(credits) * 2:
                raise ValueError('Invalid case coin ledger balance')
        return len(rows), credits

    async def first_author(self, event):
        author = event['author_id'] or ''
        if OPEN_ID.fullmatch(author):
            return author, event['author_name'] or ''
        directory = await self.cases.read()
        if not directory.stale:
            for item in directory.items:
                if item.id == event['case_id']:
                    return recipient(item)
        return '', ''

    async def settle(self, event):
        case_id = event['case_id']
        seq, credits = await self.history(case_id)
        checkpoint, prepared = await asyncio.to_thread(self.progress, case_id)
        if seq < checkpoint:
            return False  # Search has not caught up with an acknowledged create.
        target = 2 * (min(event['likes'], event['favorites']) // 5)
        while len(credits) * 2 != target:
            if prepared and prepared['fields'][SEQ] > seq:
                if prepared['event_id'] != event['event_id'] or prepared['fields'][SEQ] != seq + 1:
                    raise ValueError('Pending entry does not match the SQLite outbox head')
                fields = prepared['fields']
            else:
                balance = len(credits) * 2
                amount = 2 if balance < target else -2
                if amount < 0:
                    author, name = credits[-1]
                elif prepared and prepared['event_id'] == event['event_id']:
                    author, name = prepared['fields'][AUTHOR], prepared['fields'][NAME]
                else:
                    author, name = await self.first_author(event)
                if not author:
                    LOGGER.warning('case_coin_first_author_missing', extra={'case_id': case_id})
                    return False
                fields = {KEY: self.operation(case_id, seq + 1), CASE: case_id, TITLE: event['title'],
                          AUTHOR: author, NAME: name, AMOUNT: amount, BALANCE: balance + amount,
                          LIKES: event['likes'], FAVORITES: event['favorites'],
                          WHEN: event['happened_at'], SEQ: seq + 1}
                prepared = {'event_id': event['event_id'], 'fields': fields}
                # Freeze the resolved author and exact request before a potentially ambiguous create.
                await asyncio.to_thread(self.progress, case_id, seq, prepared)
            key = fields[KEY]
            record = await self.writer.create_once(fields, str(UUID(hex=key[:32], version=4)))
            ack = record.get('fields', {})
            if (not record.get('record_id') or text_value(ack.get(KEY)) != key
                    or text_value(ack.get(AUTHOR)) != fields[AUTHOR] or ledger_integer(ack, AMOUNT) != fields[AMOUNT]
                    or ledger_integer(ack, BALANCE) != fields[BALANCE] or ledger_integer(ack, SEQ) != fields[SEQ]):
                raise ValueError('Incomplete case coin acknowledgement')
            if fields[AMOUNT] > 0:
                credits.append((fields[AUTHOR], fields[NAME]))
            else:
                credits.pop()
            seq += 1
            await asyncio.to_thread(self.progress, case_id, seq, prepared)
        # Remember newly visible rows after lost acknowledgements. A crash here
        # will simply replay this same event against the confirmed ledger balance.
        await asyncio.to_thread(self.progress, case_id, seq)
        await self.db.ack_coin(event['event_id'])
        return True

    async def flush(self):
        # Blue/green processes share this inode with their on-disk database.
        # The kernel drops the lock immediately when a worker exits or crashes.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_name(self.path.name + '.coins.lock').open('a+b') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return 0
            events = await self.db.pending_coins(PAGE_SIZE, scope=self.scope, after=self.after)
            if not events and self.after is not None:
                events = await self.db.pending_coins(PAGE_SIZE, scope=self.scope)
            if not events:
                self.after = None
                return 0
            delay, retry_at = await asyncio.to_thread(self.permission_backoff)
            if retry_at > time():
                return 0
            # Move past failed heads and revisit them on the next pass around the queue.
            # SQLite only returns the earliest undelivered event for each case.
            self.after = events[-1]['event_id'] if len(events) == PAGE_SIZE else None
            completed = 0
            for event in events:
                try:
                    async with asyncio.timeout(125):
                        if await self.settle(event):
                            completed += 1
                except BitablePermissionError as exc:
                    delay = min(1800, max(60, delay * 2))
                    await asyncio.to_thread(self.permission_backoff, delay)
                    LOGGER.warning('case_coin_permission_denied retry_in_seconds=%d', delay,
                                   extra={'upstream_code': exc.upstream_code})
                    return completed
                except Exception as exc:
                    LOGGER.warning('case_coin_delivery_deferred', extra={
                        'case_id': event['case_id'], 'exception_type': type(exc).__name__})
            if completed and delay:
                await asyncio.to_thread(self.permission_backoff, 0)
            return completed

    async def run(self):
        while True:
            try:
                if await self.flush():
                    await asyncio.sleep(0)
                    continue
            except Exception as exc:
                LOGGER.warning('case_coin_outbox_unavailable', extra={'exception_type': type(exc).__name__})
            await asyncio.sleep(10)
