from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import sys


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.append(str(API_ROOT))

# Test environment may not have runtime DB/cache deps installed.
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
    def __init__(self, fetchall_rows: list[list[dict]], fetchone_rows: list[dict | None]):
        self._fetchall_rows = fetchall_rows
        self._fetchone_rows = fetchone_rows
        self.executed: list[tuple[str, dict]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query: str, params: dict):
        self.executed.append((query, params))

    def fetchall(self):
        if not self._fetchall_rows:
            return []
        return self._fetchall_rows.pop(0)

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


class AnalyticsSummaryTests(unittest.TestCase):
    def test_analytics_summary_aggregates_key_crossword_metrics(self):
        cursor = _FakeCursor(
            fetchall_rows=[
                [
                    {"day": date(2026, 2, 15), "users": 4},
                    {"day": date(2026, 2, 16), "users": 6},
                ],
                [
                    {"event_type": "check_all", "sessions": 3},
                    {"event_type": "clue_view", "sessions": 2},
                ],
            ],
            fetchone_rows=[
                {
                    "page_sessions": 8,
                    "completed_sessions": 5,
                    "median_solve_ms": 95234.5,
                }
            ],
        )
        conn = _FakeConn(cursor)

        with patch.object(repo, "get_db", return_value=conn):
            result = repo.get_analytics_summary(days=30, timezone="Europe/London")

        self.assertEqual(result["windowDays"], 30)
        self.assertEqual(result["timezone"], "Europe/London")
        self.assertEqual(result["dailyActiveUsers"]["latest"], 6)
        self.assertEqual(result["dailyActiveUsers"]["average"], 5.0)
        self.assertEqual(result["crossword"]["pageViewSessions"], 8)
        self.assertEqual(result["crossword"]["completedSessions"], 5)
        self.assertEqual(result["crossword"]["completionRate"], 0.625)
        self.assertEqual(result["crossword"]["medianSolveTimeMs"], 95234)
        self.assertEqual(result["crossword"]["dropoffByEventType"][0]["eventType"], "check_all")
        self.assertEqual(result["crossword"]["dropoffByEventType"][0]["sessions"], 3)

    def test_analytics_summary_handles_zero_page_views(self):
        cursor = _FakeCursor(
            fetchall_rows=[
                [{"day": date(2026, 2, 16), "users": 0}],
                [],
            ],
            fetchone_rows=[
                {
                    "page_sessions": 0,
                    "completed_sessions": 0,
                    "median_solve_ms": None,
                }
            ],
        )
        conn = _FakeConn(cursor)

        with patch.object(repo, "get_db", return_value=conn):
            result = repo.get_analytics_summary(days=7, timezone="Europe/London")

        self.assertEqual(result["crossword"]["completionRate"], None)
        self.assertEqual(result["crossword"]["medianSolveTimeMs"], None)


if __name__ == "__main__":
    unittest.main()
