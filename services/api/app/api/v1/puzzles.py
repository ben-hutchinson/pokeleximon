from __future__ import annotations

import logging
from typing import Literal
from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.api.v1.models import (
    ArchiveResponse,
    ClientErrorRequest,
    ClientErrorResponse,
    ConnectionsTelemetryRequest,
    ConnectionsTelemetryResponse,
    CrypticClueFeedbackRequest,
    CrypticClueFeedbackResponse,
    CrosswordTelemetryRequest,
    CrosswordTelemetryResponse,
    CrypticTelemetryRequest,
    CrypticTelemetryResponse,
    PersonalStatsResponse,
    PlayerProfileResponse,
    PlayerProfileUpdateRequest,
    PublicPlayerStatsResponse,
    ChallengeCreateRequest,
    ChallengeDetailResponse,
    ChallengeJoinResponse,
    ChallengeResponse,
    GlobalLeaderboardResponse,
    LeaderboardSubmitRequest,
    LeaderboardSubmitResponse,
    PuzzleProgressRequest,
    PuzzleProgressResponse,
    PuzzleResponse,
    PuzzleSummaryResponse,
    ResponseMeta,
)
from app.core import config
from app.core.observability import capture_message
from app.data import sample
from app.data import repo
from app.services.puzzle_export import build_pdf_export_bytes, build_text_export_payload

router = APIRouter(prefix="/puzzles", tags=["puzzles"])
logger = logging.getLogger(__name__)


def _connections_enabled_or_404() -> None:
    if not config.FEATURE_CONNECTIONS_ENABLED:
        raise HTTPException(status_code=404, detail="Connections is not enabled")


def _resolve_export_puzzle(
    *,
    game_type: Literal["crossword", "cryptic"],
    date: str | None,
    puzzle_id: str | None,
) -> dict:
    if puzzle_id:
        puzzle = repo.get_puzzle_by_id(puzzle_id)
    else:
        puzzle = repo.get_puzzle_by_date(game_type, date, timezone=config.TIMEZONE)
    if puzzle is None:
        raise HTTPException(status_code=404, detail="Puzzle not found")
    return puzzle


def _resolve_player_token(request: Request, fallback_query_token: str | None = None) -> str:
    session_payload = repo.get_player_auth_session(session_token=request.cookies.get(config.AUTH_SESSION_COOKIE_NAME, ""))
    session_token = (session_payload.get("playerToken") or "").strip()
    if session_token:
        return session_token
    header_token = request.headers.get("x-player-token")
    resolved_token = (header_token or fallback_query_token or "").strip()
    if not resolved_token:
        raise HTTPException(status_code=422, detail="Missing player token")
    return resolved_token


def _resolve_optional_player_token(request: Request, fallback_query_token: str | None = None) -> str | None:
    session_payload = repo.get_player_auth_session(session_token=request.cookies.get(config.AUTH_SESSION_COOKIE_NAME, ""))
    session_token = (session_payload.get("playerToken") or "").strip()
    if session_token:
        return session_token
    resolved_token = (request.headers.get("x-player-token") or fallback_query_token or "").strip()
    return resolved_token or None


@router.get("/daily", response_model=PuzzleResponse)
def get_daily_puzzle(
    date: str | None = Query(default=None, description="YYYY-MM-DD Europe/London"),
    gameType: Literal["crossword", "cryptic", "connections"] = Query(default="crossword"),
    redact_answers: bool = Query(default=False),
):
    if gameType == "connections":
        _connections_enabled_or_404()
    puzzle = repo.get_puzzle_by_date(gameType, date, timezone=config.TIMEZONE)
    if puzzle is None:
        raise HTTPException(status_code=404, detail="Puzzle not found")
    if redact_answers:
        puzzle = sample.redact_puzzle(puzzle)
    return {"data": puzzle, "meta": ResponseMeta(redactedAnswers=redact_answers)}


