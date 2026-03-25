from __future__ import annotations

import re
from datetime import date as date_type
from datetime import timedelta
from typing import Any, Literal
from uuid import uuid4


PuzzleDict = dict[str, Any]
PublishStatus = Literal["published", "already_published", "reserve_empty"]
PuzzleGameType = Literal["crossword", "cryptic", "connections"]
CompetitiveGameType = Literal["crossword", "cryptic"]

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


def parse_date(date_value: str | date_type) -> date_type:
    if isinstance(date_value, str):
        return date_type.fromisoformat(date_value)
    return date_value


def rewrite_title_for_publish(title: str, target_date: date_type) -> str:
    return DATE_TOKEN_RE.sub(target_date.isoformat(), title)


def note_snippet(value: Any, max_len: int = 180) -> str | None:
    if not isinstance(value, str):
        return None
    collapsed = WHITESPACE_RE.sub(" ", value).strip()
    if not collapsed:
        return None
    if len(collapsed) <= max_len:
        return collapsed
    return f"{collapsed[: max_len - 3].rstrip()}..."


def fallback_display_name(player_token: str) -> str:
    tail = re.sub(r"[^A-Za-z0-9]", "", player_token)[-6:]
    if not tail:
        tail = "PLAYER"
    return f"Player {tail.upper()}"


def normalize_display_name(value: str | None, *, player_token: str) -> str:
    candidate = (value or "").strip()
    if candidate:
        candidate = DISPLAY_NAME_ALLOWED_RE.sub("", candidate)
        candidate = WHITESPACE_RE.sub(" ", candidate).strip()
    if not candidate:
        candidate = fallback_display_name(player_token)
    return candidate[:40]


def generate_player_token() -> str:
    return f"plr_{uuid4().hex[:24]}"


def slugify_public_name(value: str, *, player_token: str) -> str:
    base = PUBLIC_SLUG_RE.sub("-", value.strip().lower()).strip("-")
    if not base:
        base = PUBLIC_SLUG_RE.sub("-", fallback_display_name(player_token).lower()).strip("-")
    return base[:80].strip("-") or f"player-{player_token[-6:].lower()}"


def unique_public_slug(cur: Any, *, display_name: str, player_token: str, exclude_player_token: str | None = None) -> str:
    base = slugify_public_name(display_name, player_token=player_token)
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


def player_profile_payload(row: dict[str, Any] | None, *, player_token: str) -> dict[str, Any]:
    default_name = normalize_display_name(None, player_token=player_token)
    public_slug = ""
    if row:
        public_slug = str(row.get("public_slug") or "").strip()
    if not public_slug:
        public_slug = slugify_public_name(default_name, player_token=player_token)
    return {
        "playerToken": player_token,
        "displayName": normalize_display_name((row or {}).get("display_name"), player_token=player_token),
        "publicSlug": public_slug,
        "leaderboardVisible": bool((row or {}).get("leaderboard_visible", True)),
        "avatarPreset": str((row or {}).get("avatar_preset") or "").strip() or None,
        "hasAccount": bool((row or {}).get("username")),
        "createdAt": row["created_at"].isoformat() if row and row.get("created_at") else None,
        "updatedAt": row["updated_at"].isoformat() if row and row.get("updated_at") else None,
    }


def parse_cursor_offset(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        value = int(cursor)
    except ValueError:
        return 0
    return max(0, value)


def compute_streak_lengths(dates: list[date_type]) -> tuple[int, int]:
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


def empty_personal_stats_bucket() -> dict[str, Any]:
    return {
        "pageViews": 0,
        "completions": 0,
        "completionRate": None,
        "medianSolveTimeMs": None,
        "cleanSolveRate": None,
        "streakCurrent": 0,
        "streakBest": 0,
    }


def empty_personal_stats_history(*, window_days: int, start_date: date_type) -> list[dict[str, Any]]:
    return [
        {
            "date": (start_date + timedelta(days=offset)).isoformat(),
            "pageViews": 0,
            "completions": 0,
            "cleanCompletions": 0,
        }
        for offset in range(window_days)
    ]


def empty_personal_stats_payload(
    *,
    session_ids: list[str],
    window_days: int,
    timezone: str,
    start_date: date_type,
) -> dict[str, Any]:
    streak_history = empty_personal_stats_history(window_days=window_days, start_date=start_date)
    return {
        "sessionIds": session_ids,
        "windowDays": window_days,
        "timezone": timezone,
        "crossword": empty_personal_stats_bucket(),
        "cryptic": empty_personal_stats_bucket(),
        "connections": empty_personal_stats_bucket(),
        "historyByGameType": {
            "crossword": [dict(day) for day in streak_history],
            "cryptic": [dict(day) for day in streak_history],
            "connections": [dict(day) for day in streak_history],
        },
    }


def merge_personal_stats_history(
    *,
    window_days: int,
    start_date: date_type,
    page_view_rows: list[dict[str, Any]] | None = None,
    completion_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    history = empty_personal_stats_history(window_days=window_days, start_date=start_date)
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


def table_exists(cur: Any, table_name: str) -> bool:
    cur.execute(f"SELECT to_regclass('public.{table_name}') AS table_name", {})
    table_row = cur.fetchone() or {}
    return bool(table_row.get("table_name"))


def build_personal_stats_bucket(
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
    streak_current, streak_best = compute_streak_lengths(solved_dates)
    return {
        "pageViews": page_views,
        "completions": completions,
        "completionRate": completion_rate,
        "medianSolveTimeMs": median_solve_ms,
        "cleanSolveRate": clean_solve_rate,
        "streakCurrent": streak_current,
        "streakBest": streak_best,
    }
