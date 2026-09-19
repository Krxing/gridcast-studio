import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env')
DATA = Path(os.environ.get('APP_DATA_DIR', str(ROOT / '.data'))).resolve()
for directory in [DATA, DATA / 'datasets', DATA / 'models']:
    directory.mkdir(parents=True, exist_ok=True)


def now():
    return datetime.now(UTC).isoformat()


def uid():
    return uuid.uuid4().hex[:16]


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


@contextmanager
def connection():
    database = sqlite3.connect(DATA / 'gridcast.db', timeout=30)
    database.row_factory = sqlite3.Row
    database.execute('PRAGMA foreign_keys=ON')
    try:
        yield database
        database.commit()
    except Exception:
        database.rollback()
        raise
    finally:
        database.close()


def initialize():
    with connection() as database:
        database.execute('PRAGMA journal_mode=WAL')
        database.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL, role TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS datasets (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, scene TEXT NOT NULL,
            is_demo INTEGER NOT NULL, version INTEGER NOT NULL, rows INTEGER NOT NULL,
            interval_minutes INTEGER NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL,
            path TEXT NOT NULL, quality TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS models (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
            dataset_id TEXT NOT NULL REFERENCES datasets(id), dataset_version INTEGER NOT NULL,
            status TEXT NOT NULL, horizon INTEGER NOT NULL, params TEXT NOT NULL,
            metrics TEXT NOT NULL, artifact TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL,
            progress INTEGER NOT NULL, payload TEXT NOT NULL, result TEXT,
            logs TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS forecasts (
            id TEXT PRIMARY KEY, model_id TEXT NOT NULL REFERENCES models(id),
            dataset_id TEXT NOT NULL REFERENCES datasets(id), dataset_version INTEGER NOT NULL,
            mode TEXT NOT NULL, confidence REAL NOT NULL, origin TEXT NOT NULL,
            result TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY, level TEXT NOT NULL, title TEXT NOT NULL,
            detail TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(status, created_at);
        CREATE INDEX IF NOT EXISTS forecasts_dataset ON forecasts(dataset_id, created_at);
        ''')
        defaults = {'learning': {'enabled': False, 'auto_forecast': False, 'minimum_points': 48,
                                'cooldown_hours': 24, 'error_threshold': 15.0}}
        for key, value in defaults.items():
            database.execute('INSERT OR IGNORE INTO settings VALUES (?,?)', (key, encode(value)))
    migrate_paths()


def data_path(value):
    path = Path(value)
    if path.is_absolute():
        relocated = DATA / Path(*path.parts[-2:])
        if relocated.exists():
            return relocated
        return path
    return (DATA / path)


def migrate_paths():
    subfolders = [('datasets', 'path', 'datasets'), ('models', 'artifact', 'models')]
    with connection() as database:
        for table, column, folder in subfolders:
            rows = database.execute(f'SELECT id, {column} AS stored FROM {table} WHERE {column} IS NOT NULL').fetchall()
            for row in rows:
                stored = Path(row['stored'])
                if stored.is_absolute():
                    database.execute(f'UPDATE {table} SET {column}=? WHERE id=?',
                                     (f'{folder}/{stored.name}', row['id']))


def row_dict(row):
    if row is None:
        return None
    result = dict(row)
    for key in ['quality', 'params', 'metrics', 'payload', 'result', 'logs', 'value']:
        if key in result and result[key] is not None:
            result[key] = json.loads(result[key])
    return result


def one(sql, parameters=()):
    with connection() as database:
        return row_dict(database.execute(sql, parameters).fetchone())


def many(sql, parameters=()):
    with connection() as database:
        return [row_dict(row) for row in database.execute(sql, parameters).fetchall()]


def execute(sql, parameters=()):
    with connection() as database:
        database.execute(sql, parameters)


def event(title, detail='', level='info'):
    with connection() as database:
        database.execute('INSERT INTO events VALUES (?,?,?,?,?)', (uid(), level, title, detail, now()))
        database.execute('DELETE FROM events WHERE id NOT IN '
                         '(SELECT id FROM events ORDER BY created_at DESC LIMIT 1000)')


def setting(key):
    return one('SELECT value FROM settings WHERE key=?', (key,))['value']


def create_job(kind, payload):
    job_id = uid()
    timestamp = now()
    execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?)',
            (job_id, kind, 'pending', 0, encode(payload), None,
             encode([{'time': timestamp, 'message': '任务已排队，等待计算进程'}]), timestamp, timestamp))
    return job_id


def progress(job_id, percent, message):
    with connection() as database:
        row = database.execute('SELECT logs FROM jobs WHERE id=?', (job_id,)).fetchone()
        logs = json.loads(row['logs'])
        logs.append({'time': now(), 'message': message})
        database.execute('UPDATE jobs SET progress=?, logs=?, updated_at=? WHERE id=?',
                         (percent, encode(logs[-200:]), now(), job_id))
