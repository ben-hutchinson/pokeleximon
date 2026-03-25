from __future__ import annotations

import json
import random
from datetime import date as date_type
from datetime import datetime
from datetime import timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from psycopg.rows import dict_row

from app.core import config
from app.core.auth import generate_session_token, hash_password, hash_session_token, validate_username, verify_password
from app.core.db import get_db
from app.data.common import (
    CHALLENGE_CODE_ALPHABET,
    CompetitiveGameType,
    PuzzleGameType,
    fallback_display_name,
    generate_player_token,
    normalize_display_name,
    parse_cursor_offset,
    parse_date,
    player_profile_payload,
    unique_public_slug,
)


def _progress_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "playerToken": row["player_token"],
        "key": row["progress_key"],
        "gameType": row["game_type"],
        "puzzleId": row["puzzle_id"],
        "progress": row["progress"] if isinstance(row.get("progress"), dict) else {},
        "clientUpdatedAt": row["client_updated_at"].isoformat() if row.get("client_updated_at") else None,
        "updatedAt": row["updated_at"].isoformat() if row.get("updated_at") else None,
        "createdAt": row["created_at"].isoformat() if row.get("created_at") else None,
    }


def _utcnow() -> datetime:
    return datetime.now(ZoneInfo("UTC"))


def _session_expires_at(now: datetime | None = None) -> datetime:
    base = now or _utcnow()
    return base + timedelta(days=max(1, config.AUTH_SESSION_DURATION_DAYS))


def _create_auth_session(
    cur: Any,
    *,
    player_token: str,
    user_agent: str | None,
    ip_address: str | None,
) -> str:
    raw_token = generate_session_token()
    now = _utcnow()
    cur.execute(
        "INSERT INTO player_auth_sessions ("
        "player_token, session_token_hash, expires_at, user_agent, ip_address, last_seen_at"
        ") VALUES ("
        "%(player_token)s, %(session_token_hash)s, %(expires_at)s, %(user_agent)s, %(ip_address)s, %(last_seen_at)s"
        ")",
        {
            "player_token": player_token,
            "session_token_hash": hash_session_token(raw_token),
            "expires_at": _session_expires_at(now),
            "user_agent": user_agent,
            "ip_address": ip_address,
            "last_seen_at": now,
        },
    )
    return raw_token


def _profile_exists_without_account(cur: Any, player_token: str) -> bool:
    cur.execute(
        "SELECT 1 "
        "FROM player_profiles p "
        "LEFT JOIN player_accounts a ON a.player_token = p.player_token "
        "WHERE p.player_token = %(player_token)s AND a.player_token IS NULL "
        "LIMIT 1",
        {"player_token": player_token},
    )
    return cur.fetchone() is not None


def get_player_progress(*, player_token: str, key: str) -> dict[str, Any] | None:
    token = player_token.strip()
    progress_key = key.strip()
    if not token or not progress_key:
        return None

    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT to_regclass('public.player_progress') AS table_name", {})
            table_row = cur.fetchone() or {}
            if not table_row.get("table_name"):
                return None

            cur.execute(
                "SELECT id, player_token, progress_key, game_type, puzzle_id, progress, client_updated_at, updated_at, created_at "
                "FROM player_progress "
                "WHERE player_token = %(player_token)s AND progress_key = %(progress_key)s "
                "LIMIT 1",
                {
                    "player_token": token,
                    "progress_key": progress_key,
                },
            )
            row = cur.fetchone()
    return _progress_payload(row) if row else None


def upsert_player_progress(
    *,
    player_token: str,
    key: str,
    game_type: PuzzleGameType | None,
    puzzle_id: str | None,
    progress: dict[str, Any] | None,
    client_updated_at: datetime | None,
) -> dict[str, Any] | None:
    token = player_token.strip()
    progress_key = key.strip()
    if not token or not progress_key:
        return None

    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT to_regclass('public.player_progress') AS table_name", {})
            table_row = cur.fetchone() or {}
            if not table_row.get("table_name"):
                return None

            cur.execute(
                "INSERT INTO player_progress ("
                "  player_token, progress_key, game_type, puzzle_id, progress, client_updated_at"
                ") VALUES ("
                "  %(player_token)s, %(progress_key)s, %(game_type)s, %(puzzle_id)s, %(progress)s::json, %(client_updated_at)s"
                ") ON CONFLICT (player_token, progress_key) DO UPDATE SET "
                "  game_type = EXCLUDED.game_type, "
                "  puzzle_id = EXCLUDED.puzzle_id, "
                "  progress = CASE "
                "    WHEN player_progress.client_updated_at IS NULL THEN EXCLUDED.progress "
                "    WHEN EXCLUDED.client_updated_at IS NULL THEN EXCLUDED.progress "
                "    WHEN EXCLUDED.client_updated_at >= player_progress.client_updated_at THEN EXCLUDED.progress "
                "    ELSE player_progress.progress "
                "  END, "
                "  client_updated_at = CASE "
                "    WHEN player_progress.client_updated_at IS NULL THEN EXCLUDED.client_updated_at "
                "    WHEN EXCLUDED.client_updated_at IS NULL THEN player_progress.client_updated_at "
                "    WHEN EXCLUDED.client_updated_at >= player_progress.client_updated_at THEN EXCLUDED.client_updated_at "
                "    ELSE player_progress.client_updated_at "
                "  END, "
                "  updated_at = CASE "
                "    WHEN player_progress.client_updated_at IS NULL THEN NOW() "
                "    WHEN EXCLUDED.client_updated_at IS NULL THEN NOW() "
                "    WHEN EXCLUDED.client_updated_at >= player_progress.client_updated_at THEN NOW() "
                "    ELSE player_progress.updated_at "
                "  END "
                "RETURNING id, player_token, progress_key, game_type, puzzle_id, progress, client_updated_at, updated_at, created_at",
                {
                    "player_token": token,
                    "progress_key": progress_key,
                    "game_type": game_type,
                    "puzzle_id": puzzle_id,
                    "progress": json.dumps(progress or {}),
                    "client_updated_at": client_updated_at,
                },
            )
            row = cur.fetchone()
        conn.commit()

    return _progress_payload(row) if row else None


