from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
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
    def __init__(self, fetchone_rows: list[dict | None] | None = None, fetchall_rows: list[list[dict]] | None = None):
        self._fetchone_rows = fetchone_rows or []
        self._fetchall_rows = fetchall_rows or []
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

    def fetchall(self):
        if not self._fetchall_rows:
            return []
        return self._fetchall_rows.pop(0)


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


class ChallengeLeaderboardRepoTests(unittest.TestCase):
    def test_create_challenge_inserts_and_returns_record(self):
        cursor = _FakeCursor(
            fetchone_rows=[
                {"recent_count": 0},
                None,
                {
                    "id": 12,
                    "challenge_code": "AAAAAAAA",
                    "game_type": "crossword",
                    "puzzle_id": "puz_1",
                    "puzzle_date": date(2026, 3, 3),
                    "created_by_token": "tok_1",
                    "created_at": datetime(2026, 3, 3, 12, 0, tzinfo=timezone.utc),
                },
                {"member_count": 1},
            ]
        )
        conn = _FakeConn(cursor)

        with (
            patch.object(repo, "get_db", return_value=conn),
            patch.object(repo, "get_or_create_player_profile", return_value={"playerToken": "tok_1"}),
            patch.object(
                repo,
                "get_puzzle_by_date",
                return_value={"id": "puz_1", "date": "2026-03-03", "gameType": "crossword"},
            ),
            patch("app.data.repo.random.choice", return_value="A"),
        ):
            result = repo.create_challenge(
                player_token="tok_1",
                game_type="crossword",
                puzzle_id=None,
                date_value="2026-03-03",
                timezone="Europe/London",
            )

        self.assertEqual(result["id"], 12)
        self.assertEqual(result["code"], "AAAAAAAA")
        self.assertEqual(result["puzzleId"], "puz_1")
        self.assertEqual(result["memberCount"], 1)
        self.assertTrue(conn.committed)

        queries = "\n".join(query for query, _ in cursor.executed)
        self.assertIn("INSERT INTO challenges", queries)
        self.assertIn("INSERT INTO challenge_members", queries)

    def test_get_global_leaderboard_paginates_rows(self):
        cursor = _FakeCursor(
            fetchall_rows=[
                [
                    {
                        "rank": 1,
                        "player_token": "tok_a",
                        "display_name": "Alpha",
                        "completions": 5,
                        "average_solve_time_ms": 120000,
                        "best_solve_time_ms": 90000,
                    },
                    {
                        "rank": 2,
                        "player_token": "tok_b",
                        "display_name": "Bravo",
                        "completions": 4,
                        "average_solve_time_ms": 150000,
                        "best_solve_time_ms": 110000,
                    },
                    {
                        "rank": 3,
                        "player_token": "tok_c",
                        "display_name": "Charlie",
                        "completions": 3,
                        "average_solve_time_ms": 180000,
                        "best_solve_time_ms": 130000,
                    },
                ]
            ]
        )

        with patch.object(repo, "get_db", return_value=_FakeConn(cursor)):
            result = repo.get_global_leaderboard(
                game_type="crossword",
                scope="weekly",
                date_value="2026-03-03",
                limit=2,
                cursor="0",
            )

        self.assertEqual(result["scope"], "weekly")
        self.assertEqual(result["gameType"], "crossword")
        self.assertEqual(result["dateFrom"], "2026-02-25")
        self.assertEqual(result["dateTo"], "2026-03-03")
        self.assertEqual(len(result["items"]), 2)
        self.assertTrue(result["hasMore"])
        self.assertEqual(result["cursor"], "2")
        self.assertEqual(result["items"][0]["displayName"], "Alpha")


if __name__ == "__main__":
    unittest.main()
