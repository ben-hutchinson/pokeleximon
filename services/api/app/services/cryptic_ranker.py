from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from psycopg.rows import dict_row

from app.core import config
from app.core.db import get_db

DEFAULT_MECHANISM_SCORES = {
    "charade": 9.0,
    "anagram": 8.0,
    "deletion": 7.0,
    "container": 6.0,
    "hidden": 5.0,
    "fallback": 1.0,
}


def _utcnow() -> datetime:
    return datetime.now(ZoneInfo("UTC"))


def _job_id() -> str:
    return f"job_cryptic_ranker_train_{uuid4().hex[:10]}"


def _model_version() -> str:
    return f"cryptic-ranker-{datetime.now(ZoneInfo('UTC')).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6]}"


def _insert_job(cur, job_id: str, job_date, model_version: str) -> None:
    cur.execute(
        "INSERT INTO generation_jobs "
        "(id, type, date, status, started_at, model_version) "
        "VALUES (%(id)s, %(type)s, %(date)s, %(status)s, %(started_at)s, %(model_version)s)",
        {
            "id": job_id,
            "type": "cryptic_ranker_train",
            "date": job_date,
            "status": "running",
            "started_at": _utcnow(),
            "model_version": model_version,
        },
    )


def _complete_job(cur, job_id: str, status: str, logs: dict[str, Any]) -> None:
    cur.execute(
        "UPDATE generation_jobs "
        "SET status = %(status)s, finished_at = %(finished_at)s, logs_url = %(logs_url)s "
        "WHERE id = %(id)s",
        {
            "id": job_id,
            "status": status,
            "finished_at": _utcnow(),
            "logs_url": json.dumps(logs),
        },
    )


def _load_selected_candidates(cur) -> list[dict[str, Any]]:
    cur.execute(
        "SELECT cc.id, cc.puzzle_id, cc.mechanism "
        "FROM cryptic_candidates cc "
        "JOIN puzzles p ON p.id = cc.puzzle_id "
        "WHERE cc.selected = true AND p.game_type = 'cryptic' AND p.published_at IS NOT NULL"
    )
    return cur.fetchall()


def _load_feedback_by_puzzle(cur) -> dict[str, dict[str, int]]:
    cur.execute(
        "SELECT puzzle_id, "
        "COUNT(*) FILTER (WHERE event_type = 'guess_submit') AS guess_submit_count, "
        "COUNT(*) FILTER (WHERE event_type = 'check_click') AS check_click_count, "
        "COUNT(*) FILTER (WHERE event_type = 'reveal_click') AS reveal_click_count, "
        "COUNT(*) FILTER (WHERE event_type = 'abandon') AS abandon_count, "
        "COUNT(*) AS total_count "
        "FROM cryptic_feedback "
        "GROUP BY puzzle_id"
    )
    out: dict[str, dict[str, int]] = {}
    for row in cur.fetchall():
        out[row["puzzle_id"]] = {
            "guess_submit_count": int(row["guess_submit_count"] or 0),
            "check_click_count": int(row["check_click_count"] or 0),
            "reveal_click_count": int(row["reveal_click_count"] or 0),
            "abandon_count": int(row["abandon_count"] or 0),
            "total_count": int(row["total_count"] or 0),
        }
    return out


def _derive_label(feedback: dict[str, int]) -> int | None:
    # Proxy label:
    # success=1 if at least one guess, no reveal, no abandon
    # fail=0 if reveal or abandon occurred
    # None if no meaningful signal yet
    if feedback["reveal_click_count"] > 0 or feedback["abandon_count"] > 0:
        return 0
    if feedback["guess_submit_count"] > 0:
        return 1
    return None


