"""SQLite source of truth for case interactions and their two delivery queues."""
import asyncio
import logging
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from app.core.error_codes import ErrorCode
from app.core.errors import AppError
from app.schemas.cases import CaseEngagement

SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS case_scopes (
        scope TEXT PRIMARY KEY NOT NULL
    ) WITHOUT ROWID''',
    '''CREATE TABLE IF NOT EXISTS case_interactions (
        scope TEXT NOT NULL, case_id TEXT NOT NULL, account TEXT NOT NULL,
        liked INTEGER NOT NULL, favorited INTEGER NOT NULL, liked_at INTEGER, favorited_at INTEGER,
        revision INTEGER NOT NULL DEFAULT 0, sync_pending INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(scope, case_id, account)
    ) WITHOUT ROWID''',
    '''CREATE INDEX IF NOT EXISTS case_sync_due ON case_interactions(scope, case_id, account)
       WHERE sync_pending = 1''',
    '''CREATE TABLE IF NOT EXISTS case_totals (
        scope TEXT NOT NULL, case_id TEXT NOT NULL, likes INTEGER NOT NULL, favorites INTEGER NOT NULL,
        PRIMARY KEY(scope, case_id)
    ) WITHOUT ROWID''',
    '''CREATE TABLE IF NOT EXISTS case_coin_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT NOT NULL, case_id TEXT NOT NULL,
        title TEXT NOT NULL, author_id TEXT NOT NULL, author_name TEXT NOT NULL,
        likes INTEGER NOT NULL, favorites INTEGER NOT NULL, happened_at INTEGER NOT NULL
    )''',
    '''CREATE INDEX IF NOT EXISTS case_coin_order ON case_coin_events(scope, case_id, event_id)''',
)

IMPORT_INTERACTION = '''
    INSERT INTO case_interactions(scope, case_id, account, liked, favorited, liked_at, favorited_at)
    VALUES(?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(scope, case_id, account) DO UPDATE SET
      liked = MAX(liked, excluded.liked), favorited = MAX(favorited, excluded.favorited),
      liked_at = NULLIF(MAX(COALESCE(liked_at, 0), COALESCE(excluded.liked_at, 0)), 0),
      favorited_at = NULLIF(MAX(COALESCE(favorited_at, 0), COALESCE(excluded.favorited_at, 0)), 0)
'''


def _schema(conn):
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='case_scopes' AND type='table'").fetchone():
        return
    # Concurrent first opens can get SQLITE_BUSY immediately on the journal mode switch.
    deadline = time.monotonic() + 5
    while True:
        try:
            if conn.execute('PRAGMA journal_mode=WAL').fetchone()[0] != 'wal':
                raise sqlite3.OperationalError('WAL mode unavailable')
            break
        except sqlite3.OperationalError as exc:
            if getattr(exc, 'sqlite_errorcode', 0) & 255 != sqlite3.SQLITE_BUSY or time.monotonic() >= deadline:
                raise
            time.sleep(.025)
    conn.execute('BEGIN IMMEDIATE')
    for statement in SCHEMA:
        conn.execute(statement)
    conn.commit()


def _initialized(conn, scope):
    return conn.execute('SELECT 1 FROM case_scopes WHERE scope=?', (scope,)).fetchone() is not None


def _require_import(conn, scope):
    if not _initialized(conn, scope):
        raise AppError(ErrorCode.SNAPSHOT_NOT_READY)


def _read_items(conn, scope, account, visible):
    items = {case_id: CaseEngagement() for case_id in visible}
    cases = list(items)
    # Bound the number of parameters for SQLite builds with the older 999-variable limit.
    for start in range(0, len(cases), 500):
        batch = cases[start:start + 500]
        placeholders = ','.join('?' for _ in batch)
        rows = conn.execute(f'''SELECT t.case_id, t.likes, t.favorites, i.liked, i.favorited,
                                       i.liked_at, i.favorited_at
                                FROM case_totals AS t LEFT JOIN case_interactions AS i
                                  ON i.scope=t.scope AND i.case_id=t.case_id AND i.account=?
                                WHERE t.scope=? AND t.case_id IN ({placeholders})''', (account, scope, *batch))
        for row in rows:
            items[row['case_id']] = CaseEngagement(
                like_count=row['likes'], favorite_count=row['favorites'], liked=bool(row['liked']),
                favorited=bool(row['favorited']), liked_at=row['liked_at'], favorited_at=row['favorited_at'])
    return items


def _coin_event(conn, scope, case_id, meta, likes, favorites, happened_at):
    conn.execute('''INSERT INTO case_coin_events
                    (scope, case_id, title, author_id, author_name, likes, favorites, happened_at)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?)''',
                 (scope, case_id, meta.get('title') or '', meta.get('author_id') or '',
                  meta.get('author_name') or '', likes, favorites, happened_at))


class CaseInteractionDB:
    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()

    def _transaction(self, operation, args, write):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # The connection timeout sets SQLite's busy timeout for each independent worker.
            with closing(sqlite3.connect(self.path, timeout=5, isolation_level=None)) as conn:
                conn.row_factory = sqlite3.Row
                _schema(conn)
                conn.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
                result = operation(conn, *args)
                conn.commit()
                return result
        except (OSError, sqlite3.Error) as exc:
            logging.getLogger('ows_community').warning('case_interaction_db_unavailable', exc_info=True)
            raise AppError(ErrorCode.SERVICE_UNAVAILABLE) from exc

    async def _run(self, operation, *args, write=False):
        return await asyncio.to_thread(self._transaction, operation, args, write)

    async def is_initialized(self, scope):
        return await self._run(_initialized, scope)

    async def import_rows(self, scope, rows, cases):
        def seed(conn):
            if _initialized(conn, scope):
                return False
            conn.executemany(IMPORT_INTERACTION, (
                (scope, row['case_id'], row['account'], row['liked'], row['favorited'],
                 row['liked_at'] if row['liked'] else None, row['favorited_at'] if row['favorited'] else None)
                for row in rows))
            conn.execute('''INSERT INTO case_totals(scope, case_id, likes, favorites)
                            SELECT scope, case_id, SUM(liked), SUM(favorited) FROM case_interactions
                            WHERE scope=? GROUP BY scope, case_id''', (scope,))
            now = time.time_ns() // 1_000_000
            for case_id, likes, favorites in conn.execute(
                    'SELECT case_id, likes, favorites FROM case_totals WHERE scope=? AND likes>=5 AND favorites>=5',
                    (scope,)):
                if case_id in cases:
                    _coin_event(conn, scope, case_id, cases[case_id], likes, favorites, now)
            conn.execute('INSERT INTO case_scopes(scope) VALUES(?)', (scope,))
            return True
        return await self._run(seed, write=True)

    async def directory(self, scope, account, visible):
        def read(conn):
            _require_import(conn, scope)
            return _read_items(conn, scope, account, visible)
        return await self._run(read)

    async def set_active(self, scope, account, case_id, action, active, meta):
        def apply(conn):
            _require_import(conn, scope)
            before = _read_items(conn, scope, account, [case_id])[case_id]
            if action == 'like':
                flag, date, count = 'liked', 'liked_at', 'like_count'
            elif action == 'favorite':
                flag, date, count = 'favorited', 'favorited_at', 'favorite_count'
            else:
                raise ValueError('Unknown case interaction action')
            if getattr(before, flag) == active:
                return before
            now = time.time_ns() // 1_000_000
            after = before.model_copy(update={flag: active, date: now if active else None,
                                              count: getattr(before, count) + (1 if active else -1)})
            # Revision stays on the source row after delivery, protecting later edits from stale ACKs.
            conn.execute('''INSERT INTO case_interactions
                            (scope, case_id, account, liked, favorited, liked_at, favorited_at, revision, sync_pending)
                            VALUES(?, ?, ?, ?, ?, ?, ?, 1, 1)
                            ON CONFLICT(scope, case_id, account) DO UPDATE SET
                              liked=excluded.liked, favorited=excluded.favorited, liked_at=excluded.liked_at,
                              favorited_at=excluded.favorited_at, revision=revision+1, sync_pending=1''',
                         (scope, case_id, account, after.liked, after.favorited, after.liked_at, after.favorited_at))
            conn.execute('''INSERT INTO case_totals(scope, case_id, likes, favorites) VALUES(?, ?, ?, ?)
                            ON CONFLICT(scope, case_id) DO UPDATE SET likes=excluded.likes,
                                                                     favorites=excluded.favorites''',
                         (scope, case_id, after.like_count, after.favorite_count))
            if min(before.like_count, before.favorite_count) // 5 != min(after.like_count, after.favorite_count) // 5:
                _coin_event(conn, scope, case_id, meta, after.like_count, after.favorite_count, now)
            return after
        return await self._run(apply, write=True)

    async def pending_sync(self, scope, limit=50, after=None):
        def read(conn):
            _require_import(conn, scope)
            cursor = ' AND (case_id, account) > (?, ?)' if after is not None else ''
            params = (scope, *after, limit) if after is not None else (scope, limit)
            rows = conn.execute(f'''SELECT case_id, account, liked, favorited, liked_at, favorited_at, revision
                                   FROM case_interactions WHERE scope=? AND sync_pending=1
                                   {cursor} ORDER BY case_id, account LIMIT ?''', params)
            return [{**dict(row), 'liked': bool(row['liked']), 'favorited': bool(row['favorited'])} for row in rows]
        return await self._run(read)

    async def ack_sync(self, scope, case_id, account, revision):
        def ack(conn):
            _require_import(conn, scope)
            updated = conn.execute('''UPDATE case_interactions SET sync_pending=0
                                      WHERE scope=? AND case_id=? AND account=? AND revision=? AND sync_pending=1''',
                                   (scope, case_id, account, revision))
            return updated.rowcount == 1
        return await self._run(ack, write=True)

    async def pending_coins(self, limit=100, *, scope=None, after=None):
        def read(conn):
            scope_filter = ' AND e.scope=?' if scope is not None else ''
            params = (after or 0, scope, limit) if scope is not None else (after or 0, limit)
            # Only constrain the outer query. An earlier undelivered event outside this page
            # must still prevent delivery of a later event for the same case.
            rows = conn.execute(f'''SELECT e.* FROM case_coin_events AS e
                                   WHERE e.event_id>? {scope_filter} AND NOT EXISTS (
                                     SELECT 1 FROM case_coin_events AS prior
                                     WHERE prior.scope=e.scope AND prior.case_id=e.case_id AND prior.event_id<e.event_id
                                   ) ORDER BY e.event_id LIMIT ?''', params)
            return [dict(row) for row in rows]
        return await self._run(read)

    async def ack_coin(self, event_id):
        def ack(conn):
            conn.execute('DELETE FROM case_coin_events WHERE event_id=?', (event_id,))
        await self._run(ack, write=True)
