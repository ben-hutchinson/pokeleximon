from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo

from psycopg.rows import dict_row

from app.core.db import get_db
from app.data.common import (
    CompetitiveGameType,
    PuzzleGameType,
    build_personal_stats_bucket,
    empty_personal_stats_bucket,
    empty_personal_stats_history,
    empty_personal_stats_payload,
    merge_personal_stats_history,
    player_profile_payload,
    table_exists,
)


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
    if not table_exists(cur, "crossword_feedback"):
        return empty_personal_stats_bucket(), empty_personal_stats_history(window_days=window_days, start_date=start_date)

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
        build_personal_stats_bucket(
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

    if table_exists(cur, feedback_table):
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

    if table_exists(cur, "leaderboard_submissions"):
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
        build_personal_stats_bucket(
            page_views=page_views,
            page_view_puzzle_count=page_view_puzzle_count,
            completions=completions,
            completed_puzzles=completions,
            clean_completions=clean_completions,
            median_solve_ms=median_solve_ms,
            solved_dates=solved_dates,
        ),
        merge_personal_stats_history(
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
    if not table_exists(cur, "connections_feedback"):
        return empty_personal_stats_bucket(), empty_personal_stats_history(window_days=window_days, start_date=start_date)

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

    cur.execute(
        "SELECT DISTINCT p.date AS solved_date "
        "FROM connections_feedback cf "
        "JOIN puzzles p ON p.id = cf.puzzle_id "
        "WHERE p.date >= %(start_date)s "
        "AND p.date <= %(end_date)s "
        "AND cf.session_id = ANY(%(session_ids)s) "
        "AND cf.event_type = 'completed' "
        "ORDER BY solved_date ASC",
        {
            "start_date": start_date,
            "end_date": end_date,
            "session_ids": session_ids,
        },
    )
    solved_rows = cur.fetchall()

    page_views = int(totals_row.get("page_view_count") or 0)
    completions = int(totals_row.get("completed_count") or 0)
    page_view_puzzle_count = int(totals_row.get("page_view_puzzle_count") or 0)
    completed_puzzle_count = int(totals_row.get("completed_puzzle_count") or 0)
    clean_completions = int(totals_row.get("clean_completed_count") or 0)
    solved_dates = [row.get("solved_date") for row in solved_rows if row.get("solved_date") is not None]

    return (
        build_personal_stats_bucket(
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
        return empty_personal_stats_payload(
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
    if not table_exists(cur, "player_progress"):
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
    if table_exists(cur, "leaderboard_submissions"):
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
        build_personal_stats_bucket(
            page_views=started_count,
            page_view_puzzle_count=started_count,
            completions=completions,
            completed_puzzles=completions,
            clean_completions=clean_completions,
            median_solve_ms=median_solve_ms,
            solved_dates=solved_dates,
        ),
        merge_personal_stats_history(
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
    if not table_exists(cur, "player_progress"):
        return empty_personal_stats_bucket(), empty_personal_stats_history(window_days=window_days, start_date=start_date)

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
        build_personal_stats_bucket(
            page_views=started_count,
            page_view_puzzle_count=started_count,
            completions=completions,
            completed_puzzles=completions,
            clean_completions=clean_completions,
            median_solve_ms=None,
            solved_dates=solved_dates,
        ),
        merge_personal_stats_history(
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
    payload = empty_personal_stats_payload(
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
                "SELECT p.player_token, p.display_name, p.public_slug, p.leaderboard_visible, p.avatar_preset, "
                "p.created_at, p.updated_at, a.username "
                "FROM player_profiles p "
                "LEFT JOIN player_accounts a ON a.player_token = p.player_token "
                "WHERE p.public_slug = %(public_slug)s LIMIT 1",
                {"public_slug": slug},
            )
            row = cur.fetchone()
    if row is None:
        return None
    payload = player_profile_payload(row, player_token=str(row["player_token"]))
    return {
        "displayName": payload["displayName"],
        "publicSlug": payload["publicSlug"],
        "leaderboardVisible": payload["leaderboardVisible"],
        "avatarPreset": payload["avatarPreset"],
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
            "avatarPreset": profile.get("avatarPreset"),
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
