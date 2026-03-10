from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from zoneinfo import ZoneInfo

from app.api.v1.models import JobResponse
from app.core import config
from app.core.observability import capture_exception
from app.core.security import require_admin_auth
from app.data import repo
from app.services.cryptic_ranker import (
    activate_cryptic_model,
    get_cryptic_training_readiness,
    list_cryptic_models,
    train_cryptic_ranker,
)
from app.services.reserve_generator import QualityGateError, generate_cryptic_preview, generate_puzzle_for_date, top_up_reserve

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin_auth)])


@router.post("/generate", response_model=JobResponse)
def generate_puzzle(date: str, gameType: Literal["crossword", "cryptic", "connections"], force: bool = False):
    try:
        target_date = date_type.fromisoformat(date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid date format. Expected YYYY-MM-DD.") from exc

    try:
        result = generate_puzzle_for_date(
            game_type=gameType,
            target_date=target_date,
            timezone=config.TIMEZONE,
            force=force,
        )
    except QualityGateError as exc:
        capture_exception(exc)
        raise HTTPException(status_code=422, detail=exc.to_detail()) from exc
    except Exception as exc:
        capture_exception(exc)
        raise HTTPException(status_code=500, detail="Generation failed") from exc
    return {"jobId": result["jobId"], "status": result["status"]}


@router.post("/publish")
def publish_puzzle(
    date: str,
    gameType: Literal["crossword", "cryptic", "connections"],
    contestMode: bool | None = Query(default=None),
):
    return repo.publish_next_from_reserve(
        date_value=date,
        game_type=gameType,
        timezone=config.TIMEZONE,
        reserve_threshold=config.RESERVE_MIN_COUNT,
        contest_mode=contestMode,
    )


@router.post("/publish/daily")
def publish_daily(
    gameType: Literal["crossword", "cryptic", "connections"],
    date: str | None = None,
    contestMode: bool | None = Query(default=None),
):
    target_date = date
    if target_date is None:
        tz = ZoneInfo(config.TIMEZONE)
        target_date = datetime.now(tz).date().isoformat()
    return repo.publish_next_from_reserve(
        date_value=target_date,
        game_type=gameType,
        timezone=config.TIMEZONE,
        reserve_threshold=config.RESERVE_MIN_COUNT,
        contest_mode=contestMode,
    )


@router.post("/publish/rollback")
def rollback_daily_publish(
    gameType: Literal["crossword", "cryptic", "connections"],
    date: str | None = None,
    sourceDate: str | None = None,
    reason: str = Query(default="manual rollback"),
    executedBy: str = Query(default="admin"),
):
    target_date = date
    if target_date is None:
        tz = ZoneInfo(config.TIMEZONE)
        target_date = datetime.now(tz).date().isoformat()

    try:
        return repo.rollback_daily_publish(
            date_value=target_date,
            game_type=gameType,
            timezone=config.TIMEZONE,
            source_date=sourceDate,
            reason=reason,
            executed_by=executedBy,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/reserve")
def reserve_status(gameType: Literal["crossword", "cryptic", "connections"] | None = None):
    game_types = (gameType,) if gameType else ("crossword", "cryptic", "connections")
    items = [
        repo.get_reserve_status(
            game_type=gt,
            timezone=config.TIMEZONE,
            reserve_threshold=config.RESERVE_MIN_COUNT,
        )
        for gt in game_types
    ]
    return {"items": items, "timezone": config.TIMEZONE}


@router.get("/analytics/summary")
def analytics_summary(
    days: int = Query(default=30, ge=1, le=365),
):
    return repo.get_analytics_summary(days=days, timezone=config.TIMEZONE)


@router.get("/analytics/cryptic/clue-feedback")
def cryptic_clue_feedback_summary(
    days: int = Query(default=30, ge=1, le=365),
):
    return repo.get_cryptic_clue_feedback_summary(days=days, timezone=config.TIMEZONE)


@router.post("/reserve/topup")
def topup_reserve(
    gameType: Literal["crossword", "cryptic", "connections"] | None = Query(default=None),
    targetCount: int | None = Query(default=None, ge=1, le=365),
):
    game_types = (gameType,) if gameType else ("crossword", "cryptic", "connections")
    target = targetCount if targetCount is not None else config.RESERVE_TARGET_COUNT
    items = []
    errors = []
    for gt in game_types:
        try:
            items.append(
                top_up_reserve(
                    game_type=gt,
                    target_count=target,
                    timezone=config.TIMEZONE,
                )
            )
        except QualityGateError as exc:
            errors.append(
                {
                    "gameType": gt,
                    "error": exc.code,
                    "detail": exc.to_detail(),
                }
            )
        except Exception as exc:
            errors.append(
                {
                    "gameType": gt,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    return {"items": items, "errors": errors, "timezone": config.TIMEZONE}


@router.post("/cryptic/generate")
def generate_cryptic(
    answerKey: str | None = Query(default=None),
    limit: int = Query(default=5, ge=1, le=25),
    topK: int = Query(default=3, ge=1, le=10),
    includeInvalid: bool = Query(default=False),
):
    return generate_cryptic_preview(
        limit=limit,
        top_k=topK,
        answer_key=answerKey,
        include_invalid=includeInvalid,
    )


@router.post("/cryptic/train-ranker")
def train_cryptic_ranker_endpoint(
    promote: bool = Query(default=True),
    notes: str | None = Query(default=None),
):
    return train_cryptic_ranker(promote=promote, notes=notes)


@router.get("/cryptic/models")
def list_cryptic_models_endpoint(
    limit: int = Query(default=25, ge=1, le=200),
):
    return {"items": list_cryptic_models(limit=limit)}


@router.get("/cryptic/training-readiness")
def cryptic_training_readiness_endpoint(
    minLabeledSamples: int = Query(default=25, ge=1, le=10000),
    minTotalEvents: int = Query(default=100, ge=1, le=100000),
):
    return get_cryptic_training_readiness(
        min_labeled_samples=minLabeledSamples,
        min_total_events=minTotalEvents,
    )


@router.post("/cryptic/models/{model_version}/activate")
def activate_cryptic_model_endpoint(model_version: str):
    item = activate_cryptic_model(model_version)
    if item is None:
        raise HTTPException(status_code=404, detail="Model not found")
    return {"item": item}


@router.get("/alerts")
def list_alerts(
    gameType: Literal["crossword", "cryptic", "connections"] | None = Query(default=None),
    alertType: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    includeResolved: bool = Query(default=False),
):
    items = repo.get_operational_alerts(
        game_type=gameType,
        alert_type=alertType,
        limit=limit,
        include_resolved=includeResolved,
    )
    return {"items": items}


@router.post("/alerts/{alert_id}/resolve")
def resolve_alert(
    alert_id: int,
    resolvedBy: str = Query(default="admin"),
    note: str | None = Query(default=None),
):
    alert = repo.resolve_operational_alert(
        alert_id=alert_id,
        resolved_by=resolvedBy,
        resolution_note=note,
    )
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"item": alert}


@router.get("/jobs")
def list_jobs(
    status: str | None = Query(default=None),
    type: str | None = Query(default=None),
    date: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    return {"items": repo.list_generation_jobs(status=status, job_type=type, date=date, limit=limit)}


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    item = repo.get_generation_job(job_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"item": item}


@router.post("/puzzles/{puzzle_id}/approve")
def approve_puzzle(
    puzzle_id: str,
    reviewedBy: str = Query(default="admin"),
    note: str | None = Query(default=None),
):
    item = repo.update_puzzle_review_status(
        puzzle_id=puzzle_id,
        status="approved",
        reviewed_by=reviewedBy,
        note=note,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Puzzle not found")
    return {"item": item}


@router.post("/puzzles/{puzzle_id}/reject")
def reject_puzzle(
    puzzle_id: str,
    reviewedBy: str = Query(default="admin"),
    note: str | None = Query(default=None),
    regenerate: bool = Query(default=False),
):
    item = repo.update_puzzle_review_status(
        puzzle_id=puzzle_id,
        status="rejected",
        reviewed_by=reviewedBy,
        note=note,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Puzzle not found")

    regenerate_result = None
    if regenerate:
        if item["publishedAt"] is not None:
            raise HTTPException(
                status_code=409,
                detail="Cannot regenerate a published puzzle. Generate a future reserve puzzle instead.",
            )
        try:
            regenerate_result = generate_puzzle_for_date(
                game_type=item["gameType"],
                target_date=date_type.fromisoformat(item["date"]),
                timezone=config.TIMEZONE,
                force=True,
            )
        except Exception as exc:
            capture_exception(exc)
            raise HTTPException(status_code=500, detail="Regeneration failed") from exc

    return {"item": item, "regenerate": regenerate_result}
