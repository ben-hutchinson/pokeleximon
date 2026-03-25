from __future__ import annotations

import json
import logging
import re
from datetime import date as date_type
from datetime import datetime
from typing import Any, Literal, cast
from uuid import uuid4
from zoneinfo import ZoneInfo

from psycopg.rows import dict_row

from app.core.cache import get_cache
from app.core.db import get_db
from app.data.common import (
    CompetitiveGameType,
    PuzzleDict,
    PuzzleGameType,
    PublishStatus,
)
from app.services.alerting import notify_external_alert
from app.services.artifact_store import write_json_artifact


logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 300
DATE_TOKEN_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
WHITESPACE_RE = re.compile(r"\s+")


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
    from app.data.feedback_repo import create_cryptic_feedback as impl

    return impl(
        puzzle_id=puzzle_id,
        event_type=event_type,
        session_id=session_id,
        event_value=event_value,
        candidate_id=candidate_id,
        client_ts=client_ts,
        user_agent=user_agent,
    )


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
    from app.data.feedback_repo import create_cryptic_clue_feedback as impl

    return impl(
        puzzle_id=puzzle_id,
        entry_id=entry_id,
        rating=rating,
        reason_tags=reason_tags,
        session_id=session_id,
        candidate_id=candidate_id,
        mechanism=mechanism,
        clue_text=clue_text,
        client_ts=client_ts,
        user_agent=user_agent,
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
    from app.data.feedback_repo import create_crossword_feedback as impl

    return impl(
        puzzle_id=puzzle_id,
        event_type=event_type,
        session_id=session_id,
        event_value=event_value,
        client_ts=client_ts,
        user_agent=user_agent,
    )


def create_connections_feedback(
    *,
    puzzle_id: str,
    event_type: str,
    session_id: str | None,
    event_value: dict[str, Any] | None,
    client_ts: datetime | None,
    user_agent: str | None,
) -> dict[str, Any] | None:
    from app.data.feedback_repo import create_connections_feedback as impl

    return impl(
        puzzle_id=puzzle_id,
        event_type=event_type,
        session_id=session_id,
        event_value=event_value,
        client_ts=client_ts,
        user_agent=user_agent,
    )


def get_player_progress(*, player_token: str, key: str) -> dict[str, Any] | None:
    from app.data.player_repo import get_player_progress as impl

    return impl(player_token=player_token, key=key)


def upsert_player_progress(
    *,
    player_token: str,
    key: str,
    game_type: PuzzleGameType | None,
    puzzle_id: str | None,
    progress: dict[str, Any] | None,
    client_updated_at: datetime | None,
) -> dict[str, Any] | None:
    from app.data.player_repo import upsert_player_progress as impl

    return impl(
        player_token=player_token,
        key=key,
        game_type=game_type,
        puzzle_id=puzzle_id,
        progress=progress,
        client_updated_at=client_updated_at,
    )


def get_or_create_player_profile(*, player_token: str) -> dict[str, Any]:
    from app.data.player_repo import get_or_create_player_profile as impl

    return impl(player_token=player_token)


def update_player_profile(
    *,
    player_token: str,
    display_name: str | None = None,
    leaderboard_visible: bool | None = None,
    avatar_preset: str | None = None,
) -> dict[str, Any]:
    from app.data.player_repo import update_player_profile as impl

    return impl(
        player_token=player_token,
        display_name=display_name,
        leaderboard_visible=leaderboard_visible,
        avatar_preset=avatar_preset,
    )


def create_player_account(
    *,
    username: str,
    password: str,
    guest_player_token: str | None = None,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> tuple[dict[str, Any], str]:
    from app.data.player_repo import create_player_account as impl

    return impl(
        username=username,
        password=password,
        guest_player_token=guest_player_token,
        user_agent=user_agent,
        ip_address=ip_address,
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
    from app.data.player_repo import login_player_account as impl

    return impl(
        username=username,
        password=password,
        guest_player_token=guest_player_token,
        merge_guest_data=merge_guest_data,
        user_agent=user_agent,
        ip_address=ip_address,
    )


def get_player_auth_session(*, session_token: str) -> dict[str, Any]:
    from app.data.player_repo import get_player_auth_session as impl

    return impl(session_token=session_token)


def revoke_player_auth_session(*, session_token: str) -> None:
    from app.data.player_repo import revoke_player_auth_session as impl

    impl(session_token=session_token)


def create_challenge(
    *,
    player_token: str,
    game_type: CompetitiveGameType,
    puzzle_id: str | None = None,
    date_value: str | None = None,
    timezone: str = "Europe/London",
) -> dict[str, Any]:
    from app.data.player_repo import create_challenge as impl

    return impl(
        player_token=player_token,
        game_type=game_type,
        puzzle_id=puzzle_id,
        date_value=date_value,
        timezone=timezone,
    )


def get_challenge_detail(
    *,
    challenge_code: str,
    player_token: str | None = None,
    limit: int = 25,
    cursor: str | None = None,
) -> dict[str, Any] | None:
    from app.data.player_repo import get_challenge_detail as impl

    return impl(
        challenge_code=challenge_code,
        player_token=player_token,
        limit=limit,
        cursor=cursor,
    )


def join_challenge(*, player_token: str, challenge_code: str, limit: int = 25, cursor: str | None = None) -> dict[str, Any] | None:
    from app.data.player_repo import join_challenge as impl

    return impl(player_token=player_token, challenge_code=challenge_code, limit=limit, cursor=cursor)


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
    from app.data.player_repo import submit_leaderboard_result as impl

    return impl(
        player_token=player_token,
        game_type=game_type,
        puzzle_id=puzzle_id,
        puzzle_date=puzzle_date,
        completed=completed,
        solve_time_ms=solve_time_ms,
        used_assists=used_assists,
        used_reveals=used_reveals,
        session_id=session_id,
    )


def get_global_leaderboard(
    *,
    game_type: CompetitiveGameType,
    scope: Literal["daily", "weekly"] = "daily",
    date_value: str | date_type | None = None,
    timezone: str = "Europe/London",
    limit: int = 25,
    cursor: str | None = None,
) -> dict[str, Any]:
    from app.data.player_repo import get_global_leaderboard as impl

    return impl(
        game_type=game_type,
        scope=scope,
        date_value=date_value,
        timezone=timezone,
        limit=limit,
        cursor=cursor,
    )


def get_analytics_summary(*, days: int = 30, timezone: str = "Europe/London") -> dict[str, Any]:
    from app.data.stats_repo import get_analytics_summary as impl

    return impl(days=days, timezone=timezone)


def get_personal_stats(*, session_ids: list[str], days: int = 30, timezone: str = "Europe/London") -> dict[str, Any]:
    from app.data.stats_repo import get_personal_stats as impl

    return impl(session_ids=session_ids, days=days, timezone=timezone)


def get_player_stats(*, player_token: str, days: int = 30, timezone: str = "Europe/London") -> dict[str, Any]:
    from app.data.stats_repo import get_player_stats as impl

    return impl(player_token=player_token, days=days, timezone=timezone)


def get_public_player_profile(*, public_slug: str) -> dict[str, Any] | None:
    from app.data.stats_repo import get_public_player_profile as impl

    return impl(public_slug=public_slug)


def get_public_player_stats(*, public_slug: str, days: int = 30, timezone: str = "Europe/London") -> dict[str, Any] | None:
    from app.data.stats_repo import get_public_player_stats as impl

    return impl(public_slug=public_slug, days=days, timezone=timezone)


def get_cryptic_clue_feedback_summary(*, days: int = 30, timezone: str = "Europe/London") -> dict[str, Any]:
    from app.data.stats_repo import get_cryptic_clue_feedback_summary as impl

    return impl(days=days, timezone=timezone)
