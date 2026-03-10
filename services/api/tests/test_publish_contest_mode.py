from __future__ import annotations

import unittest
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

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self, row_factory=None):  # noqa: ARG002
        return self._cursor

    def commit(self):
        return None


class PublishContestModeTests(unittest.TestCase):
    def test_publish_sets_contest_mode_for_existing_daily(self):
        cursor = _FakeCursor(
            fetchone_rows=[
                {"id": "puz_daily_1"},  # existing published puzzle
                {"contest_mode": True},  # metadata update return
                {"reserve_count": 8},  # reserve query
            ]
        )
        with (
            patch.object(repo, "get_db", return_value=_FakeConn(cursor)),
            patch.object(repo, "_invalidate_puzzle_caches"),
        ):
            result = repo.publish_next_from_reserve(
                date_value="2026-03-03",
                game_type="crossword",
                timezone="Europe/London",
                reserve_threshold=5,
                contest_mode=True,
            )

        self.assertEqual(result["status"], "already_published")
        self.assertEqual(result["puzzleId"], "puz_daily_1")
        self.assertEqual(result["contestMode"], True)
        self.assertFalse(result["lowReserve"])
        update_query, update_params = cursor.executed[1]
        self.assertIn("jsonb_set", update_query)
        self.assertEqual(update_params["id"], "puz_daily_1")
        self.assertEqual(update_params["contest_mode"], True)

    def test_publish_without_contest_mode_does_not_run_metadata_update(self):
        cursor = _FakeCursor(
            fetchone_rows=[
                {"id": "puz_daily_2"},
                {"reserve_count": 8},
            ]
        )
        with (
            patch.object(repo, "get_db", return_value=_FakeConn(cursor)),
            patch.object(repo, "_invalidate_puzzle_caches"),
        ):
            result = repo.publish_next_from_reserve(
                date_value="2026-03-03",
                game_type="crossword",
                timezone="Europe/London",
                reserve_threshold=5,
                contest_mode=None,
            )

        self.assertEqual(result["contestMode"], None)
        self.assertTrue(all("jsonb_set" not in query for query, _ in cursor.executed))


if __name__ == "__main__":
    unittest.main()