@router.get("/archive", response_model=ArchiveResponse)
def get_archive(
    gameType: Literal["crossword", "cryptic", "connections", "all"] = Query(default="all"),
    cursor: str | None = None,
    limit: int = 30,
    difficulty: Literal["easy", "medium", "hard"] | None = Query(default=None),
    q: str | None = Query(default=None, description="Title text search"),
    themeTag: list[str] | None = Query(default=None),
    dateFrom: str | None = Query(default=None, description="YYYY-MM-DD"),
    dateTo: str | None = Query(default=None, description="YYYY-MM-DD"),
):
    if gameType == "connections":
        _connections_enabled_or_404()
    try:
        archive = repo.get_archive(
            None if gameType == "all" else gameType,
            limit=limit,
            cursor=cursor,
            difficulty=difficulty,
            title_query=q,
            theme_tags=themeTag,
            date_from=dateFrom,
            date_to=dateTo,
            include_connections=config.FEATURE_CONNECTIONS_ENABLED,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"data": archive}


@router.post("/cryptic/telemetry", response_model=CrypticTelemetryResponse)
def create_cryptic_telemetry(payload: CrypticTelemetryRequest, request: Request):
    item = repo.create_cryptic_feedback(
        puzzle_id=payload.puzzleId,
        event_type=payload.eventType,
        session_id=payload.sessionId,
        event_value=payload.eventValue,
        candidate_id=payload.candidateId,
        client_ts=payload.clientTs,
        user_agent=request.headers.get("user-agent"),
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Cryptic puzzle not found")
    return {"data": item}


@router.post("/cryptic/clue-feedback", response_model=CrypticClueFeedbackResponse)
def create_cryptic_clue_feedback(payload: CrypticClueFeedbackRequest, request: Request):
    item, duplicate = repo.create_cryptic_clue_feedback(
        puzzle_id=payload.puzzleId,
        entry_id=payload.entryId,
        rating=payload.rating,
        reason_tags=payload.reasonTags,
        session_id=payload.sessionId,
        candidate_id=payload.candidateId,
        mechanism=payload.mechanism,
        clue_text=payload.clueText,
        client_ts=payload.clientTs,
        user_agent=request.headers.get("user-agent"),
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Cryptic puzzle not found")
    return {"data": item, "duplicate": duplicate}


@router.post("/crossword/telemetry", response_model=CrosswordTelemetryResponse)
def create_crossword_telemetry(payload: CrosswordTelemetryRequest, request: Request):
    item = repo.create_crossword_feedback(
        puzzle_id=payload.puzzleId,
        event_type=payload.eventType,
        session_id=payload.sessionId,
        event_value=payload.eventValue,
        client_ts=payload.clientTs,
        user_agent=request.headers.get("user-agent"),
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Crossword puzzle not found")
    return {"data": item}


@router.post("/connections/telemetry", response_model=ConnectionsTelemetryResponse)
def create_connections_telemetry(payload: ConnectionsTelemetryRequest, request: Request):
    _connections_enabled_or_404()
    item = repo.create_connections_feedback(
        puzzle_id=payload.puzzleId,
        event_type=payload.eventType,
        session_id=payload.sessionId,
        event_value=payload.eventValue,
        client_ts=payload.clientTs,
        user_agent=request.headers.get("user-agent"),
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Connections puzzle not found")
    return {"data": item}


@router.get("/stats/personal", response_model=PersonalStatsResponse)
def get_personal_stats(
    days: int = Query(default=30, ge=1, le=365),
    sessionId: list[str] | None = Query(default=None, description="Repeat to include multiple session ids"),
):
    clean_session_ids = sorted({sid.strip() for sid in (sessionId or []) if sid and sid.strip()})[:20]
    return {"data": repo.get_personal_stats(session_ids=clean_session_ids, days=days, timezone=config.TIMEZONE)}


@router.get("/stats/me", response_model=PersonalStatsResponse)
def get_authenticated_player_stats(request: Request, days: int = Query(default=30, ge=1, le=365)):
    token = _resolve_player_token(request)
    return {"data": repo.get_player_stats(player_token=token, days=days, timezone=config.TIMEZONE)}


@router.get("/players/{publicSlug}", response_model=PublicPlayerStatsResponse)
def get_public_player_stats(publicSlug: str, days: int = Query(default=30, ge=1, le=365)):
    item = repo.get_public_player_stats(public_slug=publicSlug, days=days, timezone=config.TIMEZONE)
    if item is None:
        raise HTTPException(status_code=404, detail="Player not found")
    return {"data": item}


@router.get("/profile", response_model=PlayerProfileResponse)
def get_player_profile(
    request: Request,
    playerToken: str | None = Query(default=None, min_length=1, max_length=128),
):
    token = _resolve_player_token(request, playerToken)
    return {"data": repo.get_or_create_player_profile(player_token=token)}


@router.put("/profile", response_model=PlayerProfileResponse)
def put_player_profile(payload: PlayerProfileUpdateRequest, request: Request):
    token = _resolve_player_token(request)
    try:
        item = repo.update_player_profile(
            player_token=token,
            display_name=payload.displayName,
            leaderboard_visible=payload.leaderboardVisible,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"data": item}


@router.post("/challenges", response_model=ChallengeResponse)
def create_challenge(payload: ChallengeCreateRequest, request: Request):
    token = _resolve_player_token(request)
    try:
        item = repo.create_challenge(
            player_token=token,
            game_type=payload.gameType,
            puzzle_id=payload.puzzleId,
            date_value=payload.date,
            timezone=config.TIMEZONE,
        )
    except ValueError as exc:
        detail = str(exc)
        if "limit reached" in detail.lower():
            raise HTTPException(status_code=429, detail=detail) from exc
        raise HTTPException(status_code=422, detail=detail) from exc
    return {"data": item}


@router.post("/challenges/{challenge_code}/join", response_model=ChallengeJoinResponse)
def join_challenge(challenge_code: str, request: Request, limit: int = Query(default=25, ge=1, le=100)):
    token = _resolve_player_token(request)
    item = repo.join_challenge(player_token=token, challenge_code=challenge_code, limit=limit)
    if item is None:
        raise HTTPException(status_code=404, detail="Challenge not found")
    return {"data": item}


@router.get("/challenges/{challenge_code}", response_model=ChallengeDetailResponse)
def get_challenge(
    challenge_code: str,
    request: Request,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    playerToken: str | None = Query(default=None, min_length=1, max_length=128),
):
    token = _resolve_optional_player_token(request, playerToken)
    item = repo.get_challenge_detail(challenge_code=challenge_code, player_token=token or None, limit=limit, cursor=cursor)
    if item is None:
        raise HTTPException(status_code=404, detail="Challenge not found")
    return {"data": item}


@router.post("/leaderboard/submit", response_model=LeaderboardSubmitResponse)
def submit_leaderboard(payload: LeaderboardSubmitRequest, request: Request):
    token = _resolve_player_token(request)
    try:
        item = repo.submit_leaderboard_result(
            player_token=token,
            game_type=payload.gameType,
            puzzle_id=payload.puzzleId,
            puzzle_date=payload.puzzleDate,
            completed=payload.completed,
            solve_time_ms=payload.solveTimeMs,
            used_assists=payload.usedAssists,
            used_reveals=payload.usedReveals,
            session_id=payload.sessionId,
        )
    except ValueError as exc:
        detail = str(exc)
        if "rate limit" in detail.lower():
            raise HTTPException(status_code=429, detail=detail) from exc
        raise HTTPException(status_code=422, detail=detail) from exc
    return {"data": item}


@router.get("/leaderboard", response_model=GlobalLeaderboardResponse)
def get_leaderboard(
    gameType: Literal["crossword", "cryptic"] = Query(default="crossword"),
    scope: Literal["daily", "weekly"] = Query(default="daily"),
    date: str | None = Query(default=None, description="YYYY-MM-DD"),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
):
    return {
        "data": repo.get_global_leaderboard(
            game_type=gameType,
            scope=scope,
            date_value=date,
            timezone=config.TIMEZONE,
            limit=limit,
            cursor=cursor,
        )
    }


@router.get("/export/text")
def export_text(
    gameType: Literal["crossword", "cryptic"] = Query(default="crossword"),
    date: str | None = Query(default=None, description="YYYY-MM-DD"),
    puzzleId: str | None = Query(default=None),
):
    puzzle = _resolve_export_puzzle(game_type=gameType, date=date, puzzle_id=puzzleId)
    redacted = sample.redact_puzzle(puzzle)
    return {"data": build_text_export_payload(redacted), "meta": ResponseMeta(redactedAnswers=True)}


@router.get("/export/pdf")
def export_pdf(
    gameType: Literal["crossword", "cryptic"] = Query(default="crossword"),
    date: str | None = Query(default=None, description="YYYY-MM-DD"),
    puzzleId: str | None = Query(default=None),
):
    puzzle = _resolve_export_puzzle(game_type=gameType, date=date, puzzle_id=puzzleId)
    redacted = sample.redact_puzzle(puzzle)
    payload = build_text_export_payload(redacted)
    pdf_bytes = build_pdf_export_bytes(payload)
    game_type = payload.get("gameType") or gameType
    puzzle_date = payload.get("date") or "puzzle"
    filename = f"pokeleximon-{game_type}-{puzzle_date}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/progress", response_model=PuzzleProgressResponse)
def get_progress(
    request: Request,
    key: str = Query(..., min_length=1, max_length=128),
    playerToken: str | None = Query(default=None, min_length=1, max_length=128),
):
    resolved_token = _resolve_player_token(request, playerToken)
    return {"data": repo.get_player_progress(player_token=resolved_token, key=key)}


@router.put("/progress", response_model=PuzzleProgressResponse)
def put_progress(payload: PuzzleProgressRequest, request: Request):
    resolved_token = _resolve_player_token(request)
    item = repo.upsert_player_progress(
        player_token=resolved_token,
        key=payload.key,
        game_type=payload.gameType,
        puzzle_id=payload.puzzleId,
        progress=payload.progress,
        client_updated_at=payload.clientUpdatedAt,
    )
    return {"data": item}


@router.get("/{puzzle_id}", response_model=PuzzleResponse)
def get_puzzle_by_id(
    puzzle_id: str,
    redact_answers: bool = Query(default=False),
):
    puzzle = repo.get_puzzle_by_id(puzzle_id)
    if puzzle is None:
        raise HTTPException(status_code=404, detail="Puzzle not found")
    if puzzle.get("gameType") == "connections" and not config.FEATURE_CONNECTIONS_ENABLED:
        raise HTTPException(status_code=404, detail="Puzzle not found")
    if redact_answers:
        puzzle = sample.redact_puzzle(puzzle)
    return {"data": puzzle, "meta": ResponseMeta(redactedAnswers=redact_answers)}


@router.get("/{puzzle_id}/metadata", response_model=PuzzleSummaryResponse)
def get_metadata(puzzle_id: str):
    summary = repo.get_metadata(puzzle_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Puzzle not found")
    if summary.get("gameType") == "connections" and not config.FEATURE_CONNECTIONS_ENABLED:
        raise HTTPException(status_code=404, detail="Puzzle not found")
    return {"data": summary}


@router.post("/client-errors", response_model=ClientErrorResponse)
def create_client_error(payload: ClientErrorRequest, request: Request):
    details = dict(payload.details)
    details["requestUserAgent"] = request.headers.get("user-agent")
    logger.error(
        "client_error: event=%s route=%s message=%s details=%s",
        payload.eventType,
        payload.route,
        payload.message,
        details,
    )
    capture_message(
        f"client_error[{payload.eventType}] route={payload.route or 'unknown'} message={payload.message}",
        level="error",
    )
    return {"ok": True}
