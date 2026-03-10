from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import sys


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.append(str(API_ROOT))

if "psycopg" not in sys.modules:
    psycopg_module = ModuleType("psycopg")
    psycopg_rows_module = ModuleType("psycopg.rows")
    psycopg_rows_module.dict_row = object()
    psycopg_module.rows = psycopg_rows_module
    sys.modules["psycopg"] = psycopg_module
    sys.modules["psycopg.rows"] = psycopg_rows_module

if "psycopg_pool" not in sys.modules:
    psycopg_pool_module = ModuleType("psycopg_pool")
    psycopg_pool_module.ConnectionPool = object
    sys.modules["psycopg_pool"] = psycopg_pool_module

if "redis" not in sys.modules:
    redis_module = ModuleType("redis")
    redis_module.Redis = SimpleNamespace(from_url=lambda *args, **kwargs: None)
    sys.modules["redis"] = redis_module

from app.data import repo  # noqa: E402


class _FakeCursor:
    def __init__(self, fetchone_rows: list[dict | None]):
        self._fetchone_rows = fetchone_rows
        self.executed: list[tuple[str, dict]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query: str, params: dict):
        self.executed.append((query, params))

    def fetchone(self):
        if not self._fetchone_rows:
            return None
        return self._fetchone_rows.pop(0)


class _FakeConn:
    def __init__(self, cursor: _FakeCursor):
        self._cursor = cursor
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self, row_factory=None):  # noqa: ARG002
        return self._cursor

    def commit(self):
        self.committed = True


class ConnectionsFeedbackRepoTests(unittest.TestCase):
    def test_create_connections_feedback_returns_none_for_unknown_puzzle(self):
        cursor = _FakeCursor(fetchone_rows=[None])
        conn = _FakeConn(cursor)
        with patch.object(repo, "get_db", return_value=conn):
            result = repo.create_connections_feedback(
                puzzle_id="puz_missing",
                event_type="page_view",
                session_id="sess_1",
                event_value={"foo": "bar"},
                client_ts=datetime(2026, 3, 4, 12, 0, tzinfo=timezone.utc),
                user_agent="pytest-agent",
            )
        self.assertIsNone(result)
        self.assertFalse(conn.committed)

    def test_create_connections_feedback_maps_inserted_row(self):
        now = datetime(2026, 3, 4, 12, 15, tzinfo=timezone.utc)
        cursor = _FakeCursor(
            fetchone_rows=[
                {"id": "puz_connections_1"},
                {
                    "id": 7,
                    "puzzle_id": "puz_connections_1",
                    "event_type": "solve_group",
                    "session_id": "sess_1",
                    "event_value": {"groupId": "yellow"},
                    "client_ts": now,
                    "created_at": now,
                },
            ]
        )
        conn = _FakeConn(cursor)
        with patch.object(repo, "get_db", return_value=conn):
            result = repo.create_connections_feedback(
                puzzle_id="puz_connections_1",
                event_type="solve_group",
                session_id="sess_1",
                event_value={"groupId": "yellow"},
                client_ts=now,
                user_agent="pytest-agent",
            )

        assert result is not None
        self.assertEqual(result["id"], 7)
        self.assertEqual(result["puzzleId"], "puz_connections_1")
        self.assertEqual(result["eventType"], "solve_group")
        self.assertEqual(result["sessionId"], "sess_1")
        self.assertEqual(result["eventValue"], {"groupId": "yellow"})
        self.assertTrue(result["clientTs"].startswith("2026-03-04T12:15:00"))
        self.assertTrue(result["createdAt"].startswith("2026-03-04T12:15:00"))
        self.assertTrue(conn.committed)


if __name__ == "__main__":
    unittest.main()
