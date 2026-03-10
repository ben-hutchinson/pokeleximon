from __future__ import annotations

import json
import logging
import random
import re
from datetime import date as date_type
from datetime import datetime
from datetime import timedelta
from typing import Any, Literal, cast
from uuid import uuid4
from zoneinfo import ZoneInfo

from psycopg.rows import dict_row

from app.core import config
from app.core.auth import generate_session_token, hash_password, hash_session_token, normalize_username, validate_username, verify_password
from app.core.cache import get_cache
from app.core.db import get_db
from app.services.alerting import notify_external_alert
from app.services.artifact_store import write_json_artifact


logger = logging.getLogger(__name__)

PuzzleDict = dict[str, Any]
PublishStatus = Literal["published", "already_published", "reserve_empty"]
PuzzleGameType = Literal["crossword", "cryptic", "connections"]
CompetitiveGameType = Literal["crossword", "cryptic"]

CACHE_TTL_SECONDS = 300
DATE_TOKEN_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
WHITESPACE_RE = re.compile(r"\s+")
CLUE_FEEDBACK_REASON_TAGS = {
    "definition_too_obvious",
    "wordplay_unclear",
    "surface_awkward",
    "too_easy",
    "too_hard",
    "answer_leak",
    "not_fair",
}
DISPLAY_NAME_ALLOWED_RE = re.compile(r"[^A-Za-z0-9 _-]")
PUBLIC_SLUG_RE = re.compile(r"[^a-z0-9]+")
CHALLENGE_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _cache_key(prefix: str, *parts: str) -> str:
    safe_parts = [p.replace(":", "_") for p in parts if p]
    return ":".join([prefix, *safe_parts])


def _cache_get(key: str) -> dict[str, Any] | None:
    cache = get_cache()
    value = cache.get(key)
    if value is None:
        return None
    return cast(dict[str, Any], json.loads(value))


def _cache_set(key: str, value: dict[str, Any]) -> None:
    cache = get_cache()
    cache.setex(key, CACHE_TTL_SECONDS, json.dumps(value))


def _cache_del(*keys: str) -> None:
    cache = get_cache()
    if keys:
        cache.delete(*keys)


def _cache_del_prefix(prefix: str) -> None:
    cache = get_cache()
    keys = list(cache.scan_iter(match=f"{prefix}*"))
    if keys:
        cache.delete(*keys)


def _parse_date(date_value: str | date_type) -> date_type:
    if isinstance(date_value, str):
        return date_type.fromisoformat(date_value)
    return date_value


def _rewrite_title_for_publish(title: str, target_date: date_type) -> str:
    target_token = target_date.isoformat()
    rewritten = DATE_TOKEN_RE.sub(target_token, title)
    return rewritten


def _note_snippet(value: Any, max_len: int = 180) -> str | None:
    if not isinstance(value, str):
        return None
    collapsed = WHITESPACE_RE.sub(" ", value).strip()
    if not collapsed:
        return None
    if len(collapsed) <= max_len:
        return collapsed
    return f"{collapsed[: max_len - 3].rstrip()}..."


def _fallback_display_name(player_token: str) -> str:
    tail = re.sub(r"[^A-Za-z0-9]", "", player_token)[-6:]
    if not tail:
        tail = "PLAYER"
    return f"Player {tail.upper()}"


def _normalize_display_name(value: str | None, *, player_token: str) -> str:
    candidate = (value or "").strip()
    if candidate:
        candidate = DISPLAY_NAME_ALLOWED_RE.sub("", candidate)
        candidate = WHITESPACE_RE.sub(" ", candidate).strip()
    if not candidate:
        candidate = _fallback_display_name(player_token)
    return candidate[:40]


def _generate_player_token() -> str:
    return f"plr_{uuid4().hex[:24]}"


def _slugify_public_name(value: str, *, player_token: str) -> str:
    base = PUBLIC_SLUG_RE.sub("-", value.strip().lower()).strip("-")
    if not base:
        base = PUBLIC_SLUG_RE.sub("-", _fallback_display_name(player_token).lower()).strip("-")
    return base[:80].strip("-") or f"player-{player_token[-6:].lower()}"


def _unique_public_slug(cur: Any, *, display_name: str, player_token: str, exclude_player_token: str | None = None) -> str:
    base = _slugify_public_name(display_name, player_token=player_token)
    candidate = base
    suffix = 2
    while True:
        if exclude_player_token is None:
            cur.execute(
                "SELECT 1 FROM player_profiles WHERE public_slug = %(public_slug)s LIMIT 1",
                {"public_slug": candidate},
            )
        else:
            cur.execute(
                "SELECT 1 FROM player_profiles WHERE public_slug = %(public_slug)s "
                "AND player_token <> %(exclude_player_token)s "
                "LIMIT 1",
                {
                    "public_slug": candidate,
                    "exclude_player_token": exclude_player_token,
                },
            )
        if cur.fetchone() is None:
            return candidate
        candidate = f"{base[: max(1, 80 - len(str(suffix)) - 1)]}-{suffix}"
        suffix += 1


def _player_profile_payload(row: dict[str, Any] | None, *, player_token: str) -> dict[str, Any]:
    default_name = _normalize_display_name(None, player_token=player_token)
    public_slug = ""
    if row:
        public_slug = str(row.get("public_slug") or "").strip()
    if not public_slug:
        public_slug = _slugify_public_name(default_name, player_token=player_token)
    return {
        "playerToken": player_token,
        "displayName": _normalize_display_name((row or {}).get("display_name"), player_token=player_token),
        "publicSlug": public_slug,
        "leaderboardVisible": bool((row or {}).get("leaderboard_visible", True)),
        "hasAccount": bool((row or {}).get("username")),
        "createdAt": row["created_at"].isoformat() if row and row.get("created_at") else None,
        "updatedAt": row["updated_at"].isoformat() if row and row.get("updated_at") else None,
    }


