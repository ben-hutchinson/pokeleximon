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
    def __init__(self, rows: list[dict]):
        self._rows = rows
        self.executed: list[tuple[str, dict]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query: str, params: dict):
        self.executed.append((query, params))

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, cursor: _FakeCursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self, row_factory=None):  # noqa: ARG002
        return self._cursor


class ArchivePaginationTests(unittest.TestCase):
    def test_first_page_has_cursor_for_next_page(self):
        rows = [
            {
                "id": "puz_003",
                "date": date(2026, 2, 10),
                "game_type": "crossword",
                "title": "Puzzle 3",
                "difficulty": "easy",
                "published_at": datetime(2026, 2, 10, 0, 0, tzinfo=timezone.utc),
            },
            {
                "id": "puz_002",
                "date": date(2026, 2, 10),
                "game_type": "crossword",
                "title": "Puzzle 2",
                "difficulty": "medium",
                "published_at": datetime(2026, 2, 9, 0, 0, tzinfo=timezone.utc),
            },
            {
                "id": "puz_001",
                "date": date(2026, 2, 9),
                "game_type": "crossword",
                "title": "Puzzle 1",
                "difficulty": "hard",
                "published_at": datetime(2026, 2, 8, 0, 0, tzinfo=timezone.utc),
            },
        ]
        fake_cursor = _FakeCursor(rows)
        fake_conn = _FakeConn(fake_cursor)

        with (
            patch.object(repo, "_cache_get", return_value=None),
            patch.object(repo, "_cache_set"),
            patch.object(repo, "get_db", return_value=fake_conn),
        ):
            result = repo.get_archive("crossword", limit=2, cursor=None)

        self.assertEqual(len(result["items"]), 2)
        self.assertTrue(result["hasMore"])
        self.assertEqual(result["cursor"], "2026-02-10|puz_002")

        self.assertEqual(len(fake_cursor.executed), 1)
        _, params = fake_cursor.executed[0]
        self.assertEqual(params["limit_plus_one"], 3)
        self.assertEqual(params["game_type"], "crossword")
        self.assertNotIn("cursor_date", params)
        self.assertNotIn("cursor_id", params)

    def test_cursor_filters_and_end_of_list(self):
        rows = [
            {
                "id": "puz_000",
                "date": date(2026, 2, 8),
                "game_type": "crossword",
                "title": "Puzzle 0",
                "difficulty": "easy",
                "published_at": datetime(2026, 2, 8, 0, 0, tzinfo=timezone.utc),
            }
        ]
        fake_cursor = _FakeCursor(rows)
        fake_conn = _FakeConn(fake_cursor)

        with (
            patch.object(repo, "_cache_get", return_value=None),
            patch.object(repo, "_cache_set"),
            patch.object(repo, "get_db", return_value=fake_conn),
        ):
            result = repo.get_archive("crossword", limit=2, cursor="2026-02-10|puz_002")

        self.assertEqual(len(result["items"]), 1)
        self.assertFalse(result["hasMore"])
        self.assertIsNone(result["cursor"])

        self.assertEqual(len(fake_cursor.executed), 1)
        _, params = fake_cursor.executed[0]
        self.assertEqual(params["cursor_date"], date(2026, 2, 10))
        self.assertEqual(params["cursor_id"], "puz_002")

    def test_invalid_cursor_raises(self):
        with patch.object(repo, "_cache_get", return_value=None):
            with self.assertRaises(ValueError):
                repo.get_archive("crossword", limit=2, cursor="bad-cursor")

    def test_archive_filters_are_applied_server_side(self):
        fake_cursor = _FakeCursor([])
        fake_conn = _FakeConn(fake_cursor)

        with (
            patch.object(repo, "_cache_get", return_value=None),
            patch.object(repo, "_cache_set"),
            patch.object(repo, "get_db", return_value=fake_conn),
        ):
            repo.get_archive(
                None,
                limit=20,
                difficulty="hard",
                title_query="starter",
                theme_tags=["Fire", "fire", ""],
                date_from="2026-01-01",
                date_to="2026-02-01",
            )

        self.assertEqual(len(fake_cursor.executed), 1)
        query, params = fake_cursor.executed[0]
        self.assertIn("metadata->>'difficulty' = %(difficulty)s", query)
        self.assertIn("title ILIKE %(title_query)s", query)
        self.assertIn("jsonb_array_elements_text", query)
        self.assertIn("date >= %(date_from)s", query)
        self.assertIn("date <= %(date_to)s", query)
        self.assertEqual(params["difficulty"], "hard")
        self.assertEqual(params["title_query"], "%starter%")
        self.assertEqual(params["theme_tags"], ["fire"])
        self.assertEqual(params["date_from"], date(2026, 1, 1))
        self.assertEqual(params["date_to"], date(2026, 2, 1))
        self.assertNotIn("game_type", params)

    def test_invalid_date_filter_raises(self):
        with patch.object(repo, "_cache_get", return_value=None):
            with self.assertRaises(ValueError):
                repo.get_archive("crossword", date_from="2026-99-99")

    def test_archive_note_snippet_is_whitespace_normalized(self):
        rows = [
            {
                "id": "puz_note",
                "date": date(2026, 2, 12),
                "game_type": "crossword",
                "title": "Puzzle note",
                "difficulty": "easy",
                "notes": "  Theme note with\nline breaks   and spacing.  ",
                "published_at": datetime(2026, 2, 12, 0, 0, tzinfo=timezone.utc),
            }
        ]
        fake_cursor = _FakeCursor(rows)
        fake_conn = _FakeConn(fake_cursor)

        with (
            patch.object(repo, "_cache_get", return_value=None),
            patch.object(repo, "_cache_set"),
            patch.object(repo, "get_db", return_value=fake_conn),
        ):
            result = repo.get_archive("crossword", limit=10, cursor=None)

        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["noteSnippet"], "Theme note with line breaks and spacing.")


if __name__ == "__main__":
    unittest.main()