def get_or_create_player_profile(*, player_token: str) -> dict[str, Any]:
    token = player_token.strip()
    if not token:
        raise ValueError("Missing player token")

    default_name = normalize_display_name(None, player_token=token)
    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT player_token, display_name, public_slug, leaderboard_visible, avatar_preset, created_at, updated_at "
                "FROM player_profiles WHERE player_token = %(player_token)s LIMIT 1",
                {"player_token": token},
            )
            row = cur.fetchone()
            if row is None:
                public_slug = unique_public_slug(cur, display_name=default_name, player_token=token)
                cur.execute(
                    "INSERT INTO player_profiles (player_token, display_name, public_slug, leaderboard_visible, avatar_preset) "
                    "VALUES (%(player_token)s, %(display_name)s, %(public_slug)s, true, NULL) "
                    "RETURNING player_token, display_name, public_slug, leaderboard_visible, avatar_preset, created_at, updated_at",
                    {
                        "player_token": token,
                        "display_name": default_name,
                        "public_slug": public_slug,
                    },
                )
                row = cur.fetchone()
            cur.execute(
                "SELECT username FROM player_accounts WHERE player_token = %(player_token)s LIMIT 1",
                {"player_token": token},
            )
            account_row = cur.fetchone()
        conn.commit()

    merged_row = dict(row or {})
    if account_row:
        merged_row["username"] = account_row.get("username")
    return player_profile_payload(merged_row, player_token=token)


def update_player_profile(
    *,
    player_token: str,
    display_name: str | None = None,
    leaderboard_visible: bool | None = None,
    avatar_preset: str | None = None,
) -> dict[str, Any]:
    token = player_token.strip()
    if not token:
        raise ValueError("Missing player token")

    current = get_or_create_player_profile(player_token=token)
    next_display_name = (
        normalize_display_name(display_name, player_token=token) if display_name is not None else current["displayName"]
    )
    next_visible = bool(leaderboard_visible) if leaderboard_visible is not None else bool(current["leaderboardVisible"])
    next_avatar_preset = str(avatar_preset or "").strip() or None if avatar_preset is not None else current.get("avatarPreset")

    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            public_slug = current["publicSlug"]
            cur.execute(
                "UPDATE player_profiles "
                "SET display_name = %(display_name)s, leaderboard_visible = %(leaderboard_visible)s, "
                "avatar_preset = %(avatar_preset)s, updated_at = NOW() "
                "WHERE player_token = %(player_token)s "
                "RETURNING player_token, display_name, public_slug, leaderboard_visible, avatar_preset, created_at, updated_at",
                {
                    "display_name": next_display_name,
                    "leaderboard_visible": next_visible,
                    "avatar_preset": next_avatar_preset,
                    "player_token": token,
                },
            )
            row = cur.fetchone()
            cur.execute(
                "SELECT username FROM player_accounts WHERE player_token = %(player_token)s LIMIT 1",
                {"player_token": token},
            )
            account_row = cur.fetchone()
        conn.commit()

    if not row:
        return current
    merged_row = dict(row)
    if not merged_row.get("public_slug"):
        merged_row["public_slug"] = public_slug
    if account_row:
        merged_row["username"] = account_row.get("username")
    return player_profile_payload(merged_row, player_token=token)