def _parse_cursor_offset(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        value = int(cursor)
    except ValueError:
        return 0
    return max(0, value)


def _compute_streak_lengths(dates: list[date_type]) -> tuple[int, int]:
    if not dates:
        return 0, 0
    ordered = sorted(set(dates))
    best = 1
    run = 1
    for index in range(1, len(ordered)):
        if ordered[index] == ordered[index - 1] + timedelta(days=1):
            run += 1
            best = max(best, run)
        else:
            run = 1

    current = 1
    for index in range(len(ordered) - 1, 0, -1):
        if ordered[index] == ordered[index - 1] + timedelta(days=1):
            current += 1
            continue
        break
    return current, best


def _empty_personal_stats_payload(
    *,
    session_ids: list[str],
    window_days: int,
    timezone: str,
    start_date: date_type,
) -> dict[str, Any]:
    streak_history = _empty_personal_stats_history(window_days=window_days, start_date=start_date)
    return {
        "sessionIds": session_ids,
        "windowDays": window_days,
        "timezone": timezone,
        "crossword": _empty_personal_stats_bucket(),
        "cryptic": _empty_personal_stats_bucket(),
        "connections": _empty_personal_stats_bucket(),
        "historyByGameType": {
            "crossword": [dict(day) for day in streak_history],
            "cryptic": [dict(day) for day in streak_history],
            "connections": [dict(day) for day in streak_history],
        },
    }


def _empty_personal_stats_bucket() -> dict[str, Any]:
    return {
        "pageViews": 0,
        "completions": 0,
        "completionRate": None,
        "medianSolveTimeMs": None,
        "cleanSolveRate": None,
        "streakCurrent": 0,
        "streakBest": 0,
    }


def _empty_personal_stats_history(*, window_days: int, start_date: date_type) -> list[dict[str, Any]]:
    return [
        {
            "date": (start_date + timedelta(days=offset)).isoformat(),
            "pageViews": 0,
            "completions": 0,
            "cleanCompletions": 0,
        }
        for offset in range(window_days)
    ]


def _merge_personal_stats_history(
    *,
    window_days: int,
    start_date: date_type,
    page_view_rows: list[dict[str, Any]] | None = None,
    completion_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    history = _empty_personal_stats_history(window_days=window_days, start_date=start_date)
    by_date = {item["date"]: item for item in history}

    for row in page_view_rows or []:
        day = row.get("day")
        if day is None:
            continue
        item = by_date.get(day.isoformat())
        if item is None:
            continue
        item["pageViews"] += int(row.get("page_views") or 0)

    for row in completion_rows or []:
        day = row.get("day")
        if day is None:
            continue
        item = by_date.get(day.isoformat())
        if item is None:
            continue
        item["completions"] += int(row.get("completions") or 0)
        item["cleanCompletions"] += int(row.get("clean_completions") or 0)

    return history


def _table_exists(cur: Any, table_name: str) -> bool:
    cur.execute(f"SELECT to_regclass('public.{table_name}') AS table_name", {})
    table_row = cur.fetchone() or {}
    return bool(table_row.get("table_name"))


def _build_personal_stats_bucket(
    *,
    page_views: int,
    page_view_puzzle_count: int,
    completions: int,
    completed_puzzles: int | None,
    clean_completions: int,
    median_solve_ms: int | None,
    solved_dates: list[date_type],
) -> dict[str, Any]:
    completed_puzzle_count = completions if completed_puzzles is None else completed_puzzles
    completion_rate = round(completed_puzzle_count / page_view_puzzle_count, 4) if page_view_puzzle_count > 0 else None
    clean_solve_rate = round(clean_completions / completions, 4) if completions > 0 else None
    streak_current, streak_best = _compute_streak_lengths(solved_dates)
    return {
        "pageViews": page_views,
        "completions": completions,
        "completionRate": completion_rate,
        "medianSolveTimeMs": median_solve_ms,
        "cleanSolveRate": clean_solve_rate,
        "streakCurrent": streak_current,
        "streakBest": streak_best,
    }


def _get_crossword_personal_stats_segment(
    *,
    cur: Any,
    session_ids: list[str],
    window_days: int,
    timezone: str,
    start_date: date_type,
    today: date_type,
    start_ts: datetime,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not _table_exists(cur, "crossword_feedback"):
        return _empty_personal_stats_bucket(), _empty_personal_stats_history(window_days=window_days, start_date=start_date)

    clean_completed_expr = (
        "("
        "COALESCE((NULLIF(event_value->>'revealWordCount', ''))::int, 0) + "
        "COALESCE((NULLIF(event_value->>'revealSquareCount', ''))::int, 0) + "
        "COALESCE((NULLIF(event_value->>'revealAllCount', ''))::int, 0) = 0 "
        "AND "
        "COALESCE((NULLIF(event_value->>'checkEntryCount', ''))::int, 0) + "
        "COALESCE((NULLIF(event_value->>'checkSquareCount', ''))::int, 0) + "
        "COALESCE((NULLIF(event_value->>'checkAllCount', ''))::int, 0) <= 2"
        ")"
    )
    clean_completed_series_expr = clean_completed_expr.replace("event_value", "ev.event_value")

    cur.execute(
        "SELECT "
        "COUNT(*) FILTER (WHERE event_type = 'page_view')::int AS page_view_count, "
        "COUNT(*) FILTER (WHERE event_type = 'completed')::int AS completed_count, "
        "COUNT(DISTINCT CASE WHEN event_type = 'page_view' THEN puzzle_id END)::int AS page_view_puzzle_count, "
        "COUNT(DISTINCT CASE WHEN event_type = 'completed' THEN puzzle_id END)::int AS completed_puzzle_count, "
        f"COUNT(*) FILTER (WHERE event_type = 'completed' AND {clean_completed_expr})::int AS clean_completed_count, "
        "PERCENTILE_CONT(0.5) WITHIN GROUP ("
        "  ORDER BY (event_value->>'solveMs')::double precision"
        ") FILTER ("
        "  WHERE event_type = 'completed' "
        "  AND (event_value->>'solveMs') ~ '^[0-9]+(\\.[0-9]+)?$'"
        ") AS median_solve_ms "
        "FROM crossword_feedback "
        "WHERE created_at >= %(start_ts)s "
        "AND session_id = ANY(%(session_ids)s)",
        {
            "start_ts": start_ts,
            "session_ids": session_ids,
        },
    )
    totals_row = cur.fetchone() or {}

    cur.execute(
        "WITH day_series AS ("
        "  SELECT generate_series(%(start_date)s::date, %(end_date)s::date, interval '1 day')::date AS day"
        "), events AS ("
        "  SELECT (created_at AT TIME ZONE %(timezone)s)::date AS day, event_type, event_value "
        "  FROM crossword_feedback "
        "  WHERE created_at >= %(start_ts)s "
        "    AND session_id = ANY(%(session_ids)s) "
        "    AND event_type IN ('page_view', 'completed')"
        ") "
        "SELECT ds.day, "
        "COUNT(*) FILTER (WHERE ev.event_type = 'page_view')::int AS page_views, "
        "COUNT(*) FILTER (WHERE ev.event_type = 'completed')::int AS completions, "
        f"COUNT(*) FILTER (WHERE ev.event_type = 'completed' AND {clean_completed_series_expr})::int AS clean_completions "
        "FROM day_series ds "
        "LEFT JOIN events ev ON ev.day = ds.day "
        "GROUP BY ds.day "
        "ORDER BY ds.day ASC",
        {
            "start_date": start_date,
            "end_date": today,
            "timezone": timezone,
            "start_ts": start_ts,
            "session_ids": session_ids,
        },
    )
    history_rows = cur.fetchall()

    cur.execute(
        "SELECT DISTINCT p.date AS solved_date "
        "FROM crossword_feedback cf "
        "JOIN puzzles p ON p.id = cf.puzzle_id "
        "WHERE cf.created_at >= %(start_ts)s "
        "AND cf.session_id = ANY(%(session_ids)s) "
        "AND cf.event_type = 'completed' "
        "ORDER BY solved_date ASC",
        {
            "start_ts": start_ts,
            "session_ids": session_ids,
        },
    )
    solved_rows = cur.fetchall()

    page_views = int(totals_row.get("page_view_count") or 0)
    completions = int(totals_row.get("completed_count") or 0)
    page_view_puzzle_count = int(totals_row.get("page_view_puzzle_count") or 0)
    completed_puzzle_count = int(totals_row.get("completed_puzzle_count") or 0)
    clean_completions = int(totals_row.get("clean_completed_count") or 0)
    median_solve_ms_value = totals_row.get("median_solve_ms")
    median_solve_ms = int(round(float(median_solve_ms_value))) if median_solve_ms_value is not None else None
    solved_dates = [row.get("solved_date") for row in solved_rows if row.get("solved_date") is not None]

    return (
        _build_personal_stats_bucket(
            page_views=page_views,
            page_view_puzzle_count=page_view_puzzle_count,
            completions=completions,
            completed_puzzles=completed_puzzle_count,
            clean_completions=clean_completions,
            median_solve_ms=median_solve_ms,
            solved_dates=solved_dates,
        ),
        [
            {
                "date": row["day"].isoformat(),
                "pageViews": int(row.get("page_views") or 0),
                "completions": int(row.get("completions") or 0),
                "cleanCompletions": int(row.get("clean_completions") or 0),
            }
            for row in history_rows
        ],
    )


def _get_competitive_personal_stats_segment(
    *,
    cur: Any,
    game_type: CompetitiveGameType,
    feedback_table: str,
    session_ids: list[str],
    window_days: int,
    start_date: date_type,
    end_date: date_type,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    page_view_totals: dict[str, Any] = {}
    page_view_rows: list[dict[str, Any]] = []
    submission_totals: dict[str, Any] = {}
    submission_rows: list[dict[str, Any]] = []

    if _table_exists(cur, feedback_table):
        cur.execute(
            f"SELECT "
            "COUNT(*) FILTER (WHERE fb.event_type = 'page_view')::int AS page_view_count, "
            "COUNT(DISTINCT CASE WHEN fb.event_type = 'page_view' THEN fb.puzzle_id END)::int AS page_view_puzzle_count "
            f"FROM {feedback_table} fb "
            "JOIN puzzles p ON p.id = fb.puzzle_id "
            "WHERE p.date >= %(start_date)s "
            "AND p.date <= %(end_date)s "
            "AND fb.session_id = ANY(%(session_ids)s)",
            {
                "start_date": start_date,
                "end_date": end_date,
                "session_ids": session_ids,
            },
        )
        page_view_totals = cur.fetchone() or {}

        cur.execute(
            f"SELECT p.date AS day, "
            "COUNT(*) FILTER (WHERE fb.event_type = 'page_view')::int AS page_views "
            f"FROM {feedback_table} fb "
            "JOIN puzzles p ON p.id = fb.puzzle_id "
            "WHERE p.date >= %(start_date)s "
            "AND p.date <= %(end_date)s "
            "AND fb.session_id = ANY(%(session_ids)s) "
            "GROUP BY p.date "
            "ORDER BY p.date ASC",
            {
                "start_date": start_date,
                "end_date": end_date,
                "session_ids": session_ids,
            },
        )
        page_view_rows = cur.fetchall()

    if _table_exists(cur, "leaderboard_submissions"):
        cur.execute(
            "SELECT "
            "COUNT(*) FILTER (WHERE completed = true)::int AS completed_count, "
            "COUNT(*) FILTER (WHERE completed = true AND COALESCE(used_assists, false) = false AND COALESCE(used_reveals, false) = false)::int AS clean_completed_count, "
            "PERCENTILE_CONT(0.5) WITHIN GROUP ("
            "  ORDER BY solve_time_ms::double precision"
            ") FILTER (WHERE completed = true AND solve_time_ms IS NOT NULL) AS median_solve_ms "
            "FROM leaderboard_submissions "
            "WHERE game_type = %(game_type)s "
            "AND puzzle_date >= %(start_date)s "
            "AND puzzle_date <= %(end_date)s "
            "AND session_id = ANY(%(session_ids)s)",
            {
                "game_type": game_type,
                "start_date": start_date,
                "end_date": end_date,
                "session_ids": session_ids,
            },
        )
        submission_totals = cur.fetchone() or {}

        cur.execute(
            "SELECT puzzle_date AS day, "
            "COUNT(*) FILTER (WHERE completed = true)::int AS completions, "
            "COUNT(*) FILTER (WHERE completed = true AND COALESCE(used_assists, false) = false AND COALESCE(used_reveals, false) = false)::int AS clean_completions "
            "FROM leaderboard_submissions "
            "WHERE game_type = %(game_type)s "
            "AND puzzle_date >= %(start_date)s "
            "AND puzzle_date <= %(end_date)s "
            "AND session_id = ANY(%(session_ids)s) "
            "GROUP BY puzzle_date "
            "ORDER BY puzzle_date ASC",
            {
                "game_type": game_type,
                "start_date": start_date,
                "end_date": end_date,
                "session_ids": session_ids,
            },
        )
        submission_rows = cur.fetchall()

    page_views = int(page_view_totals.get("page_view_count") or 0)
    page_view_puzzle_count = int(page_view_totals.get("page_view_puzzle_count") or 0)
    completions = int(submission_totals.get("completed_count") or 0)
    clean_completions = int(submission_totals.get("clean_completed_count") or 0)
    median_solve_ms_value = submission_totals.get("median_solve_ms")
    median_solve_ms = int(round(float(median_solve_ms_value))) if median_solve_ms_value is not None else None
    solved_dates = [row["day"] for row in submission_rows if row.get("completions")]

    return (
        _build_personal_stats_bucket(
            page_views=page_views,
            page_view_puzzle_count=page_view_puzzle_count,
            completions=completions,
            completed_puzzles=completions,
            clean_completions=clean_completions,
            median_solve_ms=median_solve_ms,
            solved_dates=solved_dates,
        ),
        _merge_personal_stats_history(
            window_days=window_days,
            start_date=start_date,
            page_view_rows=page_view_rows,
            completion_rows=submission_rows,
        ),
    )


def _get_connections_personal_stats_segment(
    *,
    cur: Any,
    session_ids: list[str],
    window_days: int,
    start_date: date_type,
    end_date: date_type,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not _table_exists(cur, "connections_feedback"):
        return _empty_personal_stats_bucket(), _empty_personal_stats_history(window_days=window_days, start_date=start_date)

    clean_completed_expr = (
        "(cf.event_value->>'mistakes') ~ '^[0-9]+$' "
        "AND COALESCE((cf.event_value->>'mistakes')::int, 0) = 0"
    )
    clean_completed_series_expr = clean_completed_expr.replace("cf.", "ev.")

    cur.execute(
        "SELECT "
        "COUNT(*) FILTER (WHERE cf.event_type = 'page_view')::int AS page_view_count, "
        "COUNT(*) FILTER (WHERE cf.event_type = 'completed')::int AS completed_count, "
        "COUNT(DISTINCT CASE WHEN cf.event_type = 'page_view' THEN cf.puzzle_id END)::int AS page_view_puzzle_count, "
        "COUNT(DISTINCT CASE WHEN cf.event_type = 'completed' THEN cf.puzzle_id END)::int AS completed_puzzle_count, "
        f"COUNT(*) FILTER (WHERE cf.event_type = 'completed' AND {clean_completed_expr})::int AS clean_completed_count "
        "FROM connections_feedback cf "
        "JOIN puzzles p ON p.id = cf.puzzle_id "
        "WHERE p.date >= %(start_date)s "
        "AND p.date <= %(end_date)s "
        "AND cf.session_id = ANY(%(session_ids)s)",
        {
            "start_date": start_date,
            "end_date": end_date,
            "session_ids": session_ids,
        },
    )
    totals_row = cur.fetchone() or {}

    cur.execute(
        "WITH day_series AS ("
        "  SELECT generate_series(%(start_date)s::date, %(end_date)s::date, interval '1 day')::date AS day"
        "), events AS ("
        "  SELECT p.date AS day, cf.event_type, cf.event_value "
        "  FROM connections_feedback cf "
        "  JOIN puzzles p ON p.id = cf.puzzle_id "
        "  WHERE p.date >= %(start_date)s "
        "    AND p.date <= %(end_date)s "
        "    AND cf.session_id = ANY(%(session_ids)s) "
        "    AND cf.event_type IN ('page_view', 'completed')"
        ") "
        "SELECT ds.day, "
        "COUNT(*) FILTER (WHERE ev.event_type = 'page_view')::int AS page_views, "
        "COUNT(*) FILTER (WHERE ev.event_type = 'completed')::int AS completions, "
        f"COUNT(*) FILTER (WHERE ev.event_type = 'completed' AND {clean_completed_series_expr})::int AS clean_completions "
        "FROM day_series ds "
        "LEFT JOIN events ev ON ev.day = ds.day "
        "GROUP BY ds.day "
        "ORDER BY ds.day ASC",
        {
            "start_date": start_date,
            "end_date": end_date,
            "session_ids": session_ids,
        },
    )
    history_rows = cur.fetchall()

    page_views = int(totals_row.get("page_view_count") or 0)
    completions = int(totals_row.get("completed_count") or 0)
    page_view_puzzle_count = int(totals_row.get("page_view_puzzle_count") or 0)
    completed_puzzle_count = int(totals_row.get("completed_puzzle_count") or 0)
    clean_completions = int(totals_row.get("clean_completed_count") or 0)
    solved_dates = [row["day"] for row in history_rows if row.get("completions")]

    return (
        _build_personal_stats_bucket(
            page_views=page_views,
            page_view_puzzle_count=page_view_puzzle_count,
            completions=completions,
            completed_puzzles=completed_puzzle_count,
            clean_completions=clean_completions,
            median_solve_ms=None,
            solved_dates=solved_dates,
        ),
        [
            {
                "date": row["day"].isoformat(),
                "pageViews": int(row.get("page_views") or 0),
                "completions": int(row.get("completions") or 0),
                "cleanCompletions": int(row.get("clean_completions") or 0),
            }
            for row in history_rows
        ],
    )


def _invalidate_puzzle_caches(
    game_type: PuzzleGameType,
    target_date: date_type,
    puzzle_id: str | None = None,
) -> None:
    _cache_del(_cache_key("puzzle:daily", game_type, target_date.isoformat()))
    _cache_del(_cache_key("puzzle:daily", game_type, "latest"))
    _cache_del_prefix(_cache_key("puzzle:archive", game_type))
    _cache_del_prefix(_cache_key("puzzle:reserve", game_type))
    if puzzle_id:
        _cache_del(_cache_key("puzzle:id", puzzle_id))
        _cache_del(_cache_key("puzzle:meta", puzzle_id))


def _row_to_puzzle(row: dict[str, Any]) -> PuzzleDict:
    return {
        "id": row["id"],
        "date": row["date"].isoformat(),
        "gameType": row["game_type"],
        "title": row["title"],
        "publishedAt": row["published_at"].isoformat() if row["published_at"] else None,
        "timezone": row["timezone"],
        "grid": row["grid"],
        "entries": row["entries"],
        "metadata": row["metadata"],
    }


def get_puzzle_by_date(
    game_type: PuzzleGameType,
    date: str | None,
    timezone: str = "Europe/London",
) -> PuzzleDict | None:
    today_token = datetime.now(ZoneInfo(timezone)).date().isoformat()
    cache_key = _cache_key("puzzle:daily", game_type, date or f"latest:{today_token}")
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    query = (
        "SELECT id, date, game_type, title, published_at, timezone, grid, entries, metadata "
        "FROM puzzles WHERE game_type = %(game_type)s AND published_at IS NOT NULL "
    )
    params: dict[str, Any] = {"game_type": game_type}

    if date:
        query += "AND date = %(date)s "
        params["date"] = date
    else:
        query += "AND date <= %(today)s "
        params["today"] = datetime.now(ZoneInfo(timezone)).date()
    query += "ORDER BY date DESC LIMIT 1"

    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, params)
            row = cur.fetchone()
    if not row:
        return None
    puzzle = _row_to_puzzle(row)
    _cache_set(cache_key, puzzle)
    return puzzle


def get_puzzle_by_id(puzzle_id: str) -> PuzzleDict | None:
    cache_key = _cache_key("puzzle:id", puzzle_id)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id, date, game_type, title, published_at, timezone, grid, entries, metadata "
                "FROM puzzles WHERE id = %(id)s AND published_at IS NOT NULL",
                {"id": puzzle_id},
            )
            row = cur.fetchone()
    if not row:
        return None
    puzzle = _row_to_puzzle(row)
    _cache_set(cache_key, puzzle)
    return puzzle


def get_archive(
    game_type: PuzzleGameType | None = None,
    limit: int = 30,
    cursor: str | None = None,
    difficulty: Literal["easy", "medium", "hard"] | None = None,
    title_query: str | None = None,
    theme_tags: list[str] | None = None,
    date_from: str | date_type | None = None,
    date_to: str | date_type | None = None,
    include_connections: bool = True,
) -> dict[str, Any]:
    normalized_theme_tags = sorted(
        {
            str(tag).strip().lower()
            for tag in (theme_tags or [])
            if str(tag).strip()
        }
    )
    normalized_title = (title_query or "").strip()
    parsed_date_from = _parse_date(date_from) if date_from else None
    parsed_date_to = _parse_date(date_to) if date_to else None

    cache_key = _cache_key(
        "puzzle:archive",
        game_type or "all",
        str(limit),
        cursor or "none",
        difficulty or "any",
        normalized_title or "none",
        ",".join(normalized_theme_tags) or "none",
        parsed_date_from.isoformat() if parsed_date_from else "none",
        parsed_date_to.isoformat() if parsed_date_to else "none",
    )
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    page_limit = max(1, min(limit, 100))
    params: dict[str, Any] = {"limit_plus_one": page_limit + 1}
    query = (
        "SELECT id, date, game_type, title, metadata->>'difficulty' AS difficulty, metadata->>'notes' AS notes, published_at "
        "FROM puzzles WHERE published_at IS NOT NULL "
    )
    if game_type is not None:
        query += "AND game_type = %(game_type)s "
        params["game_type"] = game_type
    elif not include_connections:
        query += "AND game_type <> 'connections' "
    if difficulty is not None:
        query += "AND metadata->>'difficulty' = %(difficulty)s "
        params["difficulty"] = difficulty
    if normalized_title:
        query += "AND title ILIKE %(title_query)s "
        params["title_query"] = f"%{normalized_title}%"
    if parsed_date_from is not None:
        query += "AND date >= %(date_from)s "
        params["date_from"] = parsed_date_from
    if parsed_date_to is not None:
        query += "AND date <= %(date_to)s "
        params["date_to"] = parsed_date_to
    if normalized_theme_tags:
        query += (
            "AND EXISTS ("
            "  SELECT 1 "
            "  FROM jsonb_array_elements_text(COALESCE((metadata->'themeTags')::jsonb, '[]'::jsonb)) AS theme_tag "
            "  WHERE lower(theme_tag) = ANY(%(theme_tags)s)"
            ") "
        )
        params["theme_tags"] = normalized_theme_tags
    if cursor:
        try:
            cursor_date_str, cursor_id = cursor.split("|", 1)
            cursor_date = date_type.fromisoformat(cursor_date_str)
        except ValueError as exc:
            raise ValueError("Invalid cursor format. Expected '<YYYY-MM-DD>|<puzzle_id>'.") from exc
        query += "AND (date < %(cursor_date)s OR (date = %(cursor_date)s AND id < %(cursor_id)s)) "
        params["cursor_date"] = cursor_date
        params["cursor_id"] = cursor_id
    query += "ORDER BY date DESC, id DESC LIMIT %(limit_plus_one)s"
    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

    has_more = len(rows) > page_limit
    visible_rows = rows[:page_limit]

    items = [
        {
            "id": row["id"],
            "date": row["date"].isoformat(),
            "gameType": row["game_type"],
            "title": row["title"],
            "difficulty": row["difficulty"],
            "publishedAt": row["published_at"].isoformat() if row["published_at"] else None,
            "noteSnippet": _note_snippet(row.get("notes")),
        }
        for row in visible_rows
    ]

    next_cursor = None
    if has_more and visible_rows:
        last = visible_rows[-1]
        next_cursor = f"{last['date'].isoformat()}|{last['id']}"

    payload = {"items": items, "cursor": next_cursor, "hasMore": has_more}
    _cache_set(cache_key, payload)
    return payload


def publish_next_from_reserve(
    date_value: str | date_type,
    game_type: PuzzleGameType,
    timezone: str,
    reserve_threshold: int = 5,
    contest_mode: bool | None = None,
) -> dict[str, Any]:
    target_date = _parse_date(date_value)
    published_at = datetime.now(ZoneInfo(timezone))

    status: PublishStatus = "reserve_empty"
    puzzle_id: str | None = None
    source_date: date_type | None = None
    contest_mode_applied: bool | None = None
    alert_created = False

    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id FROM puzzles "
                "WHERE game_type = %(game_type)s AND date = %(date)s AND published_at IS NOT NULL "
                "LIMIT 1",
                {"game_type": game_type, "date": target_date},
            )
            existing = cur.fetchone()
            if existing:
                status = "already_published"
                puzzle_id = cast(str, existing["id"])
            else:
                cur.execute(
                    "SELECT id, date, title FROM puzzles "
                    "  WHERE game_type = %(game_type)s AND published_at IS NULL "
                    "    AND date >= %(target_date)s "
                    "  ORDER BY "
                    "    CASE "
                    "      WHEN %(game_type)s = 'crossword' "
                    "        AND COALESCE(metadata->>'generatorVersion', '') IN ("
                    "          'seed-reserve-0.1', 'reserve-generator-0.1', 'reserve-generator-0.2', '0.1.0'"
                    "        ) THEN 1 "
                    "      WHEN %(game_type)s = 'cryptic' "
                    "        AND COALESCE(metadata->>'generatorVersion', '') = 'reserve-generator-0.1' THEN 1 "
                    "      ELSE 0 "
                    "    END ASC, "
                    "    CASE WHEN date = %(target_date)s THEN 0 ELSE 1 END ASC, "
                    "    date ASC "
                    "  FOR UPDATE SKIP LOCKED LIMIT 1",
                    {
                        "game_type": game_type,
                        "target_date": target_date,
                    },
                )
                candidate = cur.fetchone()
                if candidate:
                    new_title = _rewrite_title_for_publish(
                        cast(str, candidate["title"]),
                        target_date,
                    )
                    cur.execute(
                        "UPDATE puzzles "
                        "SET published_at = %(published_at)s, timezone = %(timezone)s, date = %(target_date)s, title = %(title)s "
                        "WHERE id = %(id)s "
                        "RETURNING id",
                        {
                            "published_at": published_at,
                            "timezone": timezone,
                            "target_date": target_date,
                            "title": new_title,
                            "id": candidate["id"],
                        },
                    )
                    row = cur.fetchone()
                    if row:
                        status = "published"
                        puzzle_id = cast(str, row["id"])
                        source_date = cast(date_type, candidate["date"])

            if puzzle_id and contest_mode is not None:
                cur.execute(
                    "UPDATE puzzles "
                    "SET metadata = jsonb_set(COALESCE(metadata::jsonb, '{}'::jsonb), '{contestMode}', to_jsonb(%(contest_mode)s::boolean), true)::json "
                    "WHERE id = %(id)s "
                    "RETURNING (metadata::jsonb->>'contestMode')::boolean AS contest_mode",
                    {
                        "id": puzzle_id,
                        "contest_mode": contest_mode,
                    },
                )
                updated_row = cur.fetchone()
                if updated_row:
                    contest_mode_applied = bool(updated_row.get("contest_mode"))

            cur.execute(
                "SELECT COUNT(*) AS reserve_count "
                "FROM puzzles "
                "WHERE game_type = %(game_type)s AND published_at IS NULL AND date > %(target_date)s",
                {"game_type": game_type, "target_date": target_date},
            )
            reserve_count = int(cur.fetchone()["reserve_count"])
            low_reserve = reserve_count < reserve_threshold

            if low_reserve:
                dedupe_key = f"reserve_low:{game_type}:{target_date.isoformat()}"
                details = json.dumps(
                    {
                        "targetDate": target_date.isoformat(),
                        "reserveCount": reserve_count,
                        "reserveThreshold": reserve_threshold,
                    }
                )
                cur.execute(
                    "INSERT INTO operational_alerts "
                    "(alert_type, game_type, severity, message, details, dedupe_key) "
                    "VALUES (%(alert_type)s, %(game_type)s, %(severity)s, %(message)s, %(details)s::json, %(dedupe_key)s) "
                    "ON CONFLICT (dedupe_key) DO NOTHING "
                    "RETURNING id",
                    {
                        "alert_type": "reserve_low",
                        "game_type": game_type,
                        "severity": "warning",
                        "message": (
                            f"Reserve below threshold for {game_type}: "
                            f"{reserve_count} remaining (threshold {reserve_threshold})"
                        ),
                        "details": details,
                        "dedupe_key": dedupe_key,
                    },
                )
                alert_created = cur.fetchone() is not None

        conn.commit()

    if status == "published":
        _invalidate_puzzle_caches(game_type, target_date, puzzle_id)
    elif status == "already_published":
        _invalidate_puzzle_caches(game_type, target_date, puzzle_id)

    if alert_created:
        logger.warning(
            "Low reserve alert created: game_type=%s date=%s threshold=%s",
            game_type,
            target_date.isoformat(),
            reserve_threshold,
        )
        notify_external_alert(
            event_type="reserve_low",
            severity="warning",
            message=(
                f"Reserve below threshold for {game_type}: "
                f"{reserve_count} remaining (threshold {reserve_threshold})"
            ),
            details={
                "gameType": game_type,
                "date": target_date.isoformat(),
                "reserveCount": reserve_count,
                "reserveThreshold": reserve_threshold,
                "dedupeKey": f"reserve_low:{game_type}:{target_date.isoformat()}",
            },
        )

    return {
        "status": status,
        "gameType": game_type,
        "date": target_date.isoformat(),
        "puzzleId": puzzle_id,
        "sourceDate": source_date.isoformat() if source_date else None,
        "contestMode": contest_mode_applied,
        "reserveCount": reserve_count,
        "reserveThreshold": reserve_threshold,
        "lowReserve": reserve_count < reserve_threshold,
        "alertCreated": alert_created,
    }


def publish_puzzle(
    date_value: str | date_type,
    game_type: PuzzleGameType,
    timezone: str,
    contest_mode: bool | None = None,
) -> bool:
    result = publish_next_from_reserve(
        date_value=date_value,
        game_type=game_type,
        timezone=timezone,
        reserve_threshold=0,
        contest_mode=contest_mode,
    )
    return result["status"] in {"published", "already_published"}


def rollback_daily_publish(
    *,
    date_value: str | date_type,
    game_type: PuzzleGameType,
    timezone: str,
    executed_by: str = "admin",
    reason: str = "manual rollback",
    source_date: str | date_type | None = None,
) -> dict[str, Any]:
    target_date = _parse_date(date_value)
    selected_source_date = _parse_date(source_date) if source_date is not None else None
    now = datetime.now(ZoneInfo(timezone))
    rollback_job_id = f"job_publish_rollback_{game_type}_{uuid4().hex[:10]}"

    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id, title, metadata "
                "FROM puzzles "
                "WHERE game_type = %(game_type)s AND date = %(date)s AND published_at IS NOT NULL "
                "LIMIT 1 "
                "FOR UPDATE",
                {"game_type": game_type, "date": target_date},
            )
            current_daily = cur.fetchone()

            if selected_source_date is not None:
                cur.execute(
                    "SELECT id, date, title, timezone, grid, entries, metadata "
                    "FROM puzzles "
                    "WHERE game_type = %(game_type)s AND date = %(source_date)s AND published_at IS NOT NULL "
                    "LIMIT 1",
                    {"game_type": game_type, "source_date": selected_source_date},
                )
            else:
                cur.execute(
                    "SELECT id, date, title, timezone, grid, entries, metadata "
                    "FROM puzzles "
                    "WHERE game_type = %(game_type)s AND date < %(date)s AND published_at IS NOT NULL "
                    "ORDER BY date DESC LIMIT 1",
                    {"game_type": game_type, "date": target_date},
                )
            source = cur.fetchone()
            if source is None:
                raise ValueError("No published source puzzle available for rollback")

            source_meta = source["metadata"] if isinstance(source.get("metadata"), dict) else {}
            rollback_data = {
                "executedAt": now.isoformat(),
                "executedBy": executed_by,
                "reason": reason,
                "sourcePuzzleId": source["id"],
                "sourceDate": source["date"].isoformat(),
            }
            source_meta = dict(source_meta)
            source_meta["rollback"] = rollback_data
            source_meta["generatorVersion"] = "rollback-playbook-1.0"

            if current_daily is not None:
                daily_puzzle_id = current_daily["id"]
                rollback_data["targetPuzzleId"] = daily_puzzle_id
                cur.execute(
                    "UPDATE puzzles "
                    "SET title = %(title)s, timezone = %(timezone)s, grid = %(grid)s, entries = %(entries)s, metadata = %(metadata)s::json "
                    "WHERE id = %(id)s",
                    {
                        "title": _rewrite_title_for_publish(cast(str, source["title"]), target_date),
                        "timezone": timezone,
                        "grid": json.dumps(source["grid"]),
                        "entries": json.dumps(source["entries"]),
                        "metadata": json.dumps(source_meta),
                        "id": daily_puzzle_id,
                    },
                )
                action = "replaced_existing_daily"
            else:
                daily_puzzle_id = f"puz_rb_{game_type}_{target_date.isoformat().replace('-', '')}_{uuid4().hex[:8]}"
                rollback_data["targetPuzzleId"] = daily_puzzle_id
                cur.execute(
                    "INSERT INTO puzzles "
                    "(id, date, game_type, title, published_at, timezone, grid, entries, metadata) "
                    "VALUES ("
                    "%(id)s, %(date)s, %(game_type)s, %(title)s, %(published_at)s, %(timezone)s, "
                    "%(grid)s::json, %(entries)s::json, %(metadata)s::json"
                    ")",
                    {
                        "id": daily_puzzle_id,
                        "date": target_date,
                        "game_type": game_type,
                        "title": _rewrite_title_for_publish(cast(str, source["title"]), target_date),
                        "published_at": now,
                        "timezone": timezone,
                        "grid": json.dumps(source["grid"]),
                        "entries": json.dumps(source["entries"]),
                        "metadata": json.dumps(source_meta),
                    },
                )
                action = "inserted_fallback_daily"

            cur.execute(
                "SELECT COUNT(*) AS reserve_count "
                "FROM puzzles "
                "WHERE game_type = %(game_type)s AND published_at IS NULL AND date > %(target_date)s",
                {"game_type": game_type, "target_date": target_date},
            )
            reserve_count = int(cur.fetchone()["reserve_count"])

            logs_payload = {
                "action": action,
                "targetPuzzleId": daily_puzzle_id,
                "sourcePuzzleId": source["id"],
                "sourceDate": source["date"].isoformat(),
                "reason": reason,
                "executedBy": executed_by,
                "targetDate": target_date.isoformat(),
            }
            cur.execute(
                "INSERT INTO generation_jobs "
                "(id, type, date, status, started_at, finished_at, logs_url, model_version) "
                "VALUES ("
                "%(id)s, %(type)s, %(date)s, %(status)s, %(started_at)s, %(finished_at)s, %(logs_url)s, %(model_version)s"
                ")",
                {
                    "id": rollback_job_id,
                    "type": "publish_rollback",
                    "date": target_date,
                    "status": "completed",
                    "started_at": now,
                    "finished_at": now,
                    "logs_url": json.dumps(logs_payload, separators=(",", ":"), ensure_ascii=True),
                    "model_version": "rollback-playbook-1.0",
                },
            )
        conn.commit()

    _invalidate_puzzle_caches(game_type, target_date, daily_puzzle_id)
    artifact_ref = write_json_artifact(
        artifact_type="rollback-events",
        object_id=rollback_job_id,
        payload={
            "jobId": rollback_job_id,
            "gameType": game_type,
            "date": target_date.isoformat(),
            "action": action,
            "targetPuzzleId": daily_puzzle_id,
            "sourcePuzzleId": source["id"],
            "sourceDate": source["date"].isoformat(),
            "executedAt": now.isoformat(),
            "executedBy": executed_by,
            "reason": reason,
        },
    )
    notify_external_alert(
        event_type="publish_rollback_executed",
        severity="warning",
        message=f"Rollback executed for {game_type} on {target_date.isoformat()}",
        details={
            "jobId": rollback_job_id,
            "gameType": game_type,
            "date": target_date.isoformat(),
            "action": action,
            "targetPuzzleId": daily_puzzle_id,
            "sourcePuzzleId": source["id"],
            "sourceDate": source["date"].isoformat(),
            "reserveCount": reserve_count,
            "artifactRef": artifact_ref,
        },
    )

    return {
        "jobId": rollback_job_id,
        "status": "completed",
        "action": action,
        "gameType": game_type,
        "date": target_date.isoformat(),
        "targetPuzzleId": daily_puzzle_id,
        "sourcePuzzleId": source["id"],
        "sourceDate": source["date"].isoformat(),
        "reserveCount": reserve_count,
        "artifactRef": artifact_ref,
    }


def get_reserve_status(
    game_type: PuzzleGameType,
    timezone: str,
    reserve_threshold: int,
) -> dict[str, Any]:
    today = datetime.now(ZoneInfo(timezone)).date()
    cache_key = _cache_key("puzzle:reserve", game_type, today.isoformat(), str(reserve_threshold))
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT COUNT(*) AS remaining, MIN(date) AS next_date "
                "FROM puzzles "
                "WHERE game_type = %(game_type)s AND published_at IS NULL AND date > %(today)s",
                {"game_type": game_type, "today": today},
            )
            row = cur.fetchone()
    remaining = int(row["remaining"] or 0)
    next_date = row["next_date"].isoformat() if row["next_date"] else None
    payload = {
        "gameType": game_type,
        "today": today.isoformat(),
        "remaining": remaining,
        "threshold": reserve_threshold,
        "lowReserve": remaining < reserve_threshold,
        "nextDate": next_date,
    }
    _cache_set(cache_key, payload)
    return payload


