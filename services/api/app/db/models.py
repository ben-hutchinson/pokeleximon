from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Date, DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Puzzle(Base):
    __tablename__ = "puzzles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    date: Mapped[datetime] = mapped_column(Date, nullable=False, index=True)
    game_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Europe/London")

    grid: Mapped[dict] = mapped_column(JSON, nullable=False)
    entries: Mapped[list] = mapped_column(JSON, nullable=False)
    puzzle_metadata: Mapped[dict] = mapped_column("metadata", JSON, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class GenerationJob(Base):
    __tablename__ = "generation_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    date: Mapped[datetime] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    logs_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PokeDataCache(Base):
    __tablename__ = "poke_data_cache"
    __table_args__ = (UniqueConstraint("resource_type", "resource_id", name="uq_resource"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    cached_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    etag: Mapped[str | None] = mapped_column(String(128), nullable=True)


class OperationalAlert(Base):
    __tablename__ = "operational_alerts"
    __table_args__ = (UniqueConstraint("dedupe_key", name="uq_operational_alerts_dedupe_key"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    alert_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    game_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="warning")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    dedupe_key: Mapped[str] = mapped_column(String(128), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    resolved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CrypticCandidate(Base):
    __tablename__ = "cryptic_candidates"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    puzzle_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_date: Mapped[datetime] = mapped_column(Date, nullable=False, index=True)

    source_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    answer_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    answer_display: Mapped[str] = mapped_column(String(200), nullable=False)

    clue_text: Mapped[str] = mapped_column(Text, nullable=False)
    mechanism: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    wordplay_plan: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    validator_passed: Mapped[bool] = mapped_column(nullable=False, default=False, index=True)
    validator_issues: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    rank_score: Mapped[float] = mapped_column(nullable=False, default=0.0, index=True)
    rank_position: Mapped[int] = mapped_column(nullable=False, default=999)
    selected: Mapped[bool] = mapped_column(nullable=False, default=False, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class CrypticFeedback(Base):
    __tablename__ = "cryptic_feedback"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    puzzle_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    candidate_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    event_value: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    client_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class CrosswordFeedback(Base):
    __tablename__ = "crossword_feedback"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    puzzle_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    event_value: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    client_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class ConnectionsFeedback(Base):
    __tablename__ = "connections_feedback"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    puzzle_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    event_value: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    client_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class PlayerProgress(Base):
    __tablename__ = "player_progress"
    __table_args__ = (UniqueConstraint("player_token", "progress_key", name="uq_player_progress_token_key"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    player_token: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    progress_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    game_type: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    puzzle_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    progress: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    client_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class PlayerProfile(Base):
    __tablename__ = "player_profiles"

    player_token: Mapped[str] = mapped_column(String(128), primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String(48), nullable=True)
    leaderboard_visible: Mapped[bool] = mapped_column(nullable=False, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), index=True
    )


class Challenge(Base):
    __tablename__ = "challenges"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    challenge_code: Mapped[str] = mapped_column(String(24), nullable=False, unique=True, index=True)
    game_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    puzzle_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    puzzle_date: Mapped[datetime] = mapped_column(Date, nullable=False, index=True)
    created_by_token: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class ChallengeMember(Base):
    __tablename__ = "challenge_members"
    __table_args__ = (UniqueConstraint("challenge_id", "player_token", name="uq_challenge_member"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    challenge_id: Mapped[int] = mapped_column(nullable=False, index=True)
    player_token: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class LeaderboardSubmission(Base):
    __tablename__ = "leaderboard_submissions"
    __table_args__ = (UniqueConstraint("player_token", "puzzle_id", name="uq_leaderboard_player_puzzle"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    player_token: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    game_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    puzzle_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    puzzle_date: Mapped[datetime] = mapped_column(Date, nullable=False, index=True)
    completed: Mapped[bool] = mapped_column(nullable=False, default=False, index=True)
    solve_time_ms: Mapped[int | None] = mapped_column(nullable=True, index=True)
    used_assists: Mapped[bool] = mapped_column(nullable=False, default=False)
    used_reveals: Mapped[bool] = mapped_column(nullable=False, default=False)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), index=True
    )


class CrypticModelRegistry(Base):
    __tablename__ = "cryptic_model_registry"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    model_version: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    model_type: Mapped[str] = mapped_column(String(32), nullable=False, default="ranker", index=True)
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=False, index=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