def _merge_guest_player_data(cur: Any, *, source_player_token: str, target_player_token: str) -> None:
    if not source_player_token or source_player_token == target_player_token:
        return

    cur.execute(
        "SELECT 1 FROM player_accounts WHERE player_token = %(player_token)s LIMIT 1",
        {"player_token": source_player_token},
    )
    if cur.fetchone() is not None:
        return

    cur.execute(
        "SELECT display_name, leaderboard_visible, avatar_preset FROM player_profiles WHERE player_token = %(player_token)s LIMIT 1",
        {"player_token": source_player_token},
    )
    source_profile = cur.fetchone()
    if source_profile is None:
        return

    cur.execute(
        "SELECT display_name, leaderboard_visible, avatar_preset FROM player_profiles WHERE player_token = %(player_token)s LIMIT 1",
        {"player_token": target_player_token},
    )
    target_profile = cur.fetchone() or {}

    cur.execute(
        "INSERT INTO player_progress (player_token, progress_key, game_type, puzzle_id, progress, client_updated_at) "
        "SELECT %(target_player_token)s, progress_key, game_type, puzzle_id, progress, client_updated_at "
        "FROM player_progress WHERE player_token = %(source_player_token)s "
        "ON CONFLICT (player_token, progress_key) DO UPDATE SET "
        "  game_type = COALESCE(EXCLUDED.game_type, player_progress.game_type), "
        "  puzzle_id = COALESCE(EXCLUDED.puzzle_id, player_progress.puzzle_id), "
        "  progress = CASE "
        "    WHEN player_progress.client_updated_at IS NULL THEN EXCLUDED.progress "
        "    WHEN EXCLUDED.client_updated_at IS NULL THEN EXCLUDED.progress "
        "    WHEN EXCLUDED.client_updated_at >= player_progress.client_updated_at THEN EXCLUDED.progress "
        "    ELSE player_progress.progress "
        "  END, "
        "  client_updated_at = CASE "
        "    WHEN player_progress.client_updated_at IS NULL THEN EXCLUDED.client_updated_at "
        "    WHEN EXCLUDED.client_updated_at IS NULL THEN player_progress.client_updated_at "
        "    WHEN EXCLUDED.client_updated_at >= player_progress.client_updated_at THEN EXCLUDED.client_updated_at "
        "    ELSE player_progress.client_updated_at "
        "  END, "
        "  updated_at = NOW()",
        {
            "source_player_token": source_player_token,
            "target_player_token": target_player_token,
        },
    )
    cur.execute("DELETE FROM player_progress WHERE player_token = %(player_token)s", {"player_token": source_player_token})

    cur.execute(
        "INSERT INTO leaderboard_submissions ("
        "player_token, game_type, puzzle_id, puzzle_date, completed, solve_time_ms, used_assists, used_reveals, session_id"
        ") "
        "SELECT %(target_player_token)s, game_type, puzzle_id, puzzle_date, completed, solve_time_ms, used_assists, used_reveals, session_id "
        "FROM leaderboard_submissions WHERE player_token = %(source_player_token)s "
        "ON CONFLICT (player_token, puzzle_id) DO UPDATE SET "
        "  game_type = EXCLUDED.game_type, "
        "  puzzle_date = EXCLUDED.puzzle_date, "
        "  completed = leaderboard_submissions.completed OR EXCLUDED.completed, "
        "  solve_time_ms = CASE "
        "    WHEN leaderboard_submissions.solve_time_ms IS NULL THEN EXCLUDED.solve_time_ms "
        "    WHEN EXCLUDED.solve_time_ms IS NULL THEN leaderboard_submissions.solve_time_ms "
        "    WHEN EXCLUDED.solve_time_ms < leaderboard_submissions.solve_time_ms THEN EXCLUDED.solve_time_ms "
        "    ELSE leaderboard_submissions.solve_time_ms "
        "  END, "
        "  used_assists = leaderboard_submissions.used_assists OR EXCLUDED.used_assists, "
        "  used_reveals = leaderboard_submissions.used_reveals OR EXCLUDED.used_reveals, "
        "  session_id = COALESCE(EXCLUDED.session_id, leaderboard_submissions.session_id), "
        "  updated_at = NOW()",
        {
            "source_player_token": source_player_token,
            "target_player_token": target_player_token,
        },
    )
    cur.execute(
        "DELETE FROM leaderboard_submissions WHERE player_token = %(player_token)s",
        {"player_token": source_player_token},
    )

    cur.execute(
        "INSERT INTO challenge_members (challenge_id, player_token) "
        "SELECT challenge_id, %(target_player_token)s "
        "FROM challenge_members WHERE player_token = %(source_player_token)s "
        "ON CONFLICT (challenge_id, player_token) DO NOTHING",
        {
            "source_player_token": source_player_token,
            "target_player_token": target_player_token,
        },
    )
    cur.execute("DELETE FROM challenge_members WHERE player_token = %(player_token)s", {"player_token": source_player_token})

    cur.execute(
        "UPDATE challenges SET created_by_token = %(target_player_token)s WHERE created_by_token = %(source_player_token)s",
        {
            "source_player_token": source_player_token,
            "target_player_token": target_player_token,
        },
    )

    source_display_name = normalize_display_name(source_profile.get("display_name"), player_token=source_player_token)
    target_display_name = normalize_display_name(target_profile.get("display_name"), player_token=target_player_token)
    next_display_name = target_display_name
    if target_display_name == fallback_display_name(target_player_token) and source_display_name != fallback_display_name(
        source_player_token
    ):
        next_display_name = source_display_name
    next_visible = bool(target_profile.get("leaderboard_visible", True)) or bool(source_profile.get("leaderboard_visible", True))
    next_avatar_preset = str(target_profile.get("avatar_preset") or "").strip() or str(source_profile.get("avatar_preset") or "").strip() or None
    cur.execute(
        "UPDATE player_profiles "
        "SET display_name = %(display_name)s, leaderboard_visible = %(leaderboard_visible)s, "
        "avatar_preset = %(avatar_preset)s, updated_at = NOW() "
        "WHERE player_token = %(player_token)s",
        {
            "display_name": next_display_name,
            "leaderboard_visible": next_visible,
            "avatar_preset": next_avatar_preset,
            "player_token": target_player_token,
        },
    )
    cur.execute("DELETE FROM player_profiles WHERE player_token = %(player_token)s", {"player_token": source_player_token})


