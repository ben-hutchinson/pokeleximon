from __future__ import annotations

from contextlib import contextmanager
import os

from psycopg_pool import ConnectionPool


_pool: ConnectionPool | None = None


def _resolve_database_url() -> str:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")
    if database_url.startswith("postgresql+psycopg://"):
        database_url = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    return database_url


def init_db() -> None:
    global _pool
    database_url = _resolve_database_url()
    _pool = ConnectionPool(
        conninfo=database_url,
        min_size=0,
        max_size=10,
        open=False,
        kwargs={"connect_timeout": 5},
    )
    _pool.open()
    ping_db()


def close_db() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def get_db():
    if _pool is None:
        raise RuntimeError("Database pool is not initialized")
    if _pool.closed:
        _pool.open()
    with _pool.connection(timeout=5) as conn:
        yield conn


def ping_db() -> None:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
