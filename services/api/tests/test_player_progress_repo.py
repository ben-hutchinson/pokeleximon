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


class PlayerProgressRepoTests(unittest.TestCase):
    def test_get_player_progress_returns_none_when_table_missing(self):
        cursor = _FakeCursor(fetchone_rows=[{"table_name": None}])
        with patch.object(repo, "get_db", return_value=_FakeConn(cursor)):
            result = repo.get_player_progress(player_token="tok", key="crossword:puzzle:p1")
        self.assertIsNone(result)

    def test_get_player_progress_maps_row(self):
        row = {
            "id": 17,
            "player_token": "tok_1",
            "progress_key": "crossword:puzzle:p1",
            "game_type": "crossword",
            "puzzle_id": "p1",
            "progress": {"values": {"0,0": "A"}},
            "client_updated_at": datetime(2026, 3, 3, 12, 0, tzinfo=timezone.utc),
            "updated_at": datetime(2026, 3, 3, 12, 1, tzinfo=timezone.utc),
            "created_at": datetime(2026, 3, 3, 11, 59, tzinfo=timezone.utc),
        }
        cursor = _FakeCursor(fetchone_rows=[{"table_name": "player_progress"}, row])
        with patch.object(repo, "get_db", return_value=_FakeConn(cursor)):
            result = repo.get_player_progress(player_token=" tok_1 ", key=" crossword:puzzle:p1 ")

        assert result is not None
        self.assertEqual(result["id"], 17)
        self.assertEqual(result["playerToken"], "tok_1")
        self.assertEqual(result["key"], "crossword:puzzle:p1")
        self.assertEqual(result["gameType"], "crossword")
        self.assertEqual(result["progress"], {"values": {"0,0": "A"}})
        self.assertEqual(result["puzzleId"], "p1")
        self.assertTrue(result["clientUpdatedAt"].startswith("2026-03-03T12:00:00"))
        _, params = cursor.executed[1]
        self.assertEqual(params["player_token"], "tok_1")
        self.assertEqual(params["progress_key"], "crossword:puzzle:p1")

    def test_upsert_player_progress_returns_none_when_table_missing(self):
        cursor = _FakeCursor(fetchone_rows=[{"table_name": None}])
        with patch.object(repo, "get_db", return_value=_FakeConn(cursor)):
            result = repo.upsert_player_progress(
                player_token="tok",
                key="crossword:puzzle:p1",
                game_type="crossword",
                puzzle_id="p1",
                progress={"values": {"0,0": "A"}},
                client_updated_at=datetime(2026, 3, 3, 12, 0, tzinfo=timezone.utc),
            )
        self.assertIsNone(result)

    def test_upsert_player_progress_returns_record_and_uses_conflict_update(self):
        now = datetime(2026, 3, 3, 12, 0, tzinfo=timezone.utc)
        row = {
            "id": 19,
            "player_token": "tok_2",
            "progress_key": "cryptic:puzzle:p2",
            "game_type": "cryptic",
            "puzzle_id": "p2",
            "progress": {"guess": "PIKACHU"},
            "client_updated_at": now,
            "updated_at": now,
            "created_at": now,
        }
        cursor = _FakeCursor(fetchone_rows=[{"table_name": "player_progress"}, row])
        conn = _FakeConn(cursor)
        with patch.object(repo, "get_db", return_value=conn):
            result = repo.upsert_player_progress(
                player_token=" tok_2 ",
                key=" cryptic:puzzle:p2 ",
                game_type="cryptic",
                puzzle_id="p2",
                progress={"guess": "PIKACHU"},
                client_updated_at=now,
            )

        assert result is not None
        self.assertEqual(result["id"], 19)
        self.assertEqual(result["key"], "cryptic:puzzle:p2")
        self.assertEqual(result["gameType"], "cryptic")
        self.assertEqual(result["puzzleId"], "p2")
        self.assertEqual(result["progress"], {"guess": "PIKACHU"})
        self.assertTrue(conn.committed)

        upsert_query, upsert_params = cursor.executed[1]
        self.assertIn("ON CONFLICT (player_token, progress_key) DO UPDATE", upsert_query)
        self.assertIn("EXCLUDED.client_updated_at >= player_progress.client_updated_at", upsert_query)
        self.assertEqual(upsert_params["player_token"], "tok_2")
        self.assertEqual(upsert_params["progress_key"], "cryptic:puzzle:p2")
        self.assertEqual(upsert_params["game_type"], "cryptic")
        self.assertEqual(upsert_params["puzzle_id"], "p2")
        self.assertEqual(upsert_params["client_updated_at"], now)


if __name__ == "__main__":
    unittest.main()