def create_player_account(
    *,
    username: str,
    password: str,
    guest_player_token: str | None = None,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> tuple[dict[str, Any], str]:
    normalized_username = validate_username(username)
    password_hash = hash_password(password)
    guest_token = (guest_player_token or "").strip()

    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT 1 FROM player_accounts WHERE username = %(username)s LIMIT 1", {"username": normalized_username})
            if cur.fetchone() is not None:
                raise ValueError("Username already exists")

            player_token = guest_token or generate_player_token()
            if guest_token:
                cur.execute("SELECT 1 FROM player_accounts WHERE player_token = %(player_token)s LIMIT 1", {"player_token": guest_token})
                if cur.fetchone() is not None:
                    raise ValueError("Guest profile already claimed")
                cur.execute(
                    "SELECT player_token, display_name, public_slug, leaderboard_visible, avatar_preset, created_at, updated_at "
                    "FROM player_profiles WHERE player_token = %(player_token)s LIMIT 1",
                    {"player_token": player_token},
                )
                profile_row = cur.fetchone()
                if profile_row is None:
                    default_name = normalize_display_name(None, player_token=player_token)
                    public_slug = unique_public_slug(cur, display_name=default_name, player_token=player_token)
                    cur.execute(
                        "INSERT INTO player_profiles (player_token, display_name, public_slug, leaderboard_visible, avatar_preset) "
                        "VALUES (%(player_token)s, %(display_name)s, %(public_slug)s, true, NULL) "
                        "RETURNING player_token, display_name, public_slug, leaderboard_visible, avatar_preset, created_at, updated_at",
                        {
                            "player_token": player_token,
                            "display_name": default_name,
                            "public_slug": public_slug,
                        },
                    )
                    profile_row = cur.fetchone()
            else:
                default_name = normalize_display_name(None, player_token=player_token)
                public_slug = unique_public_slug(cur, display_name=default_name, player_token=player_token)
                cur.execute(
                    "INSERT INTO player_profiles (player_token, display_name, public_slug, leaderboard_visible, avatar_preset) "
                    "VALUES (%(player_token)s, %(display_name)s, %(public_slug)s, true, NULL) "
                    "RETURNING player_token, display_name, public_slug, leaderboard_visible, avatar_preset, created_at, updated_at",
                    {
                        "player_token": player_token,
                        "display_name": default_name,
                        "public_slug": public_slug,
                    },
                )
                profile_row = cur.fetchone()

            cur.execute(
                "INSERT INTO player_accounts (player_token, username, password_hash, last_login_at) "
                "VALUES (%(player_token)s, %(username)s, %(password_hash)s, NOW())",
                {
                    "player_token": player_token,
                    "username": normalized_username,
                    "password_hash": password_hash,
                },
            )
            raw_session_token = _create_auth_session(
                cur,
                player_token=player_token,
                user_agent=user_agent,
                ip_address=ip_address,
            )
        conn.commit()

    profile = player_profile_payload({**dict(profile_row or {}), "username": normalized_username}, player_token=player_token)
    return (
        {
            "authenticated": True,
            "playerToken": player_token,
            "username": normalized_username,
            "profile": profile,
            "mergedGuestToken": guest_token or None,
        },
        raw_session_token,
    )


def login_player_account(
    *,
    username: str,
    password: str,
    guest_player_token: str | None = None,
    merge_guest_data: bool = True,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> tuple[dict[str, Any], str]:
    normalized_username = validate_username(username)
    guest_token = (guest_player_token or "").strip()
    merged_guest_token: str | None = None

    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT a.player_token, a.username, a.password_hash "
                "FROM player_accounts a WHERE a.username = %(username)s LIMIT 1",
                {"username": normalized_username},
            )
            account_row = cur.fetchone()
            if account_row is None or not verify_password(str(account_row.get("password_hash") or ""), password):
                raise ValueError("Invalid username or password")

            player_token = str(account_row["player_token"])
            if merge_guest_data and guest_token and guest_token != player_token and _profile_exists_without_account(cur, guest_token):
                _merge_guest_player_data(cur, source_player_token=guest_token, target_player_token=player_token)
                merged_guest_token = guest_token

            cur.execute(
                "UPDATE player_accounts SET last_login_at = NOW(), updated_at = NOW() WHERE player_token = %(player_token)s",
                {"player_token": player_token},
            )
            raw_session_token = _create_auth_session(
                cur,
                player_token=player_token,
                user_agent=user_agent,
                ip_address=ip_address,
            )
        conn.commit()

    profile = get_or_create_player_profile(player_token=player_token)
    return (
        {
            "authenticated": True,
            "playerToken": player_token,
            "username": normalized_username,
            "profile": profile,
            "mergedGuestToken": merged_guest_token,
        },
        raw_session_token,
    )


def get_player_auth_session(*, session_token: str) -> dict[str, Any]:
    raw_token = (session_token or "").strip()
    if not raw_token:
        return {
            "authenticated": False,
            "playerToken": None,
            "username": None,
            "profile": None,
            "mergedGuestToken": None,
        }

    now = _utcnow()
    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT s.id, s.player_token, a.username "
                "FROM player_auth_sessions s "
                "LEFT JOIN player_accounts a ON a.player_token = s.player_token "
                "WHERE s.session_token_hash = %(session_token_hash)s "
                "AND s.revoked_at IS NULL "
                "AND s.expires_at > %(now)s "
                "LIMIT 1",
                {
                    "session_token_hash": hash_session_token(raw_token),
                    "now": now,
                },
            )
            row = cur.fetchone()
            if row is None:
                return {
                    "authenticated": False,
                    "playerToken": None,
                    "username": None,
                    "profile": None,
                    "mergedGuestToken": None,
                }
            cur.execute(
                "UPDATE player_auth_sessions SET last_seen_at = %(now)s, expires_at = %(expires_at)s WHERE id = %(id)s",
                {
                    "id": row["id"],
                    "now": now,
                    "expires_at": _session_expires_at(now),
                },
            )
        conn.commit()

    profile = get_or_create_player_profile(player_token=str(row["player_token"]))
    return {
        "authenticated": True,
        "playerToken": str(row["player_token"]),
        "username": str(row.get("username") or ""),
        "profile": profile,
        "mergedGuestToken": None,
    }


