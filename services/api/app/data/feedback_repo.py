from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from psycopg.rows import dict_row

from app.core.db import get_db
from app.data.common import CLUE_FEEDBACK_REASON_TAGS


def _feedback_row_payload(row: dict[str, Any], *, include_candidate: bool = False) -> dict[str, Any]:
    payload = {
        "id": row["id"],
        "puzzleId": row["puzzle_id"],
        "eventType": row["event_type"],
        "sessionId": row["session_id"],
        "eventValue": row["event_value"],
        "clientTs": row["client_ts"].isoformat() if row["client_ts"] else None,
        "createdAt": row["created_at"].isoformat() if row["created_at"] else None,
    }
    if include_candidate:
        payload["candidateId"] = row["candidate_id"]
    return payload


def _published_puzzle_exists(*, cur: Any, puzzle_id: str, game_type: str) -> bool:
    cur.execute(
        "SELECT id FROM puzzles WHERE id = %(id)s AND game_type = %(game_type)s AND published_at IS NOT NULL",
        {"id": puzzle_id, "game_type": game_type},
    )
    return cur.fetchone() is not None


def _validated_cryptic_candidate_id(*, cur: Any, puzzle_id: str, candidate_id: int | None) -> int | None:
    if candidate_id is None:
        return None
    cur.execute(
        "SELECT id FROM cryptic_candidates WHERE id = %(id)s AND puzzle_id = %(puzzle_id)s",
        {"id": candidate_id, "puzzle_id": puzzle_id},
    )
    return candidate_id if cur.fetchone() else None


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
            if not _published_puzzle_exists(cur=cur, puzzle_id=puzzle_id, game_type="cryptic"):
                return None

            cur.execute(
                "INSERT INTO cryptic_feedback ("
                "puzzle_id, candidate_id, event_type, session_id, event_value, client_ts, user_agent"
                ") VALUES ("
                "%(puzzle_id)s, %(candidate_id)s, %(event_type)s, %(session_id)s, %(event_value)s::json, %(client_ts)s, %(user_agent)s"
                ") RETURNING id, puzzle_id, candidate_id, event_type, session_id, event_value, client_ts, created_at",
                {
                    "puzzle_id": puzzle_id,
                    "candidate_id": _validated_cryptic_candidate_id(cur=cur, puzzle_id=puzzle_id, candidate_id=candidate_id),
                    "event_type": event_type,
                    "session_id": session_id,
                    "event_value": json.dumps(event_value or {}),
                    "client_ts": client_ts,
                    "user_agent": user_agent,
                },
            )
            row = cur.fetchone()
        conn.commit()

    return _feedback_row_payload(row, include_candidate=True) if row else None


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
            if not _published_puzzle_exists(cur=cur, puzzle_id=puzzle_id, game_type="cryptic"):
                return None, False

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
                return _feedback_row_payload(existing, include_candidate=True), True

            cur.execute(
                "INSERT INTO cryptic_feedback ("
                "puzzle_id, candidate_id, event_type, session_id, event_value, client_ts, user_agent"
                ") VALUES ("
                "%(puzzle_id)s, %(candidate_id)s, 'clue_feedback', %(session_id)s, %(event_value)s::json, %(client_ts)s, %(user_agent)s"
                ") RETURNING id, puzzle_id, candidate_id, event_type, session_id, event_value, client_ts, created_at",
                {
                    "puzzle_id": puzzle_id,
                    "candidate_id": _validated_cryptic_candidate_id(cur=cur, puzzle_id=puzzle_id, candidate_id=candidate_id),
                    "session_id": session_id,
                    "event_value": json.dumps(feedback_payload),
                    "client_ts": client_ts,
                    "user_agent": user_agent,
                },
            )
            row = cur.fetchone()
        conn.commit()

    return (_feedback_row_payload(row, include_candidate=True), False) if row else (None, False)


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
            if not _published_puzzle_exists(cur=cur, puzzle_id=puzzle_id, game_type="crossword"):
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

    return _feedback_row_payload(row) if row else None


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
            if not _published_puzzle_exists(cur=cur, puzzle_id=puzzle_id, game_type="connections"):
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

    return _feedback_row_payload(row) if row else None