def _compute_model_config(
    selected_candidates: list[dict[str, Any]],
    feedback_by_puzzle: dict[str, dict[str, int]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    stats: dict[str, dict[str, int]] = {}
    labeled_samples = 0
    total_success = 0

    event_totals = {
        "guess_submit": sum(v["guess_submit_count"] for v in feedback_by_puzzle.values()),
        "check_click": sum(v["check_click_count"] for v in feedback_by_puzzle.values()),
        "reveal_click": sum(v["reveal_click_count"] for v in feedback_by_puzzle.values()),
        "abandon": sum(v["abandon_count"] for v in feedback_by_puzzle.values()),
        "total": sum(v["total_count"] for v in feedback_by_puzzle.values()),
    }

    for row in selected_candidates:
        mechanism = str(row["mechanism"])
        feedback = feedback_by_puzzle.get(str(row["puzzle_id"]))
        if feedback is None:
            continue
        label = _derive_label(feedback)
        if label is None:
            continue

        labeled_samples += 1
        total_success += label
        bucket = stats.setdefault(mechanism, {"total": 0, "success": 0})
        bucket["total"] += 1
        bucket["success"] += label

    overall_success = (total_success / labeled_samples) if labeled_samples > 0 else 0.5

    # Beta(1,1) smoothing and map to score band [4.0, 12.0].
    mechanism_base_scores = dict(DEFAULT_MECHANISM_SCORES)
    mechanism_rates: dict[str, dict[str, Any]] = {}
    for mechanism, bucket in stats.items():
        total = bucket["total"]
        success = bucket["success"]
        smoothed_rate = (success + 1) / (total + 2)
        score = round(4.0 + smoothed_rate * 8.0, 2)
        mechanism_base_scores[mechanism] = score
        mechanism_rates[mechanism] = {
            "total": total,
            "success": success,
            "rate": round(success / total, 4) if total else 0.0,
            "smoothedRate": round(smoothed_rate, 4),
            "score": score,
        }

    config_payload = {
        "mechanism_base_scores": mechanism_base_scores,
        "validity_bonus": 12.0,
        "invalid_penalty": 35.0,
        "warning_penalty": 3.0,
        "error_penalty": 12.0,
        "hidden_penalty": 2.0,
        "charade_penalty": 4.0,
        "derivedAt": _utcnow().isoformat(),
    }

    metrics_payload = {
        "selectedCandidates": len(selected_candidates),
        "puzzlesWithFeedback": len(feedback_by_puzzle),
        "labeledSamples": labeled_samples,
        "overallSuccessRate": round(overall_success, 4),
        "eventTotals": event_totals,
        "mechanismRates": mechanism_rates,
    }

    return config_payload, metrics_payload


def train_cryptic_ranker(*, promote: bool = True, notes: str | None = None) -> dict[str, Any]:
    now = _utcnow()
    today = now.date()
    job_id = _job_id()
    model_version = _model_version()

    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            _insert_job(cur, job_id=job_id, job_date=today, model_version=model_version)

            selected_candidates = _load_selected_candidates(cur)
            feedback_by_puzzle = _load_feedback_by_puzzle(cur)
            model_config, metrics = _compute_model_config(selected_candidates, feedback_by_puzzle)

            if promote:
                cur.execute("UPDATE cryptic_model_registry SET is_active = false WHERE is_active = true")

            cur.execute(
                "INSERT INTO cryptic_model_registry ("
                "model_version, model_type, config, metrics, is_active, activated_at, notes, trained_at"
                ") VALUES ("
                "%(model_version)s, %(model_type)s, %(config)s::json, %(metrics)s::json, %(is_active)s, "
                "%(activated_at)s, %(notes)s, %(trained_at)s"
                ") RETURNING id, model_version, model_type, config, metrics, is_active, activated_at, trained_at, created_at",
                {
                    "model_version": model_version,
                    "model_type": "ranker",
                    "config": json.dumps(model_config),
                    "metrics": json.dumps(metrics),
                    "is_active": promote,
                    "activated_at": now if promote else None,
                    "notes": notes,
                    "trained_at": now,
                },
            )
            model_row = cur.fetchone()

            _complete_job(
                cur,
                job_id=job_id,
                status="succeeded",
                logs={
                    "modelVersion": model_version,
                    "promoted": promote,
                    "labeledSamples": metrics.get("labeledSamples", 0),
                    "overallSuccessRate": metrics.get("overallSuccessRate", 0.0),
                },
            )
        conn.commit()

    return {
        "jobId": job_id,
        "model": {
            "id": model_row["id"],
            "modelVersion": model_row["model_version"],
            "modelType": model_row["model_type"],
            "isActive": model_row["is_active"],
            "activatedAt": model_row["activated_at"].isoformat() if model_row["activated_at"] else None,
            "trainedAt": model_row["trained_at"].isoformat() if model_row["trained_at"] else None,
            "createdAt": model_row["created_at"].isoformat() if model_row["created_at"] else None,
            "config": model_row["config"],
            "metrics": model_row["metrics"],
        },
    }


def list_cryptic_models(limit: int = 25) -> list[dict[str, Any]]:
    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id, model_version, model_type, config, metrics, is_active, activated_at, notes, trained_at, created_at "
                "FROM cryptic_model_registry "
                "ORDER BY trained_at DESC LIMIT %(limit)s",
                {"limit": max(1, min(limit, 200))},
            )
            rows = cur.fetchall()

    return [
        {
            "id": row["id"],
            "modelVersion": row["model_version"],
            "modelType": row["model_type"],
            "config": row["config"],
            "metrics": row["metrics"],
            "isActive": row["is_active"],
            "activatedAt": row["activated_at"].isoformat() if row["activated_at"] else None,
            "notes": row["notes"],
            "trainedAt": row["trained_at"].isoformat() if row["trained_at"] else None,
            "createdAt": row["created_at"].isoformat() if row["created_at"] else None,
        }
        for row in rows
    ]


def activate_cryptic_model(model_version: str) -> dict[str, Any] | None:
    now = _utcnow()
    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id FROM cryptic_model_registry WHERE model_version = %(model_version)s",
                {"model_version": model_version},
            )
            existing = cur.fetchone()
            if not existing:
                return None

            cur.execute("UPDATE cryptic_model_registry SET is_active = false WHERE is_active = true")
            cur.execute(
                "UPDATE cryptic_model_registry "
                "SET is_active = true, activated_at = %(activated_at)s "
                "WHERE model_version = %(model_version)s "
                "RETURNING id, model_version, model_type, config, metrics, is_active, activated_at, notes, trained_at, created_at",
                {"activated_at": now, "model_version": model_version},
            )
            row = cur.fetchone()
        conn.commit()

    if not row:
        return None
    return {
        "id": row["id"],
        "modelVersion": row["model_version"],
        "modelType": row["model_type"],
        "config": row["config"],
        "metrics": row["metrics"],
        "isActive": row["is_active"],
        "activatedAt": row["activated_at"].isoformat() if row["activated_at"] else None,
        "notes": row["notes"],
        "trainedAt": row["trained_at"].isoformat() if row["trained_at"] else None,
        "createdAt": row["created_at"].isoformat() if row["created_at"] else None,
    }