def revoke_player_auth_session(*, session_token: str) -> None:
    raw_token = (session_token or "").strip()
    if not raw_token:
        return
    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "UPDATE player_auth_sessions SET revoked_at = NOW() "
                "WHERE session_token_hash = %(session_token_hash)s AND revoked_at IS NULL",
                {"session_token_hash": hash_session_token(raw_token)},
            )
        conn.commit()


def create_challenge(
    *,
    player_token: str,
    game_type: CompetitiveGameType,
    puzzle_id: str | None = None,
    date_value: str | None = None,
    timezone: str = "Europe/London",
) -> dict[str, Any]:
    from app.data import repo

    token = player_token.strip()
    if not token:
        raise ValueError("Missing player token")
    get_or_create_player_profile(player_token=token)

    puzzle = repo.get_puzzle_by_id(puzzle_id) if puzzle_id else repo.get_puzzle_by_date(game_type, date_value, timezone=timezone)
    if puzzle is None:
        raise ValueError("Puzzle not found")
    if puzzle.get("gameType") != game_type:
        raise ValueError("Challenge game type does not match puzzle")
    resolved_puzzle_id = str(puzzle.get("id"))
    resolved_puzzle_date = parse_date(str(puzzle.get("date")))

    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT COUNT(*) AS recent_count "
                "FROM challenges "
                "WHERE created_by_token = %(player_token)s "
                "  AND created_at >= (NOW() - INTERVAL '1 hour')",
                {"player_token": token},
            )
            recent_count = int((cur.fetchone() or {}).get("recent_count") or 0)
            if recent_count >= 20:
                raise ValueError("Challenge creation limit reached. Try again shortly.")

            challenge_code = ""
            for _ in range(12):
                candidate_code = "".join(random.choice(CHALLENGE_CODE_ALPHABET) for _ in range(8))
                cur.execute(
                    "SELECT 1 FROM challenges WHERE challenge_code = %(challenge_code)s LIMIT 1",
                    {"challenge_code": candidate_code},
                )
                if cur.fetchone() is None:
                    challenge_code = candidate_code
                    break
            if not challenge_code:
                raise RuntimeError("Unable to allocate challenge code")

            cur.execute(
                "INSERT INTO challenges (challenge_code, game_type, puzzle_id, puzzle_date, created_by_token) "
                "VALUES (%(challenge_code)s, %(game_type)s, %(puzzle_id)s, %(puzzle_date)s, %(created_by_token)s) "
                "RETURNING id, challenge_code, game_type, puzzle_id, puzzle_date, created_by_token, created_at",
                {
                    "challenge_code": challenge_code,
                    "game_type": game_type,
                    "puzzle_id": resolved_puzzle_id,
                    "puzzle_date": resolved_puzzle_date,
                    "created_by_token": token,
                },
            )
            row = cur.fetchone()
            if not row:
                raise RuntimeError("Challenge insert failed")

            challenge_id = int(row["id"])
            cur.execute(
                "INSERT INTO challenge_members (challenge_id, player_token) "
                "VALUES (%(challenge_id)s, %(player_token)s) "
                "ON CONFLICT (challenge_id, player_token) DO NOTHING",
                {"challenge_id": challenge_id, "player_token": token},
            )
            cur.execute(
                "SELECT COUNT(*) AS member_count FROM challenge_members WHERE challenge_id = %(challenge_id)s",
                {"challenge_id": challenge_id},
            )
            member_count = int((cur.fetchone() or {}).get("member_count") or 0)
        conn.commit()

    return {
        "id": challenge_id,
        "code": row["challenge_code"],
        "gameType": row["game_type"],
        "puzzleId": row["puzzle_id"],
        "puzzleDate": row["puzzle_date"].isoformat() if row.get("puzzle_date") else None,
        "createdByToken": row["created_by_token"],
        "memberCount": member_count,
        "createdAt": row["created_at"].isoformat() if row.get("created_at") else None,
    }


