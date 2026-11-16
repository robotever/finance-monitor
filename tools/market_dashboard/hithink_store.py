"""Private normalized SQLite boundary. Never opens the provider DuckDB.

Callers share ``store_write_lock(state_root)`` across live and backfill work,
holding it only for short write batches. No provider envelope is accepted here.
Dates and timestamps arrive normalized from the provider boundary.
"""
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
import fcntl
import math
import os
from pathlib import Path
import sqlite3
import stat


CATALOG_VERSION = 'sector-universe-ths-v1'
MEMBERSHIP_VERSION = 'sector-membership-ths-v1'
FEATURE_VERSION = 'sector-features-ths-v1'
BUSY_TIMEOUT_MS = 5000
MAX_READ_ROWS = 10000


def _safe_path(path):
    path = Path(path).absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError('UNSAFE_STORE_PATH')
    return path


def _private_directory(path):
    path = _safe_path(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def _private_file(path):
    path = _safe_path(path)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode) or os.fstat(fd).st_nlink != 1:
            raise ValueError('UNSAFE_STORE_PATH')
        os.fchmod(fd, 0o600)
    except BaseException:
        os.close(fd)
        raise
    return fd


def open_store(path: Path) -> sqlite3.Connection:
    """Open a private WAL database with explicit transaction ownership."""
    path = _safe_path(path)
    _private_directory(path.parent)
    for suffix in ('-wal', '-shm', '-journal'):
        sidecar = _safe_path(Path(str(path) + suffix))
        if sidecar.exists():
            os.close(_private_file(sidecar))
    os.close(_private_file(path))
    connection = sqlite3.connect(path, isolation_level=None, timeout=BUSY_TIMEOUT_MS / 1000)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute(f'PRAGMA busy_timeout={BUSY_TIMEOUT_MS}')
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('PRAGMA journal_mode=WAL')
    except BaseException:
        connection.close()
        raise
    return connection


@contextmanager
def store_write_lock(state_root: Path):
    """One fail-fast advisory lock for every private-store writer; never unlink it."""
    root = _private_directory(state_root)
    fd = _private_file(root / 'sector-history.lock')
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('STORE_BUSY') from None
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


@contextmanager
def _transaction(connection):
    if connection.in_transaction:
        raise ValueError('STORE_TRANSACTION_ACTIVE')
    connection.execute('BEGIN IMMEDIATE')
    try:
        yield
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def migrate_store(connection):
    """Atomically apply the bundled schema once; reject unknown future versions."""
    if connection.in_transaction:
        raise ValueError('STORE_TRANSACTION_ACTIVE')
    version = connection.execute('PRAGMA user_version').fetchone()[0]
    if version == 1:
        return
    if version != 0:
        raise ValueError('UNSUPPORTED_STORE_VERSION')
    script = (Path(__file__).parent / 'sqlite' / '0001_hithink_sector_history.sql').read_text()
    try:
        connection.executescript('BEGIN IMMEDIATE;\n' + script + '\nPRAGMA user_version=1;\nCOMMIT;')
    except BaseException:
        connection.rollback()
        raise


def _mapping(row):
    if is_dataclass(row) and not isinstance(row, type):
        row = asdict(row)
    if not isinstance(row, Mapping):
        raise ValueError('INVALID_STORE_ROW')
    row = dict(row)
    if any(not isinstance(value, (str, int, float, type(None)))
           or isinstance(value, bool)
           or (isinstance(value, float) and not math.isfinite(value))
           for value in row.values()):
        raise ValueError('INVALID_STORE_ROW')
    return row


def _upsert(connection, table, rows):
    # Table names come exclusively from module constants, never caller input.
    columns = {r['name'] for r in connection.execute(f'PRAGMA table_info({table})')}
    keys = [r['name'] for r in connection.execute(f'PRAGMA table_info({table})') if r['pk']]
    for row in rows:
        row = _mapping(row)
        if not row or not row.keys() <= columns:
            raise ValueError('INVALID_STORE_ROW')
        names = list(row)
        updates = [name for name in names if name not in keys]
        conflict = ('DO UPDATE SET ' + ','.join(f'{name}=excluded.{name}' for name in updates)
                    if updates else 'DO NOTHING')
        connection.execute(f'INSERT INTO {table} ({",".join(names)}) VALUES ({",".join("?" for _ in names)}) '
                           f'ON CONFLICT ({",".join(keys)}) {conflict}', list(row.values()))