def get_operational_alerts(
    game_type: PuzzleGameType | None = None,
    alert_type: str | None = None,
    limit: int = 50,
    include_resolved: bool = False,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"limit": max(1, min(limit, 200))}
    where: list[str] = []
    if not include_resolved:
        where.append("resolved_at IS NULL")
    if game_type:
        where.append("game_type = %(game_type)s")
        params["game_type"] = game_type
    if alert_type:
        where.append("alert_type = %(alert_type)s")
        params["alert_type"] = alert_type

    query = (
        "SELECT id, alert_type, game_type, severity, message, details, dedupe_key, "
        "resolved_at, resolved_by, resolution_note, created_at "
        "FROM operational_alerts "
    )
    if where:
        query += "WHERE " + " AND ".join(where) + " "
    query += "ORDER BY created_at DESC LIMIT %(limit)s"

    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

    return [
        {
            "id": row["id"],
            "alertType": row["alert_type"],
            "gameType": row["game_type"],
            "severity": row["severity"],
            "message": row["message"],
            "details": row["details"],
            "dedupeKey": row["dedupe_key"],
            "resolvedAt": row["resolved_at"].isoformat() if row["resolved_at"] else None,
            "resolvedBy": row["resolved_by"],
            "resolutionNote": row["resolution_note"],
            "createdAt": row["created_at"].isoformat() if row["created_at"] else None,
        }
        for row in rows
    ]


