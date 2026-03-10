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
    def __init__(self, fetchone_rows: list[dict | None] | None = None):
        self._fetchone_rows = fetchone_rows or []
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


class PlayerAuthRepoTests(unittest.TestCase):
    def test_unique_public_slug_without_exclude_player_token_uses_simple_lookup(self):
        cursor = _FakeCursor(fetchone_rows=[None])

        result = repo._unique_public_slug(cursor, display_name="Ash", player_token="tok_1")

        self.assertEqual(result, "ash")
        self.assertEqual(len(cursor.executed), 1)
        query, params = cursor.executed[0]
        self.assertIn("SELECT 1 FROM player_profiles WHERE public_slug = %(public_slug)s LIMIT 1", query)
        self.assertNotIn("exclude_player_token", query)
        self.assertEqual(params, {"public_slug": "ash"})

    def test_unique_public_slug_with_exclude_player_token_checks_other_players_only(self):
        cursor = _FakeCursor(fetchone_rows=[{"exists": 1}, None])

        result = repo._unique_public_slug(
            cursor,
            display_name="Ash",
            player_token="tok_1",
            exclude_player_token="tok_1",
        )

        self.assertEqual(result, "ash-2")
        self.assertEqual(len(cursor.executed), 2)
        first_query, first_params = cursor.executed[0]
        second_query, second_params = cursor.executed[1]
        self.assertIn("player_token <> %(exclude_player_token)s", first_query)
        self.assertEqual(first_params["public_slug"], "ash")
        self.assertEqual(first_params["exclude_player_token"], "tok_1")
        self.assertIn("player_token <> %(exclude_player_token)s", second_query)
        self.assertEqual(second_params["public_slug"], "ash-2")
        self.assertEqual(second_params["exclude_player_token"], "tok_1")

    def test_create_player_account_claims_existing_guest_profile(self):
        now = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)
        profile_row = {
            "player_token": "guest_tok",
            "display_name": "Guest Hero",
            "public_slug": "guest-hero",
            "leaderboard_visible": True,
            "created_at": now,
            "updated_at": now,
        }
        cursor = _FakeCursor(fetchone_rows=[None, None, profile_row])
        conn = _FakeConn(cursor)

        with (
            patch.object(repo, "get_db", return_value=conn),
            patch.object(repo, "hash_password", return_value="hashed-password"),
            patch.object(repo, "_create_auth_session", return_value="raw-session-token"),
        ):
            session, raw_session_token = repo.create_player_account(
                username="Alice123",
                password="correct horse battery staple",
                guest_player_token="guest_tok",
                user_agent="pytest",
                ip_address="127.0.0.1",
            )

        self.assertEqual(raw_session_token, "raw-session-token")
        self.assertTrue(session["authenticated"])
        self.assertEqual(session["playerToken"], "guest_tok")
        self.assertEqual(session["username"], "alice123")
        self.assertEqual(session["mergedGuestToken"], "guest_tok")
        self.assertEqual(session["profile"]["publicSlug"], "guest-hero")
        self.assertTrue(session["profile"]["hasAccount"])
        self.assertTrue(conn.committed)

        queries = "\n".join(query for query, _ in cursor.executed)
        self.assertIn("SELECT 1 FROM player_accounts WHERE username", queries)
        self.assertIn("INSERT INTO player_accounts", queries)
        insert_params = next(params for query, params in cursor.executed if "INSERT INTO player_accounts" in query)
        self.assertEqual(insert_params["player_token"], "guest_tok")
        self.assertEqual(insert_params["username"], "alice123")

    def test_login_player_account_merges_guest_data_into_claimed_account(self):
        cursor = _FakeCursor(
            fetchone_rows=[
                {
                    "player_token": "acct_tok",
                    "username": "alice123",
                    "password_hash": "stored-password-hash",
                },
                {"exists": 1},
                None,
                {"display_name": "Guest Hero", "leaderboard_visible": True},
                {"display_name": "Account Hero", "leaderboard_visible": True},
            ]
        )
        conn = _FakeConn(cursor)

        with (
            patch.object(repo, "get_db", return_value=conn),
            patch.object(repo, "verify_password", return_value=True),
            patch.object(repo, "_create_auth_session", return_value="raw-session-token"),
            patch.object(
                repo,
                "get_or_create_player_profile",
                return_value={
                    "playerToken": "acct_tok",
                    "displayName": "Account Hero",
                    "publicSlug": "account-hero",
                    "leaderboardVisible": True,
                    "hasAccount": True,
                    "createdAt": "2026-03-10T12:00:00+00:00",
                    "updatedAt": "2026-03-10T12:00:00+00:00",
                },
            ),
        ):
            session, raw_session_token = repo.login_player_account(
                username="Alice123",
                password="correct horse battery staple",
                guest_player_token="guest_tok",
                merge_guest_data=True,
                user_agent="pytest",
                ip_address="127.0.0.1",
            )

        self.assertEqual(raw_session_token, "raw-session-token")
        self.assertTrue(session["authenticated"])
        self.assertEqual(session["playerToken"], "acct_tok")
        self.assertEqual(session["mergedGuestToken"], "guest_tok")
        self.assertEqual(session["profile"]["publicSlug"], "account-hero")
        self.assertTrue(conn.committed)

        queries = "\n".join(query for query, _ in cursor.executed)
        self.assertIn("INSERT INTO player_progress", queries)
        self.assertIn("INSERT INTO leaderboard_submissions", queries)
        self.assertIn("INSERT INTO challenge_members", queries)
        self.assertIn("UPDATE challenges SET created_by_token", queries)
        self.assertIn("DELETE FROM player_profiles", queries)

    def test_get_player_auth_session_refreshes_active_session(self):
        cursor = _FakeCursor(
            fetchone_rows=[
                {
                    "id": 5,
                    "player_token": "acct_tok",
                    "username": "alice123",
                }
            ]
        )
        conn = _FakeConn(cursor)

        with (
            patch.object(repo, "get_db", return_value=conn),
            patch.object(
                repo,
                "get_or_create_player_profile",
                return_value={
                    "playerToken": "acct_tok",
                    "displayName": "Account Hero",
                    "publicSlug": "account-hero",
                    "leaderboardVisible": True,
                    "hasAccount": True,
                    "createdAt": "2026-03-10T12:00:00+00:00",
                    "updatedAt": "2026-03-10T12:00:00+00:00",
                },
            ),
        ):
            session = repo.get_player_auth_session(session_token="raw-session-token")

        self.assertTrue(session["authenticated"])
        self.assertEqual(session["playerToken"], "acct_tok")
        self.assertEqual(session["username"], "alice123")
        self.assertEqual(session["profile"]["publicSlug"], "account-hero")
        self.assertTrue(conn.committed)
        self.assertIn("UPDATE player_auth_sessions SET last_seen_at", cursor.executed[1][0])

    def test_get_public_player_stats_hides_internal_player_token(self):
        stats_payload = {
            "sessionIds": [],
            "windowDays": 30,
            "timezone": "Europe/London",
            "crossword": {},
            "cryptic": {},
            "connections": {},
            "historyByGameType": {},
        }
        with (
            patch.object(
                repo,
                "get_public_player_profile",
                return_value={
                    "displayName": "Account Hero",
                    "publicSlug": "account-hero",
                    "leaderboardVisible": True,
                    "hasAccount": True,
                    "createdAt": "2026-03-10T12:00:00+00:00",
                    "updatedAt": "2026-03-10T12:00:00+00:00",
                    "playerToken": "acct_tok",
                },
            ),
            patch.object(repo, "get_player_stats", return_value=stats_payload),
        ):
            result = repo.get_public_player_stats(public_slug="account-hero", days=30, timezone="Europe/London")

        assert result is not None
        self.assertEqual(result["profile"]["publicSlug"], "account-hero")
        self.assertNotIn("playerToken", result["profile"])
        self.assertEqual(result["stats"], stats_payload)


if __name__ == "__main__":
    unittest.main()