def get_challenge_detail(
    *,
    challenge_code: str,
    player_token: str | None = None,
    limit: int = 25,
    cursor: str | None = None,
) -> dict[str, Any] | None:
    normalized_code = (challenge_code or "").strip().upper()
    if not normalized_code:
        return None
    token = (player_token or "").strip()
    page_limit = max(1, min(limit, 100))
    offset = parse_cursor_offset(cursor)

    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT c.id, c.challenge_code, c.game_type, c.puzzle_id, c.puzzle_date, c.created_by_token, c.created_at, "
                "  (SELECT COUNT(*) FROM challenge_members cm WHERE cm.challenge_id = c.id) AS member_count "
                "FROM challenges c "
                "WHERE c.challenge_code = %(challenge_code)s "
                "LIMIT 1",
                {"challenge_code": normalized_code},
            )
            challenge_row = cur.fetchone()
            if not challenge_row:
                return None

            joined = False
            if token:
                cur.execute(
                    "SELECT 1 FROM challenge_members "
                    "WHERE challenge_id = %(challenge_id)s AND player_token = %(player_token)s "
                    "LIMIT 1",
                    {"challenge_id": challenge_row["id"], "player_token": token},
                )
                joined = cur.fetchone() is not None

            cur.execute(
                "WITH ranked AS ("
                "  SELECT "
                "    ROW_NUMBER() OVER (ORDER BY s.solve_time_ms ASC NULLS LAST, s.updated_at ASC, m.player_token ASC) AS rank, "
                "    m.player_token, "
                "    COALESCE(NULLIF(p.display_name, ''), %(fallback_prefix)s || UPPER(RIGHT(m.player_token, 6))) AS display_name, "
                "    p.public_slug, "
                "    s.solve_time_ms, s.completed, COALESCE(s.used_assists, false) AS used_assists, "
                "    COALESCE(s.used_reveals, false) AS used_reveals, s.updated_at "
                "  FROM challenge_members m "
                "  LEFT JOIN player_profiles p ON p.player_token = m.player_token "
                "  LEFT JOIN leaderboard_submissions s ON s.player_token = m.player_token "
                "    AND s.puzzle_id = %(puzzle_id)s "
                "  WHERE m.challenge_id = %(challenge_id)s "
                "    AND COALESCE(p.leaderboard_visible, true) = true "
                "    AND s.completed = true "
                ") "
                "SELECT rank, player_token, display_name, public_slug, solve_time_ms, completed, used_assists, used_reveals, updated_at "
                "FROM ranked "
                "ORDER BY rank "
                "OFFSET %(offset)s LIMIT %(limit_plus_one)s",
                {
                    "fallback_prefix": "Player ",
                    "puzzle_id": challenge_row["puzzle_id"],
                    "challenge_id": challenge_row["id"],
                    "offset": offset,
                    "limit_plus_one": page_limit + 1,
                },
            )
            ranked_rows = cur.fetchall()

    has_more = len(ranked_rows) > page_limit
    visible_rows = ranked_rows[:page_limit]
    next_cursor = str(offset + page_limit) if has_more else None

    return {
        "challenge": {
            "id": challenge_row["id"],
            "code": challenge_row["challenge_code"],
            "gameType": challenge_row["game_type"],
            "puzzleId": challenge_row["puzzle_id"],
            "puzzleDate": challenge_row["puzzle_date"].isoformat() if challenge_row.get("puzzle_date") else None,
            "createdByToken": challenge_row["created_by_token"],
            "memberCount": int(challenge_row.get("member_count") or 0),
            "createdAt": challenge_row["created_at"].isoformat() if challenge_row.get("created_at") else None,
        },
        "joined": joined,
        "items": [
            {
                "rank": int(row["rank"]),
                "playerToken": row["player_token"],
                "displayName": row["display_name"],
                "publicSlug": row.get("public_slug"),
                "solveTimeMs": int(row["solve_time_ms"]) if row.get("solve_time_ms") is not None else None,
                "completed": bool(row.get("completed")),
                "usedAssists": bool(row.get("used_assists")),
                "usedReveals": bool(row.get("used_reveals")),
                "updatedAt": row["updated_at"].isoformat() if row.get("updated_at") else None,
            }
            for row in visible_rows
        ],
        "cursor": next_cursor,
        "hasMore": has_more,
    }