def resolve_operational_alert(
    alert_id: int,
    resolved_by: str,
    resolution_note: str | None = None,
) -> dict[str, Any] | None:
    now = datetime.now(ZoneInfo("UTC"))
    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "UPDATE operational_alerts "
                "SET resolved_at = %(resolved_at)s, resolved_by = %(resolved_by)s, resolution_note = %(resolution_note)s "
                "WHERE id = %(id)s "
                "RETURNING id, alert_type, game_type, severity, message, details, dedupe_key, "
                "resolved_at, resolved_by, resolution_note, created_at",
                {
                    "resolved_at": now,
                    "resolved_by": resolved_by,
                    "resolution_note": resolution_note,
                    "id": alert_id,
                },
            )
            row = cur.fetchone()
        conn.commit()
    if not row:
        return None
    return {
        "id": row["id"],
        "alertType": row["alert_type"],
        "gameType": row["game_type"],
        "severity": row["severity"],
        "message": row["message"],
        "details": row["details"],
        "dedupeKey": row["dedupe_key"],
        "resolvedAt": row["resolved_at"].isoformat() if row["resolved_at"] else None,
        "resolvedBy": row["resolved_by"],
        "resolutionNote": row["resolution_note"],
        "createdAt": row["created_at"].isoformat() if row["created_at"] else None,
    }


