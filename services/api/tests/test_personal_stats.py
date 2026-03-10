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
    def __init__(self, fetchone_rows: list[dict | None], fetchall_rows: list[list[dict]]):
        self._fetchone_rows = fetchone_rows
        self._fetchall_rows = fetchall_rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query: str, params: dict):
        del query, params

    def fetchone(self):
        if not self._fetchone_rows:
            return None
        return self._fetchone_rows.pop(0)

    def fetchall(self):
        if not self._fetchall_rows:
            return []
        return self._fetchall_rows.pop(0)


class _FakeConn:
    def __init__(self, cursor: _FakeCursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self, row_factory=None):  # noqa: ARG002
        return self._cursor


class PersonalStatsTests(unittest.TestCase):
    def test_personal_stats_aggregates_metrics_and_streaks(self):
        cursor = _FakeCursor(
            fetchone_rows=[
                {"table_name": "crossword_feedback"},
                {
                    "page_view_count": 9,
                    "completed_count": 4,
                    "page_view_puzzle_count": 6,
                    "completed_puzzle_count": 4,
                    "clean_completed_count": 3,
                    "median_solve_ms": 87456.4,
                },
                {"table_name": "cryptic_feedback"},
                {
                    "page_view_count": 5,
                    "page_view_puzzle_count": 2,
                },
                {"table_name": "leaderboard_submissions"},
                {
                    "completed_count": 2,
                    "clean_completed_count": 1,
                    "median_solve_ms": 65234.2,
                },
                {"table_name": "connections_feedback"},
                {
                    "page_view_count": 4,
                    "completed_count": 1,
                    "page_view_puzzle_count": 2,
                    "completed_puzzle_count": 1,
                    "clean_completed_count": 1,
                },
            ],
            fetchall_rows=[
                [
                    {"day": date(2026, 3, 1), "page_views": 2, "completions": 1, "clean_completions": 1},
                    {"day": date(2026, 3, 2), "page_views": 3, "completions": 2, "clean_completions": 1},
                ],
                [
                    {"solved_date": date(2026, 2, 28)},
                    {"solved_date": date(2026, 3, 1)},
                    {"solved_date": date(2026, 3, 2)},
                ],
                [
                    {"day": date(2026, 3, 1), "page_views": 3},
                    {"day": date(2026, 3, 2), "page_views": 2},
                ],
                [
                    {"day": date(2026, 3, 1), "completions": 1, "clean_completions": 1},
                    {"day": date(2026, 3, 2), "completions": 1, "clean_completions": 0},
                ],
                [
                    {"day": date(2026, 3, 2), "page_views": 2, "completions": 1, "clean_completions": 1},
                ],
            ],
        )

        with patch.object(repo, "get_db", return_value=_FakeConn(cursor)):
            result = repo.get_personal_stats(session_ids=["sess_a"], days=30, timezone="Europe/London")

        self.assertEqual(result["windowDays"], 30)
        self.assertEqual(result["crossword"]["pageViews"], 9)
        self.assertEqual(result["crossword"]["completions"], 4)
        self.assertEqual(result["crossword"]["completionRate"], 0.6667)
        self.assertEqual(result["crossword"]["cleanSolveRate"], 0.75)
        self.assertEqual(result["crossword"]["medianSolveTimeMs"], 87456)
        self.assertEqual(result["crossword"]["streakCurrent"], 3)
        self.assertEqual(result["crossword"]["streakBest"], 3)
        self.assertTrue(any(day["date"] == "2026-03-01" for day in result["historyByGameType"]["crossword"]))
        self.assertEqual(result["cryptic"]["pageViews"], 5)
        self.assertEqual(result["cryptic"]["completions"], 2)
        self.assertEqual(result["cryptic"]["cleanSolveRate"], 0.5)
        self.assertEqual(result["cryptic"]["medianSolveTimeMs"], 65234)
        self.assertEqual(result["cryptic"]["streakCurrent"], 2)
        self.assertEqual(result["connections"]["pageViews"], 4)
        self.assertEqual(result["connections"]["completions"], 1)
        self.assertEqual(result["connections"]["cleanSolveRate"], 1.0)
        self.assertEqual(result["connections"]["streakBest"], 1)

    def test_personal_stats_without_sessions_returns_empty_payload(self):
        result = repo.get_personal_stats(session_ids=[], days=7, timezone="Europe/London")
        self.assertEqual(result["sessionIds"], [])
        self.assertEqual(result["crossword"]["pageViews"], 0)
        self.assertEqual(result["crossword"]["completions"], 0)
        self.assertEqual(result["crossword"]["completionRate"], None)
        self.assertEqual(result["crossword"]["streakCurrent"], 0)
        self.assertEqual(result["cryptic"]["completions"], 0)
        self.assertEqual(result["connections"]["completions"], 0)
        self.assertEqual(len(result["historyByGameType"]["crossword"]), 7)
        self.assertEqual(len(result["historyByGameType"]["cryptic"]), 7)
        self.assertEqual(len(result["historyByGameType"]["connections"]), 7)

    def test_personal_stats_missing_telemetry_table_returns_empty_payload(self):
        cursor = _FakeCursor(
            fetchone_rows=[
                {"table_name": None},
                {"table_name": None},
                {"table_name": None},
                {"table_name": None},
            ],
            fetchall_rows=[],
        )
        with patch.object(repo, "get_db", return_value=_FakeConn(cursor)):
            result = repo.get_personal_stats(session_ids=["sess_a"], days=7, timezone="Europe/London")

        self.assertEqual(result["sessionIds"], ["sess_a"])
        self.assertEqual(result["crossword"]["pageViews"], 0)
        self.assertEqual(result["crossword"]["completions"], 0)
        self.assertEqual(result["cryptic"]["completions"], 0)
        self.assertEqual(result["connections"]["completions"], 0)
        self.assertEqual(len(result["historyByGameType"]["crossword"]), 7)


if __name__ == "__main__":
    unittest.main()
