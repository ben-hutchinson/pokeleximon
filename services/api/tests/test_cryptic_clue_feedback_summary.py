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


class CrypticClueFeedbackSummaryTests(unittest.TestCase):
    def test_summary_groups_by_date_type_and_reason(self):
        cursor = _FakeCursor(
            fetchone_rows=[
                {
                    "total_count": 6,
                    "up_count": 2,
                    "down_count": 4,
                }
            ],
            fetchall_rows=[
                [
                    {"day": date(2026, 3, 1), "total_count": 2, "up_count": 1, "down_count": 1},
                    {"day": date(2026, 3, 2), "total_count": 4, "up_count": 1, "down_count": 3},
                ],
                [
                    {"clue_type": "anagram", "total_count": 3, "up_count": 1, "down_count": 2},
                    {"clue_type": "deletion", "total_count": 3, "up_count": 1, "down_count": 2},
                ],
                [
                    {"reason_tag": "wordplay_unclear", "count": 3},
                    {"reason_tag": "surface_awkward", "count": 2},
                ],
            ],
        )

        with patch.object(repo, "get_db", return_value=_FakeConn(cursor)):
            result = repo.get_cryptic_clue_feedback_summary(days=14, timezone="Europe/London")

        self.assertEqual(result["windowDays"], 14)
        self.assertEqual(result["totalFeedback"], 6)
        self.assertEqual(result["ratings"]["up"], 2)
        self.assertEqual(result["ratings"]["down"], 4)
        self.assertEqual(result["byDate"][0]["date"], "2026-03-01")
        self.assertEqual(result["byClueType"][0]["clueType"], "anagram")
        self.assertEqual(result["topReasonTags"][0]["reason"], "wordplay_unclear")


if __name__ == "__main__":
    unittest.main()
