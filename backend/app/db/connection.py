import sqlite3

from .. import config

if config.USE_POSTGRES:
    import psycopg2
    import psycopg2.extras

    IntegrityError = psycopg2.IntegrityError
else:
    class IntegrityError(Exception):
        """Never raised in SQLite mode; sqlite3.IntegrityError is used instead."""


SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    order_id TEXT NOT NULL,
    order_date TEXT,
    customer_email TEXT,
    currency TEXT,
    gross_amount TEXT,
    discount TEXT,
    net_amount TEXT,
    status TEXT,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    transaction_ref TEXT NOT NULL,
    processed_at TEXT,
    order_reference TEXT,
    currency TEXT,
    amount TEXT,
    fee TEXT,
    net_settled TEXT,
    type TEXT,
    status TEXT,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS explanations (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, fingerprint)
);
"""

POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    order_id TEXT NOT NULL,
    order_date TEXT,
    customer_email TEXT,
    currency TEXT,
    gross_amount TEXT,
    discount TEXT,
    net_amount TEXT,
    status TEXT,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS payments (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    transaction_ref TEXT NOT NULL,
    processed_at TEXT,
    order_reference TEXT,
    currency TEXT,
    amount TEXT,
    fee TEXT,
    net_settled TEXT,
    type TEXT,
    status TEXT,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS explanations (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, fingerprint)
);
"""


class PgConnection:
    """Wraps a psycopg2 connection so callers can keep using '?' placeholders,
    dict-like rows, and a sqlite3-style context manager (commit-or-rollback then close)."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        cur = self._conn.cursor()
        cur.execute(sql.replace("?", "%s"), params)
        return cur

    def executemany(self, sql, seq):
        cur = self._conn.cursor()
        cur.executemany(sql.replace("?", "%s"), seq)
        return cur

    def executescript(self, sql):
        cur = self._conn.cursor()
        cur.execute(sql)
        return cur

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self._conn.commit()
        else:
            self._conn.rollback()
        self._conn.close()
        return False


def connect():
    if config.USE_POSTGRES:
        conn = psycopg2.connect(config.DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
        return PgConnection(conn)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with connect() as db:
        db.executescript(POSTGRES_SCHEMA if config.USE_POSTGRES else SQLITE_SCHEMA)