def get_active_cryptic_model() -> dict[str, Any] | None:
    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT model_version, config, metrics, trained_at, activated_at "
                "FROM cryptic_model_registry "
                "WHERE is_active = true "
                "ORDER BY activated_at DESC NULLS LAST, trained_at DESC "
                "LIMIT 1"
            )
            row = cur.fetchone()
    if not row:
        return None
    return {
        "modelVersion": row["model_version"],
        "config": row["config"] or {},
        "metrics": row["metrics"] or {},
        "trainedAt": row["trained_at"].isoformat() if row["trained_at"] else None,
        "activatedAt": row["activated_at"].isoformat() if row["activated_at"] else None,
    }


def _serialize_model_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "modelVersion": row["model_version"],
        "modelType": row["model_type"],
        "isActive": row["is_active"],
        "trainedAt": row["trained_at"].isoformat() if row["trained_at"] else None,
        "activatedAt": row["activated_at"].isoformat() if row["activated_at"] else None,
        "metrics": row["metrics"] or {},
    }


def get_cryptic_training_readiness(
    *,
    min_labeled_samples: int = 25,
    min_total_events: int = 100,
) -> dict[str, Any]:
    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            selected_candidates = _load_selected_candidates(cur)
            feedback_by_puzzle = _load_feedback_by_puzzle(cur)

            labeled_samples = 0
            for row in selected_candidates:
                feedback = feedback_by_puzzle.get(str(row["puzzle_id"]))
                if feedback is None:
                    continue
                if _derive_label(feedback) is not None:
                    labeled_samples += 1

            event_counts = {
                "guess_submit": sum(v["guess_submit_count"] for v in feedback_by_puzzle.values()),
                "check_click": sum(v["check_click_count"] for v in feedback_by_puzzle.values()),
                "reveal_click": sum(v["reveal_click_count"] for v in feedback_by_puzzle.values()),
                "abandon": sum(v["abandon_count"] for v in feedback_by_puzzle.values()),
                "total": sum(v["total_count"] for v in feedback_by_puzzle.values()),
            }

            cur.execute(
                "SELECT model_version, model_type, is_active, trained_at, activated_at, metrics "
                "FROM cryptic_model_registry "
                "ORDER BY trained_at DESC "
                "LIMIT 1"
            )
            last_trained_model = cur.fetchone()

            cur.execute(
                "SELECT model_version, model_type, is_active, trained_at, activated_at, metrics "
                "FROM cryptic_model_registry "
                "WHERE is_active = true "
                "ORDER BY activated_at DESC NULLS LAST, trained_at DESC "
                "LIMIT 1"
            )
            active_model = cur.fetchone()

    readiness_issues: list[str] = []
    if labeled_samples < min_labeled_samples:
        readiness_issues.append("labeled_samples_below_threshold")
    if event_counts["total"] < min_total_events:
        readiness_issues.append("event_count_below_threshold")

    return {
        "readyForTraining": len(readiness_issues) == 0,
        "readinessIssues": readiness_issues,
        "thresholds": {
            "minLabeledSamples": min_labeled_samples,
            "minTotalEvents": min_total_events,
        },
        "labeledSamples": labeled_samples,
        "selectedCandidateCount": len(selected_candidates),
        "puzzlesWithFeedback": len(feedback_by_puzzle),
        "eventCounts": event_counts,
        "lastTrainedModel": _serialize_model_row(last_trained_model),
        "activeModel": _serialize_model_row(active_model),
    }