def list_generation_jobs(
    status: str | None = None,
    job_type: str | None = None,
    date: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"limit": max(1, min(limit, 500))}
    where: list[str] = []
    if status:
        where.append("status = %(status)s")
        params["status"] = status
    if job_type:
        where.append("type = %(job_type)s")
        params["job_type"] = job_type
    if date:
        where.append("date = %(date)s")
        params["date"] = date

    query = (
        "SELECT id, type, date, status, started_at, finished_at, logs_url, model_version, created_at "
        "FROM generation_jobs "
    )
    if where:
        query += "WHERE " + " AND ".join(where) + " "
    query += "ORDER BY created_at DESC LIMIT %(limit)s"

    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

    return [
        {
            "id": row["id"],
            "type": row["type"],
            "date": row["date"].isoformat() if row["date"] else None,
            "status": row["status"],
            "startedAt": row["started_at"].isoformat() if row["started_at"] else None,
            "finishedAt": row["finished_at"].isoformat() if row["finished_at"] else None,
            "logs": row["logs_url"],
            "modelVersion": row["model_version"],
            "createdAt": row["created_at"].isoformat() if row["created_at"] else None,
        }
        for row in rows
    ]


def get_generation_job(job_id: str) -> dict[str, Any] | None:
    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id, type, date, status, started_at, finished_at, logs_url, model_version, created_at "
                "FROM generation_jobs WHERE id = %(id)s",
                {"id": job_id},
            )
            row = cur.fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "type": row["type"],
        "date": row["date"].isoformat() if row["date"] else None,
        "status": row["status"],
        "startedAt": row["started_at"].isoformat() if row["started_at"] else None,
        "finishedAt": row["finished_at"].isoformat() if row["finished_at"] else None,
        "logs": row["logs_url"],
        "modelVersion": row["model_version"],
        "createdAt": row["created_at"].isoformat() if row["created_at"] else None,
    }


def update_puzzle_review_status(
    *,
    puzzle_id: str,
    status: Literal["approved", "rejected"],
    reviewed_by: str,
    note: str | None = None,
) -> dict[str, Any] | None:
    reviewed_at = datetime.now(ZoneInfo("UTC"))
    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id, date, game_type, published_at, metadata "
                "FROM puzzles WHERE id = %(id)s "
                "FOR UPDATE",
                {"id": puzzle_id},
            )
            row = cur.fetchone()
            if not row:
                return None

            metadata = row["metadata"] if isinstance(row.get("metadata"), dict) else {}
            review_payload = {
                "status": status,
                "reviewedAt": reviewed_at.isoformat(),
                "reviewedBy": reviewed_by,
                "note": note,
            }
            metadata["reviewStatus"] = status
            metadata["review"] = review_payload

            cur.execute(
                "UPDATE puzzles "
                "SET metadata = %(metadata)s::json "
                "WHERE id = %(id)s",
                {"metadata": json.dumps(metadata), "id": puzzle_id},
            )
        conn.commit()

    game_type = cast(PuzzleGameType, row["game_type"])
    puzzle_date = cast(date_type, row["date"])
    _invalidate_puzzle_caches(game_type, puzzle_date, puzzle_id)

    return {
        "id": row["id"],
        "date": puzzle_date.isoformat(),
        "gameType": game_type,
        "publishedAt": row["published_at"].isoformat() if row["published_at"] else None,
        "reviewStatus": status,
        "reviewedAt": reviewed_at.isoformat(),
        "reviewedBy": reviewed_by,
        "note": note,
    }


def get_metadata(puzzle_id: str) -> dict[str, Any] | None:
    cache_key = _cache_key("puzzle:meta", puzzle_id)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id, date, game_type, title, metadata->>'difficulty' AS difficulty, metadata->>'notes' AS notes, published_at "
                "FROM puzzles WHERE id = %(id)s AND published_at IS NOT NULL",
                {"id": puzzle_id},
            )
            row = cur.fetchone()
    if not row:
        return None
    payload = {
        "id": row["id"],
        "date": row["date"].isoformat(),
        "gameType": row["game_type"],
        "title": row["title"],
        "difficulty": row["difficulty"],
        "publishedAt": row["published_at"].isoformat() if row["published_at"] else None,
        "noteSnippet": _note_snippet(row.get("notes")),
    }
    _cache_set(cache_key, payload)
    return payload


def create_cryptic_feedback(
    *,
    puzzle_id: str,
    event_type: str,
    session_id: str | None,
    event_value: dict[str, Any] | None,
    candidate_id: int | None,
    client_ts: datetime | None,
    user_agent: str | None,
) -> dict[str, Any] | None:
    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id FROM puzzles WHERE id = %(id)s AND game_type = 'cryptic' AND published_at IS NOT NULL",
                {"id": puzzle_id},
            )
            puzzle_row = cur.fetchone()
            if not puzzle_row:
                return None

            candidate_to_store = candidate_id
            if candidate_id is not None:
                cur.execute(
                    "SELECT id FROM cryptic_candidates WHERE id = %(id)s AND puzzle_id = %(puzzle_id)s",
                    {"id": candidate_id, "puzzle_id": puzzle_id},
                )
                candidate_row = cur.fetchone()
                if not candidate_row:
                    candidate_to_store = None

            cur.execute(
                "INSERT INTO cryptic_feedback ("
                "puzzle_id, candidate_id, event_type, session_id, event_value, client_ts, user_agent"
                ") VALUES ("
                "%(puzzle_id)s, %(candidate_id)s, %(event_type)s, %(session_id)s, %(event_value)s::json, %(client_ts)s, %(user_agent)s"
                ") RETURNING id, puzzle_id, candidate_id, event_type, session_id, event_value, client_ts, created_at",
                {
                    "puzzle_id": puzzle_id,
                    "candidate_id": candidate_to_store,
                    "event_type": event_type,
                    "session_id": session_id,
                    "event_value": json.dumps(event_value or {}),
                    "client_ts": client_ts,
                    "user_agent": user_agent,
                },
            )
            row = cur.fetchone()
        conn.commit()

    if not row:
        return None
    return {
        "id": row["id"],
        "puzzleId": row["puzzle_id"],
        "candidateId": row["candidate_id"],
        "eventType": row["event_type"],
        "sessionId": row["session_id"],
        "eventValue": row["event_value"],
        "clientTs": row["client_ts"].isoformat() if row["client_ts"] else None,
        "createdAt": row["created_at"].isoformat() if row["created_at"] else None,
    }