def join_challenge(*, player_token: str, challenge_code: str, limit: int = 25, cursor: str | None = None) -> dict[str, Any] | None:
    token = player_token.strip()
    normalized_code = (challenge_code or "").strip().upper()
    if not token or not normalized_code:
        return None
    get_or_create_player_profile(player_token=token)

    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id FROM challenges WHERE challenge_code = %(challenge_code)s LIMIT 1",
                {"challenge_code": normalized_code},
            )
            row = cur.fetchone()
            if not row:
                return None
            cur.execute(
                "INSERT INTO challenge_members (challenge_id, player_token) "
                "VALUES (%(challenge_id)s, %(player_token)s) "
                "ON CONFLICT (challenge_id, player_token) DO NOTHING",
                {"challenge_id": row["id"], "player_token": token},
            )
        conn.commit()

    return get_challenge_detail(challenge_code=normalized_code, player_token=token, limit=limit, cursor=cursor)


def submit_leaderboard_result(
    *,
    player_token: str,
    game_type: CompetitiveGameType,
    puzzle_id: str,
    puzzle_date: str | date_type,
    completed: bool = True,
    solve_time_ms: int | None = None,
    used_assists: bool = False,
    used_reveals: bool = False,
    session_id: str | None = None,
) -> dict[str, Any]:
    token = player_token.strip()
    resolved_puzzle_id = puzzle_id.strip()
    if not token or not resolved_puzzle_id:
        raise ValueError("Missing token or puzzle id")
    get_or_create_player_profile(player_token=token)
    resolved_puzzle_date = parse_date(puzzle_date)
    normalized_solve_ms = max(0, int(solve_time_ms)) if solve_time_ms is not None else None
    normalized_session_id = session_id.strip() if isinstance(session_id, str) and session_id.strip() else None

    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT COUNT(*) AS recent_count "
                "FROM leaderboard_submissions "
                "WHERE player_token = %(player_token)s "
                "  AND updated_at >= (NOW() - INTERVAL '30 seconds')",
                {"player_token": token},
            )
            recent_count = int((cur.fetchone() or {}).get("recent_count") or 0)
            if recent_count >= 60:
                raise ValueError("Leaderboard submission rate limit reached")

            cur.execute(
                "INSERT INTO leaderboard_submissions ("
                "  player_token, game_type, puzzle_id, puzzle_date, completed, solve_time_ms, "
                "  used_assists, used_reveals, session_id"
                ") VALUES ("
                "  %(player_token)s, %(game_type)s, %(puzzle_id)s, %(puzzle_date)s, %(completed)s, %(solve_time_ms)s, "
                "  %(used_assists)s, %(used_reveals)s, %(session_id)s"
                ") ON CONFLICT (player_token, puzzle_id) DO UPDATE SET "
                "  game_type = EXCLUDED.game_type, "
                "  puzzle_date = EXCLUDED.puzzle_date, "
                "  completed = leaderboard_submissions.completed OR EXCLUDED.completed, "
                "  solve_time_ms = CASE "
                "    WHEN leaderboard_submissions.solve_time_ms IS NULL THEN EXCLUDED.solve_time_ms "
                "    WHEN EXCLUDED.solve_time_ms IS NULL THEN leaderboard_submissions.solve_time_ms "
                "    WHEN EXCLUDED.solve_time_ms < leaderboard_submissions.solve_time_ms THEN EXCLUDED.solve_time_ms "
                "    ELSE leaderboard_submissions.solve_time_ms "
                "  END, "
                "  used_assists = leaderboard_submissions.used_assists OR EXCLUDED.used_assists, "
                "  used_reveals = leaderboard_submissions.used_reveals OR EXCLUDED.used_reveals, "
                "  session_id = COALESCE(EXCLUDED.session_id, leaderboard_submissions.session_id), "
                "  updated_at = NOW() "
                "RETURNING id, player_token, game_type, puzzle_id, puzzle_date, completed, solve_time_ms, "
                "  used_assists, used_reveals, session_id, submitted_at, updated_at",
                {
                    "player_token": token,
                    "game_type": game_type,
                    "puzzle_id": resolved_puzzle_id,
                    "puzzle_date": resolved_puzzle_date,
                    "completed": bool(completed),
                    "solve_time_ms": normalized_solve_ms,
                    "used_assists": bool(used_assists),
                    "used_reveals": bool(used_reveals),
                    "session_id": normalized_session_id,
                },
            )
            row = cur.fetchone()
        conn.commit()

    if not row:
        raise RuntimeError("Leaderboard submission failed")
    return {
        "id": int(row["id"]),
        "playerToken": row["player_token"],
        "gameType": row["game_type"],
        "puzzleId": row["puzzle_id"],
        "puzzleDate": row["puzzle_date"].isoformat() if row.get("puzzle_date") else None,
        "completed": bool(row.get("completed")),
        "solveTimeMs": int(row["solve_time_ms"]) if row.get("solve_time_ms") is not None else None,
        "usedAssists": bool(row.get("used_assists")),
        "usedReveals": bool(row.get("used_reveals")),
        "sessionId": row.get("session_id"),
        "submittedAt": row["submitted_at"].isoformat() if row.get("submitted_at") else None,
        "updatedAt": row["updated_at"].isoformat() if row.get("updated_at") else None,
    }