def replace_catalog(connection, rows, *, catalog_version=CATALOG_VERSION, observed_at_ms,
                    valid_from=None):
    """Replace one catalog version atomically; referenced removals fail closed."""
    with _transaction(connection):
        retained = []
        for record in rows:
            row = _mapping(record)
            identity = row.pop('code', row.get('sector_id'))
            row.update(sector_id=identity, catalog_version=catalog_version,
                       observed_at_ms=observed_at_ms, valid_from=valid_from)
            _upsert(connection, 'sector_catalog', [row])
            retained.append(identity)
        # Avoid SQL variable limits even for large catalogs.
        for old in connection.execute('SELECT sector_id FROM sector_catalog WHERE catalog_version=?', (catalog_version,)).fetchall():
            if old['sector_id'] not in retained:
                connection.execute('DELETE FROM sector_catalog WHERE catalog_version=? AND sector_id=?',
                                   (catalog_version, old['sector_id']))


def upsert_memberships(connection, rows, *, membership_date, catalog_version=CATALOG_VERSION,
                       membership_version=MEMBERSHIP_VERSION):
    with _transaction(connection):
        for record in rows:
            row = _mapping(record)
            row['sector_id'] = row.pop('sector_code', row.get('sector_id'))
            row['stock_id'] = row.pop('stock_code', row.get('stock_id'))
            row.update(membership_date=membership_date, catalog_version=catalog_version,
                       membership_version=membership_version)
            _upsert(connection, 'sector_membership_snapshot', [row])


def upsert_index_daily(connection, rows, *, catalog_version=CATALOG_VERSION, observed_at_ms=None):
    with _transaction(connection):
        for record in rows:
            row = _mapping(record)
            row['sector_id'] = row.pop('code', row.get('sector_id'))
            row['market_date'] = row.pop('date', row.get('market_date'))
            row.update(catalog_version=catalog_version, observed_at_ms=observed_at_ms)
            _upsert(connection, 'sector_index_daily', [row])


def upsert_sector_features(connection, rows, *, intraday=False, feature_version=FEATURE_VERSION,
                           catalog_version=CATALOG_VERSION, membership_version=MEMBERSHIP_VERSION):
    table = 'sector_features_intraday' if intraday else 'sector_features_daily'
    with _transaction(connection):
        for record in rows:
            row = _mapping(record)
            row.update(feature_version=feature_version, catalog_version=catalog_version,
                       membership_version=membership_version)
            _upsert(connection, table, [row])


def _read(connection, table, where, params, order, limit):
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_READ_ROWS:
        raise ValueError('INVALID_STORE_READ')
    return [dict(row) for row in connection.execute(
        f'SELECT * FROM {table} WHERE {where} ORDER BY {order} LIMIT ?', (*params, limit))]


def read_catalog(connection, *, catalog_version=CATALOG_VERSION, limit=1000):
    return _read(connection, 'sector_catalog', 'catalog_version=?', (catalog_version,), 'sector_id', limit)


def read_memberships(connection, sector_id, membership_date, *, limit=10000):
    return _read(connection, 'sector_membership_snapshot', 'sector_id=? AND membership_date=?',
                 (sector_id, membership_date), 'stock_id', limit)


def read_index_daily(connection, sector_id, start, end, *, limit=2000):
    if start > end:
        raise ValueError('INVALID_STORE_READ')
    return _read(connection, 'sector_index_daily', 'sector_id=? AND market_date BETWEEN ? AND ?',
                 (sector_id, start, end), 'market_date', limit)


def read_sector_features(connection, sector_id, start, end, *, intraday=False,
                         feature_version=FEATURE_VERSION, limit=2000):
    if start > end:
        raise ValueError('INVALID_STORE_READ')
    table = 'sector_features_intraday' if intraday else 'sector_features_daily'
    time = 'observed_at' if intraday else 'market_date'
    return _read(connection, table, f'sector_id=? AND feature_version=? AND {time} BETWEEN ? AND ?',
                 (sector_id, feature_version, start, end), time, limit)