def create_cryptic_clue_feedback(
    *,
    puzzle_id: str,
    entry_id: str,
    rating: Literal["up", "down"],
    reason_tags: list[str] | None,
    session_id: str,
    candidate_id: int | None,
    mechanism: str | None,
    clue_text: str | None,
    client_ts: datetime | None,
    user_agent: str | None,
) -> tuple[dict[str, Any] | None, bool]:
    clean_reasons = [
        tag
        for tag in dict.fromkeys(str(tag).strip().lower() for tag in (reason_tags or []))
        if tag in CLUE_FEEDBACK_REASON_TAGS
    ][:5]
    feedback_payload = {
        "entryId": str(entry_id).strip() or "a1",
        "rating": rating,
        "reasons": clean_reasons,
        "mechanism": (str(mechanism).strip().lower() or None) if mechanism else None,
        "clueText": str(clue_text or "").strip()[:500],
    }

    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id FROM puzzles WHERE id = %(id)s AND game_type = 'cryptic' AND published_at IS NOT NULL",
                {"id": puzzle_id},
            )
            puzzle_row = cur.fetchone()
            if not puzzle_row:
                return None, False

            candidate_to_store = candidate_id
            if candidate_id is not None:
                cur.execute(
                    "SELECT id FROM cryptic_candidates WHERE id = %(id)s AND puzzle_id = %(puzzle_id)s",
                    {"id": candidate_id, "puzzle_id": puzzle_id},
                )
                candidate_row = cur.fetchone()
                if not candidate_row:
                    candidate_to_store = None

            cur.execute(
                "SELECT id, puzzle_id, candidate_id, event_type, session_id, event_value, client_ts, created_at "
                "FROM cryptic_feedback "
                "WHERE puzzle_id = %(puzzle_id)s "
                "AND event_type = 'clue_feedback' "
                "AND session_id = %(session_id)s "
                "AND event_value->>'entryId' = %(entry_id)s "
                "LIMIT 1",
                {"puzzle_id": puzzle_id, "session_id": session_id, "entry_id": feedback_payload["entryId"]},
            )
            existing = cur.fetchone()
            if existing:
                return (
                    {
                        "id": existing["id"],
                        "puzzleId": existing["puzzle_id"],
                        "candidateId": existing["candidate_id"],
                        "eventType": existing["event_type"],
                        "sessionId": existing["session_id"],
                        "eventValue": existing["event_value"],
                        "clientTs": existing["client_ts"].isoformat() if existing["client_ts"] else None,
                        "createdAt": existing["created_at"].isoformat() if existing["created_at"] else None,
                    },
                    True,
                )

            cur.execute(
                "INSERT INTO cryptic_feedback ("
                "puzzle_id, candidate_id, event_type, session_id, event_value, client_ts, user_agent"
                ") VALUES ("
                "%(puzzle_id)s, %(candidate_id)s, 'clue_feedback', %(session_id)s, %(event_value)s::json, %(client_ts)s, %(user_agent)s"
                ") RETURNING id, puzzle_id, candidate_id, event_type, session_id, event_value, client_ts, created_at",
                {
                    "puzzle_id": puzzle_id,
                    "candidate_id": candidate_to_store,
                    "session_id": session_id,
                    "event_value": json.dumps(feedback_payload),
                    "client_ts": client_ts,
                    "user_agent": user_agent,
                },
            )
            row = cur.fetchone()
        conn.commit()

    if not row:
        return None, False
    return (
        {
            "id": row["id"],
            "puzzleId": row["puzzle_id"],
            "candidateId": row["candidate_id"],
            "eventType": row["event_type"],
            "sessionId": row["session_id"],
            "eventValue": row["event_value"],
            "clientTs": row["client_ts"].isoformat() if row["client_ts"] else None,
            "createdAt": row["created_at"].isoformat() if row["created_at"] else None,
        },
        False,
    )


def create_crossword_feedback(
    *,
    puzzle_id: str,
    event_type: str,
    session_id: str | None,
    event_value: dict[str, Any] | None,
    client_ts: datetime | None,
    user_agent: str | None,
) -> dict[str, Any] | None:
    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id FROM puzzles WHERE id = %(id)s AND game_type = 'crossword' AND published_at IS NOT NULL",
                {"id": puzzle_id},
            )
            puzzle_row = cur.fetchone()
            if not puzzle_row:
                return None

            cur.execute(
                "INSERT INTO crossword_feedback ("
                "puzzle_id, event_type, session_id, event_value, client_ts, user_agent"
                ") VALUES ("
                "%(puzzle_id)s, %(event_type)s, %(session_id)s, %(event_value)s::json, %(client_ts)s, %(user_agent)s"
                ") RETURNING id, puzzle_id, event_type, session_id, event_value, client_ts, created_at",
                {
                    "puzzle_id": puzzle_id,
                    "event_type": event_type,
                    "session_id": session_id,
                    "event_value": json.dumps(event_value or {}),
                    "client_ts": client_ts,
                    "user_agent": user_agent,
                },
            )
            row = cur.fetchone()
        conn.commit()

    if not row:
        return None
    return {
        "id": row["id"],
        "puzzleId": row["puzzle_id"],
        "eventType": row["event_type"],
        "sessionId": row["session_id"],
        "eventValue": row["event_value"],
        "clientTs": row["client_ts"].isoformat() if row["client_ts"] else None,
        "createdAt": row["created_at"].isoformat() if row["created_at"] else None,
    }


def create_connections_feedback(
    *,
    puzzle_id: str,
    event_type: str,
    session_id: str | None,
    event_value: dict[str, Any] | None,
    client_ts: datetime | None,
    user_agent: str | None,
) -> dict[str, Any] | None:
    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id FROM puzzles WHERE id = %(id)s AND game_type = 'connections' AND published_at IS NOT NULL",
                {"id": puzzle_id},
            )
            puzzle_row = cur.fetchone()
            if not puzzle_row:
                return None

            cur.execute(
                "INSERT INTO connections_feedback ("
                "puzzle_id, event_type, session_id, event_value, client_ts, user_agent"
                ") VALUES ("
                "%(puzzle_id)s, %(event_type)s, %(session_id)s, %(event_value)s::json, %(client_ts)s, %(user_agent)s"
                ") RETURNING id, puzzle_id, event_type, session_id, event_value, client_ts, created_at",
                {
                    "puzzle_id": puzzle_id,
                    "event_type": event_type,
                    "session_id": session_id,
                    "event_value": json.dumps(event_value or {}),
                    "client_ts": client_ts,
                    "user_agent": user_agent,
                },
            )
            row = cur.fetchone()
        conn.commit()

    if not row:
        return None
    return {
        "id": row["id"],
        "puzzleId": row["puzzle_id"],
        "eventType": row["event_type"],
        "sessionId": row["session_id"],
        "eventValue": row["event_value"],
        "clientTs": row["client_ts"].isoformat() if row["client_ts"] else None,
        "createdAt": row["created_at"].isoformat() if row["created_at"] else None,
    }


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
    if not row:
        return None
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

    if not row:
        return None
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


def get_or_create_player_profile(*, player_token: str) -> dict[str, Any]:
    token = player_token.strip()
    if not token:
        raise ValueError("Missing player token")
    default_name = _normalize_display_name(None, player_token=token)
    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT player_token, display_name, public_slug, leaderboard_visible, created_at, updated_at "
                "FROM player_profiles WHERE player_token = %(player_token)s LIMIT 1",
                {"player_token": token},
            )
            row = cur.fetchone()
            if row is None:
                public_slug = _unique_public_slug(cur, display_name=default_name, player_token=token)
                cur.execute(
                    "INSERT INTO player_profiles (player_token, display_name, public_slug, leaderboard_visible) "
                    "VALUES (%(player_token)s, %(display_name)s, %(public_slug)s, true) "
                    "RETURNING player_token, display_name, public_slug, leaderboard_visible, created_at, updated_at",
                    {
                        "player_token": token,
                        "display_name": default_name,
                        "public_slug": public_slug,
                    },
                )
                row = cur.fetchone()
            cur.execute(
                "SELECT username FROM player_accounts WHERE player_token = %(player_token)s LIMIT 1",
                {
                    "player_token": token,
                },
            )
            account_row = cur.fetchone()
        conn.commit()
    merged_row = dict(row or {})
    if account_row:
        merged_row["username"] = account_row.get("username")
    return _player_profile_payload(merged_row, player_token=token)