def get_global_leaderboard(
    *,
    game_type: CompetitiveGameType,
    scope: Literal["daily", "weekly"] = "daily",
    date_value: str | date_type | None = None,
    timezone: str = "Europe/London",
    limit: int = 25,
    cursor: str | None = None,
) -> dict[str, Any]:
    target_date = parse_date(date_value) if date_value else datetime.now(ZoneInfo(timezone)).date()
    start_date = target_date if scope == "daily" else target_date - timedelta(days=6)
    end_date = target_date

    offset = parse_cursor_offset(cursor)
    page_limit = max(1, min(limit, 100))
    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "WITH aggregated AS ("
                "  SELECT "
                "    s.player_token, "
                "    COALESCE(NULLIF(p.display_name, ''), %(fallback_prefix)s || UPPER(RIGHT(s.player_token, 6))) AS display_name, "
                "    p.public_slug, "
                "    COUNT(*) AS completions, "
                "    ROUND(AVG(s.solve_time_ms) FILTER (WHERE s.solve_time_ms IS NOT NULL))::int AS average_solve_time_ms, "
                "    MIN(s.solve_time_ms) FILTER (WHERE s.solve_time_ms IS NOT NULL) AS best_solve_time_ms "
                "  FROM leaderboard_submissions s "
                "  LEFT JOIN player_profiles p ON p.player_token = s.player_token "
                "  WHERE s.game_type = %(game_type)s "
                "    AND s.puzzle_date >= %(start_date)s "
                "    AND s.puzzle_date <= %(end_date)s "
                "    AND s.completed = true "
                "    AND COALESCE(p.leaderboard_visible, true) = true "
                "  GROUP BY s.player_token, p.display_name, p.public_slug"
                "), ranked AS ("
                "  SELECT "
                "    ROW_NUMBER() OVER (ORDER BY completions DESC, average_solve_time_ms ASC NULLS LAST, best_solve_time_ms ASC NULLS LAST, player_token ASC) AS rank, "
                "    player_token, display_name, public_slug, completions, average_solve_time_ms, best_solve_time_ms "
                "  FROM aggregated"
                ") "
                "SELECT rank, player_token, display_name, public_slug, completions, average_solve_time_ms, best_solve_time_ms "
                "FROM ranked "
                "ORDER BY rank "
                "OFFSET %(offset)s LIMIT %(limit_plus_one)s",
                {
                    "fallback_prefix": "Player ",
                    "game_type": game_type,
                    "start_date": start_date,
                    "end_date": end_date,
                    "offset": offset,
                    "limit_plus_one": page_limit + 1,
                },
            )
            rows = cur.fetchall()

    has_more = len(rows) > page_limit
    visible_rows = rows[:page_limit]
    next_cursor = str(offset + page_limit) if has_more else None
    return {
        "scope": scope,
        "gameType": game_type,
        "dateFrom": start_date.isoformat(),
        "dateTo": end_date.isoformat(),
        "items": [
            {
                "rank": int(row["rank"]),
                "playerToken": row["player_token"],
                "displayName": row["display_name"],
                "publicSlug": row.get("public_slug"),
                "completions": int(row["completions"]),
                "averageSolveTimeMs": int(row["average_solve_time_ms"]) if row.get("average_solve_time_ms") is not None else None,
                "bestSolveTimeMs": int(row["best_solve_time_ms"]) if row.get("best_solve_time_ms") is not None else None,
            }
            for row in visible_rows
        ],
        "cursor": next_cursor,
        "hasMore": has_more,
    }