def update_player_profile(
    *,
    player_token: str,
    display_name: str | None = None,
    leaderboard_visible: bool | None = None,
) -> dict[str, Any]:
    token = player_token.strip()
    if not token:
        raise ValueError("Missing player token")
    current = get_or_create_player_profile(player_token=token)
    next_display_name = (
        _normalize_display_name(display_name, player_token=token) if display_name is not None else current["displayName"]
    )
    next_visible = bool(leaderboard_visible) if leaderboard_visible is not None else bool(current["leaderboardVisible"])
    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            public_slug = current["publicSlug"]
            cur.execute(
                "UPDATE player_profiles "
                "SET display_name = %(display_name)s, leaderboard_visible = %(leaderboard_visible)s, updated_at = NOW() "
                "WHERE player_token = %(player_token)s "
                "RETURNING player_token, display_name, public_slug, leaderboard_visible, created_at, updated_at",
                {
                    "display_name": next_display_name,
                    "leaderboard_visible": next_visible,
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
    return _player_profile_payload(merged_row, player_token=token)


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
        "SELECT display_name, leaderboard_visible FROM player_profiles WHERE player_token = %(player_token)s LIMIT 1",
        {"player_token": source_player_token},
    )
    source_profile = cur.fetchone()
    if source_profile is None:
        return

    cur.execute(
        "SELECT display_name, leaderboard_visible FROM player_profiles WHERE player_token = %(player_token)s LIMIT 1",
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

    source_display_name = _normalize_display_name(source_profile.get("display_name"), player_token=source_player_token)
    target_display_name = _normalize_display_name(target_profile.get("display_name"), player_token=target_player_token)
    next_display_name = target_display_name
    if target_display_name == _fallback_display_name(target_player_token) and source_display_name != _fallback_display_name(
        source_player_token
    ):
        next_display_name = source_display_name
    next_visible = bool(target_profile.get("leaderboard_visible", True)) or bool(source_profile.get("leaderboard_visible", True))
    cur.execute(
        "UPDATE player_profiles "
        "SET display_name = %(display_name)s, leaderboard_visible = %(leaderboard_visible)s, updated_at = NOW() "
        "WHERE player_token = %(player_token)s",
        {
            "display_name": next_display_name,
            "leaderboard_visible": next_visible,
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

            player_token = guest_token or _generate_player_token()
            if guest_token:
                cur.execute("SELECT 1 FROM player_accounts WHERE player_token = %(player_token)s LIMIT 1", {"player_token": guest_token})
                if cur.fetchone() is not None:
                    raise ValueError("Guest profile already claimed")
                cur.execute(
                    "SELECT player_token, display_name, public_slug, leaderboard_visible, created_at, updated_at "
                    "FROM player_profiles WHERE player_token = %(player_token)s LIMIT 1",
                    {"player_token": player_token},
                )
                profile_row = cur.fetchone()
                if profile_row is None:
                    default_name = _normalize_display_name(None, player_token=player_token)
                    public_slug = _unique_public_slug(cur, display_name=default_name, player_token=player_token)
                    cur.execute(
                        "INSERT INTO player_profiles (player_token, display_name, public_slug, leaderboard_visible) "
                        "VALUES (%(player_token)s, %(display_name)s, %(public_slug)s, true) "
                        "RETURNING player_token, display_name, public_slug, leaderboard_visible, created_at, updated_at",
                        {
                            "player_token": player_token,
                            "display_name": default_name,
                            "public_slug": public_slug,
                        },
                    )
                    profile_row = cur.fetchone()
            else:
                default_name = _normalize_display_name(None, player_token=player_token)
                public_slug = _unique_public_slug(cur, display_name=default_name, player_token=player_token)
                cur.execute(
                    "INSERT INTO player_profiles (player_token, display_name, public_slug, leaderboard_visible) "
                    "VALUES (%(player_token)s, %(display_name)s, %(public_slug)s, true) "
                    "RETURNING player_token, display_name, public_slug, leaderboard_visible, created_at, updated_at",
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

    profile = _player_profile_payload({**dict(profile_row or {}), "username": normalized_username}, player_token=player_token)
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
    token = player_token.strip()
    if not token:
        raise ValueError("Missing player token")
    get_or_create_player_profile(player_token=token)

    puzzle = get_puzzle_by_id(puzzle_id) if puzzle_id else get_puzzle_by_date(game_type, date_value, timezone=timezone)
    if puzzle is None:
        raise ValueError("Puzzle not found")
    if puzzle.get("gameType") != game_type:
        raise ValueError("Challenge game type does not match puzzle")
    resolved_puzzle_id = str(puzzle.get("id"))
    resolved_puzzle_date = _parse_date(str(puzzle.get("date")))

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
    offset = _parse_cursor_offset(cursor)

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
    resolved_puzzle_date = _parse_date(puzzle_date)
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
    target_date = _parse_date(date_value) if date_value else datetime.now(ZoneInfo(timezone)).date()
    if scope == "daily":
        start_date = target_date
    else:
        start_date = target_date - timedelta(days=6)
    end_date = target_date

    offset = _parse_cursor_offset(cursor)
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


def get_analytics_summary(*, days: int = 30, timezone: str = "Europe/London") -> dict[str, Any]:
    window_days = max(1, min(days, 365))
    today = datetime.now(ZoneInfo(timezone)).date()
    start_date = today - timedelta(days=window_days - 1)
    start_ts = datetime.combine(start_date, datetime.min.time(), tzinfo=ZoneInfo(timezone))

    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "WITH day_series AS ("
                "  SELECT generate_series(%(start_date)s::date, %(end_date)s::date, interval '1 day')::date AS day"
                "), all_events AS ("
                "  SELECT (created_at AT TIME ZONE %(timezone)s)::date AS day, session_id"
                "  FROM crossword_feedback"
                "  WHERE created_at >= %(start_ts)s AND session_id IS NOT NULL"
                "  UNION ALL "
                "  SELECT (created_at AT TIME ZONE %(timezone)s)::date AS day, session_id"
                "  FROM cryptic_feedback"
                "  WHERE created_at >= %(start_ts)s AND session_id IS NOT NULL"
                ")"
                "SELECT ds.day, COALESCE(COUNT(DISTINCT ev.session_id), 0) AS users "
                "FROM day_series ds "
                "LEFT JOIN all_events ev ON ev.day = ds.day "
                "GROUP BY ds.day "
                "ORDER BY ds.day ASC",
                {
                    "start_date": start_date,
                    "end_date": today,
                    "timezone": timezone,
                    "start_ts": start_ts,
                },
            )
            dau_rows = cur.fetchall()

            cur.execute(
                "SELECT "
                "COUNT(DISTINCT CASE WHEN event_type = 'page_view' AND session_id IS NOT NULL THEN session_id END) "
                "  AS page_sessions, "
                "COUNT(DISTINCT CASE WHEN event_type = 'completed' AND session_id IS NOT NULL THEN session_id END) "
                "  AS completed_sessions, "
                "PERCENTILE_CONT(0.5) WITHIN GROUP ("
                "  ORDER BY (event_value->>'solveMs')::double precision"
                ") FILTER ("
                "  WHERE event_type = 'completed' "
                "  AND (event_value ? 'solveMs') "
                "  AND (event_value->>'solveMs') ~ '^[0-9]+(\\.[0-9]+)?$'"
                ") AS median_solve_ms "
                "FROM crossword_feedback "
                "WHERE created_at >= %(start_ts)s",
                {"start_ts": start_ts},
            )
            crossword_row = cur.fetchone() or {}

            cur.execute(
                "WITH session_events AS ("
                "  SELECT id, session_id, event_type, created_at, "
                "         BOOL_OR(event_type = 'completed') OVER (PARTITION BY session_id) AS completed_any, "
                "         ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY created_at DESC, id DESC) AS rn "
                "  FROM crossword_feedback "
                "  WHERE created_at >= %(start_ts)s AND session_id IS NOT NULL"
                ") "
                "SELECT event_type, COUNT(*)::int AS sessions "
                "FROM session_events "
                "WHERE rn = 1 AND completed_any = FALSE "
                "GROUP BY event_type "
                "ORDER BY sessions DESC, event_type ASC",
                {"start_ts": start_ts},
            )
            dropoff_rows = cur.fetchall()

    dau_series = [
        {
            "date": row["day"].isoformat() if row.get("day") else None,
            "users": int(row.get("users") or 0),
        }
        for row in dau_rows
    ]
    dau_values = [item["users"] for item in dau_series]
    latest_dau = dau_values[-1] if dau_values else 0
    average_dau = round(sum(dau_values) / max(1, len(dau_values)), 2)

    page_sessions = int(crossword_row.get("page_sessions") or 0)
    completed_sessions = int(crossword_row.get("completed_sessions") or 0)
    completion_rate = round(completed_sessions / page_sessions, 4) if page_sessions > 0 else None
    median_solve_ms_value = crossword_row.get("median_solve_ms")
    median_solve_ms = int(round(float(median_solve_ms_value))) if median_solve_ms_value is not None else None

    dropoff = [
        {
            "eventType": str(row.get("event_type") or ""),
            "sessions": int(row.get("sessions") or 0),
        }
        for row in dropoff_rows
    ]

    return {
        "windowDays": window_days,
        "timezone": timezone,
        "dailyActiveUsers": {
            "latest": latest_dau,
            "average": average_dau,
            "series": dau_series,
        },
        "crossword": {
            "pageViewSessions": page_sessions,
            "completedSessions": completed_sessions,
            "completionRate": completion_rate,
            "medianSolveTimeMs": median_solve_ms,
            "dropoffByEventType": dropoff,
        },
    }


def get_personal_stats(*, session_ids: list[str], days: int = 30, timezone: str = "Europe/London") -> dict[str, Any]:
    clean_session_ids = sorted({sid.strip() for sid in session_ids if isinstance(sid, str) and sid.strip()})
    window_days = max(1, min(days, 365))
    today = datetime.now(ZoneInfo(timezone)).date()
    start_date = today - timedelta(days=window_days - 1)
    start_ts = datetime.combine(start_date, datetime.min.time(), tzinfo=ZoneInfo(timezone))

    if not clean_session_ids:
        return _empty_personal_stats_payload(
            session_ids=[],
            window_days=window_days,
            timezone=timezone,
            start_date=start_date,
        )

    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            crossword_bucket, crossword_history = _get_crossword_personal_stats_segment(
                cur=cur,
                session_ids=clean_session_ids,
                window_days=window_days,
                timezone=timezone,
                start_date=start_date,
                today=today,
                start_ts=start_ts,
            )
            cryptic_bucket, cryptic_history = _get_competitive_personal_stats_segment(
                cur=cur,
                game_type="cryptic",
                feedback_table="cryptic_feedback",
                session_ids=clean_session_ids,
                window_days=window_days,
                start_date=start_date,
                end_date=today,
            )
            connections_bucket, connections_history = _get_connections_personal_stats_segment(
                cur=cur,
                session_ids=clean_session_ids,
                window_days=window_days,
                start_date=start_date,
                end_date=today,
            )

    return {
        "sessionIds": clean_session_ids,
        "windowDays": window_days,
        "timezone": timezone,
        "crossword": crossword_bucket,
        "cryptic": cryptic_bucket,
        "connections": connections_bucket,
        "historyByGameType": {
            "crossword": crossword_history,
            "cryptic": cryptic_history,
            "connections": connections_history,
        },
    }


def _get_player_started_progress_rows(
    cur: Any,
    *,
    player_token: str,
    game_type: PuzzleGameType,
    start_date: date_type,
    end_date: date_type,
) -> tuple[int, list[dict[str, Any]]]:
    if not _table_exists(cur, "player_progress"):
        return 0, []
    cur.execute(
        "SELECT COUNT(DISTINCT pp.puzzle_id)::int AS started_count "
        "FROM player_progress pp "
        "JOIN puzzles p ON p.id = pp.puzzle_id "
        "WHERE pp.player_token = %(player_token)s "
        "AND pp.game_type = %(game_type)s "
        "AND pp.puzzle_id IS NOT NULL "
        "AND p.date >= %(start_date)s "
        "AND p.date <= %(end_date)s",
        {
            "player_token": player_token,
            "game_type": game_type,
            "start_date": start_date,
            "end_date": end_date,
        },
    )
    totals_row = cur.fetchone() or {}
    cur.execute(
        "SELECT p.date AS day, COUNT(DISTINCT pp.puzzle_id)::int AS page_views "
        "FROM player_progress pp "
        "JOIN puzzles p ON p.id = pp.puzzle_id "
        "WHERE pp.player_token = %(player_token)s "
        "AND pp.game_type = %(game_type)s "
        "AND pp.puzzle_id IS NOT NULL "
        "AND p.date >= %(start_date)s "
        "AND p.date <= %(end_date)s "
        "GROUP BY p.date "
        "ORDER BY p.date ASC",
        {
            "player_token": player_token,
            "game_type": game_type,
            "start_date": start_date,
            "end_date": end_date,
        },
    )
    return int(totals_row.get("started_count") or 0), cur.fetchall()


def _get_player_competitive_stats_segment(
    cur: Any,
    *,
    player_token: str,
    game_type: CompetitiveGameType,
    window_days: int,
    start_date: date_type,
    end_date: date_type,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    started_count, started_rows = _get_player_started_progress_rows(
        cur,
        player_token=player_token,
        game_type=game_type,
        start_date=start_date,
        end_date=end_date,
    )

    completion_totals: dict[str, Any] = {}
    completion_rows: list[dict[str, Any]] = []
    if _table_exists(cur, "leaderboard_submissions"):
        cur.execute(
            "SELECT "
            "COUNT(*) FILTER (WHERE completed = true)::int AS completed_count, "
            "COUNT(*) FILTER (WHERE completed = true AND COALESCE(used_assists, false) = false AND COALESCE(used_reveals, false) = false)::int AS clean_completed_count, "
            "PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY solve_time_ms::double precision) "
            "FILTER (WHERE completed = true AND solve_time_ms IS NOT NULL) AS median_solve_ms "
            "FROM leaderboard_submissions "
            "WHERE player_token = %(player_token)s "
            "AND game_type = %(game_type)s "
            "AND puzzle_date >= %(start_date)s "
            "AND puzzle_date <= %(end_date)s",
            {
                "player_token": player_token,
                "game_type": game_type,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        completion_totals = cur.fetchone() or {}
        cur.execute(
            "SELECT puzzle_date AS day, "
            "COUNT(*) FILTER (WHERE completed = true)::int AS completions, "
            "COUNT(*) FILTER (WHERE completed = true AND COALESCE(used_assists, false) = false AND COALESCE(used_reveals, false) = false)::int AS clean_completions "
            "FROM leaderboard_submissions "
            "WHERE player_token = %(player_token)s "
            "AND game_type = %(game_type)s "
            "AND puzzle_date >= %(start_date)s "
            "AND puzzle_date <= %(end_date)s "
            "GROUP BY puzzle_date "
            "ORDER BY puzzle_date ASC",
            {
                "player_token": player_token,
                "game_type": game_type,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        completion_rows = cur.fetchall()

    completions = int(completion_totals.get("completed_count") or 0)
    clean_completions = int(completion_totals.get("clean_completed_count") or 0)
    median_solve_ms_value = completion_totals.get("median_solve_ms")
    median_solve_ms = int(round(float(median_solve_ms_value))) if median_solve_ms_value is not None else None
    solved_dates = [row["day"] for row in completion_rows if int(row.get("completions") or 0) > 0]

    return (
        _build_personal_stats_bucket(
            page_views=started_count,
            page_view_puzzle_count=started_count,
            completions=completions,
            completed_puzzles=completions,
            clean_completions=clean_completions,
            median_solve_ms=median_solve_ms,
            solved_dates=solved_dates,
        ),
        _merge_personal_stats_history(
            window_days=window_days,
            start_date=start_date,
            page_view_rows=started_rows,
            completion_rows=completion_rows,
        ),
    )


def _get_player_connections_stats_segment(
    cur: Any,
    *,
    player_token: str,
    window_days: int,
    start_date: date_type,
    end_date: date_type,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    started_count, started_rows = _get_player_started_progress_rows(
        cur,
        player_token=player_token,
        game_type="connections",
        start_date=start_date,
        end_date=end_date,
    )
    if not _table_exists(cur, "player_progress"):
        return _empty_personal_stats_bucket(), _empty_personal_stats_history(window_days=window_days, start_date=start_date)

    cur.execute(
        "WITH latest AS ("
        "  SELECT DISTINCT ON (pp.puzzle_id) pp.puzzle_id, pp.progress "
        "  FROM player_progress pp "
        "  JOIN puzzles p ON p.id = pp.puzzle_id "
        "  WHERE pp.player_token = %(player_token)s "
        "    AND pp.game_type = 'connections' "
        "    AND pp.puzzle_id IS NOT NULL "
        "    AND p.date >= %(start_date)s "
        "    AND p.date <= %(end_date)s "
        "  ORDER BY pp.puzzle_id, COALESCE(pp.client_updated_at, pp.updated_at) DESC, pp.id DESC"
        ") "
        "SELECT "
        "COUNT(*) FILTER (WHERE latest.progress->>'outcome' = 'completed')::int AS completed_count, "
        "COUNT(*) FILTER (WHERE latest.progress->>'outcome' = 'completed' "
        "  AND COALESCE((NULLIF(latest.progress->>'mistakes', ''))::int, 0) = 0)::int AS clean_completed_count "
        "FROM latest",
        {
            "player_token": player_token,
            "start_date": start_date,
            "end_date": end_date,
        },
    )
    totals_row = cur.fetchone() or {}
    cur.execute(
        "WITH latest AS ("
        "  SELECT DISTINCT ON (pp.puzzle_id) pp.puzzle_id, p.date AS day, pp.progress "
        "  FROM player_progress pp "
        "  JOIN puzzles p ON p.id = pp.puzzle_id "
        "  WHERE pp.player_token = %(player_token)s "
        "    AND pp.game_type = 'connections' "
        "    AND pp.puzzle_id IS NOT NULL "
        "    AND p.date >= %(start_date)s "
        "    AND p.date <= %(end_date)s "
        "  ORDER BY pp.puzzle_id, COALESCE(pp.client_updated_at, pp.updated_at) DESC, pp.id DESC"
        ") "
        "SELECT day, "
        "COUNT(*) FILTER (WHERE latest.progress->>'outcome' = 'completed')::int AS completions, "
        "COUNT(*) FILTER (WHERE latest.progress->>'outcome' = 'completed' "
        "  AND COALESCE((NULLIF(latest.progress->>'mistakes', ''))::int, 0) = 0)::int AS clean_completions "
        "FROM latest "
        "GROUP BY day "
        "ORDER BY day ASC",
        {
            "player_token": player_token,
            "start_date": start_date,
            "end_date": end_date,
        },
    )
    completion_rows = cur.fetchall()
    completions = int(totals_row.get("completed_count") or 0)
    clean_completions = int(totals_row.get("clean_completed_count") or 0)
    solved_dates = [row["day"] for row in completion_rows if int(row.get("completions") or 0) > 0]
    return (
        _build_personal_stats_bucket(
            page_views=started_count,
            page_view_puzzle_count=started_count,
            completions=completions,
            completed_puzzles=completions,
            clean_completions=clean_completions,
            median_solve_ms=None,
            solved_dates=solved_dates,
        ),
        _merge_personal_stats_history(
            window_days=window_days,
            start_date=start_date,
            page_view_rows=started_rows,
            completion_rows=completion_rows,
        ),
    )


def get_player_stats(*, player_token: str, days: int = 30, timezone: str = "Europe/London") -> dict[str, Any]:
    token = player_token.strip()
    if not token:
        raise ValueError("Missing player token")

    window_days = max(1, min(days, 365))
    today = datetime.now(ZoneInfo(timezone)).date()
    start_date = today - timedelta(days=window_days - 1)
    payload = _empty_personal_stats_payload(
        session_ids=[],
        window_days=window_days,
        timezone=timezone,
        start_date=start_date,
    )

    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            crossword_bucket, crossword_history = _get_player_competitive_stats_segment(
                cur,
                player_token=token,
                game_type="crossword",
                window_days=window_days,
                start_date=start_date,
                end_date=today,
            )
            cryptic_bucket, cryptic_history = _get_player_competitive_stats_segment(
                cur,
                player_token=token,
                game_type="cryptic",
                window_days=window_days,
                start_date=start_date,
                end_date=today,
            )
            connections_bucket, connections_history = _get_player_connections_stats_segment(
                cur,
                player_token=token,
                window_days=window_days,
                start_date=start_date,
                end_date=today,
            )
    payload["crossword"] = crossword_bucket
    payload["cryptic"] = cryptic_bucket
    payload["connections"] = connections_bucket
    payload["historyByGameType"] = {
        "crossword": crossword_history,
        "cryptic": cryptic_history,
        "connections": connections_history,
    }
    return payload


def get_public_player_profile(*, public_slug: str) -> dict[str, Any] | None:
    slug = (public_slug or "").strip().lower()
    if not slug:
        return None
    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT p.player_token, p.display_name, p.public_slug, p.leaderboard_visible, p.created_at, p.updated_at, a.username "
                "FROM player_profiles p "
                "LEFT JOIN player_accounts a ON a.player_token = p.player_token "
                "WHERE p.public_slug = %(public_slug)s LIMIT 1",
                {"public_slug": slug},
            )
            row = cur.fetchone()
    if row is None:
        return None
    payload = _player_profile_payload(row, player_token=str(row["player_token"]))
    return {
        "displayName": payload["displayName"],
        "publicSlug": payload["publicSlug"],
        "leaderboardVisible": payload["leaderboardVisible"],
        "hasAccount": payload["hasAccount"],
        "createdAt": payload["createdAt"],
        "updatedAt": payload["updatedAt"],
        "playerToken": payload["playerToken"],
    }


def get_public_player_stats(*, public_slug: str, days: int = 30, timezone: str = "Europe/London") -> dict[str, Any] | None:
    profile = get_public_player_profile(public_slug=public_slug)
    if profile is None:
        return None
    stats = get_player_stats(player_token=str(profile["playerToken"]), days=days, timezone=timezone)
    return {
        "profile": {
            "displayName": profile["displayName"],
            "publicSlug": profile["publicSlug"],
            "leaderboardVisible": profile["leaderboardVisible"],
            "hasAccount": profile["hasAccount"],
            "createdAt": profile["createdAt"],
            "updatedAt": profile["updatedAt"],
        },
        "stats": stats,
    }


def get_cryptic_clue_feedback_summary(*, days: int = 30, timezone: str = "Europe/London") -> dict[str, Any]:
    window_days = max(1, min(days, 365))
    today = datetime.now(ZoneInfo(timezone)).date()
    start_date = today - timedelta(days=window_days - 1)
    start_ts = datetime.combine(start_date, datetime.min.time(), tzinfo=ZoneInfo(timezone))

    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT "
                "COUNT(*)::int AS total_count, "
                "COUNT(*) FILTER (WHERE event_value->>'rating' = 'up')::int AS up_count, "
                "COUNT(*) FILTER (WHERE event_value->>'rating' = 'down')::int AS down_count "
                "FROM cryptic_feedback "
                "WHERE event_type = 'clue_feedback' AND created_at >= %(start_ts)s",
                {"start_ts": start_ts},
            )
            totals_row = cur.fetchone() or {}

            cur.execute(
                "SELECT "
                "(created_at AT TIME ZONE %(timezone)s)::date AS day, "
                "COUNT(*)::int AS total_count, "
                "COUNT(*) FILTER (WHERE event_value->>'rating' = 'up')::int AS up_count, "
                "COUNT(*) FILTER (WHERE event_value->>'rating' = 'down')::int AS down_count "
                "FROM cryptic_feedback "
                "WHERE event_type = 'clue_feedback' AND created_at >= %(start_ts)s "
                "GROUP BY day ORDER BY day ASC",
                {"start_ts": start_ts, "timezone": timezone},
            )
            day_rows = cur.fetchall()

            cur.execute(
                "SELECT "
                "COALESCE(NULLIF(event_value->>'mechanism', ''), 'unknown') AS clue_type, "
                "COUNT(*)::int AS total_count, "
                "COUNT(*) FILTER (WHERE event_value->>'rating' = 'up')::int AS up_count, "
                "COUNT(*) FILTER (WHERE event_value->>'rating' = 'down')::int AS down_count "
                "FROM cryptic_feedback "
                "WHERE event_type = 'clue_feedback' AND created_at >= %(start_ts)s "
                "GROUP BY clue_type ORDER BY total_count DESC, clue_type ASC",
                {"start_ts": start_ts},
            )
            type_rows = cur.fetchall()

            cur.execute(
                "SELECT reason_tag, COUNT(*)::int AS count "
                "FROM ("
                "  SELECT jsonb_array_elements_text("
                "    CASE "
                "      WHEN jsonb_typeof((event_value->'reasons')::jsonb) = 'array' THEN (event_value->'reasons')::jsonb "
                "      ELSE '[]'::jsonb "
                "    END"
                "  ) AS reason_tag "
                "  FROM cryptic_feedback "
                "  WHERE event_type = 'clue_feedback' AND created_at >= %(start_ts)s"
                ") reason_rows "
                "GROUP BY reason_tag "
                "ORDER BY count DESC, reason_tag ASC "
                "LIMIT 20",
                {"start_ts": start_ts},
            )
            reason_rows = cur.fetchall()

    return {
        "windowDays": window_days,
        "timezone": timezone,
        "totalFeedback": int(totals_row.get("total_count") or 0),
        "ratings": {
            "up": int(totals_row.get("up_count") or 0),
            "down": int(totals_row.get("down_count") or 0),
        },
        "byDate": [
            {
                "date": row["day"].isoformat() if row.get("day") else None,
                "total": int(row.get("total_count") or 0),
                "up": int(row.get("up_count") or 0),
                "down": int(row.get("down_count") or 0),
            }
            for row in day_rows
        ],
        "byClueType": [
            {
                "clueType": str(row.get("clue_type") or "unknown"),
                "total": int(row.get("total_count") or 0),
                "up": int(row.get("up_count") or 0),
                "down": int(row.get("down_count") or 0),
            }
            for row in type_rows
        ],
        "topReasonTags": [
            {"reason": str(row.get("reason_tag") or ""), "count": int(row.get("count") or 0)}
            for row in reason_rows
            if str(row.get("reason_tag") or "")
        ],
    }
