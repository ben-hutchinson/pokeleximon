"""add challenge, leaderboard, and player profile tables

Revision ID: 0010_challenges_leaderboard
Revises: 0009_player_progress
Create Date: 2026-03-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0010_challenges_leaderboard"
down_revision = "0009_player_progress"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "player_profiles",
        sa.Column("player_token", sa.String(length=128), primary_key=True),
        sa.Column("display_name", sa.String(length=48), nullable=True),
        sa.Column("leaderboard_visible", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_player_profiles_leaderboard_visible",
        "player_profiles",
        ["leaderboard_visible"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_player_profiles_created_at",
        "player_profiles",
        ["created_at"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_player_profiles_updated_at",
        "player_profiles",
        ["updated_at"],
        unique=False,
        if_not_exists=True,
    )

    op.create_table(
        "challenges",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("challenge_code", sa.String(length=24), nullable=False),
        sa.Column("game_type", sa.String(length=32), nullable=False),
        sa.Column("puzzle_id", sa.String(length=64), nullable=False),
        sa.Column("puzzle_date", sa.Date(), nullable=False),
        sa.Column("created_by_token", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("challenge_code", name="uq_challenges_code"),
    )
    op.create_index("ix_challenges_challenge_code", "challenges", ["challenge_code"], unique=True, if_not_exists=True)
    op.create_index("ix_challenges_game_type", "challenges", ["game_type"], unique=False, if_not_exists=True)
    op.create_index("ix_challenges_puzzle_id", "challenges", ["puzzle_id"], unique=False, if_not_exists=True)
    op.create_index("ix_challenges_puzzle_date", "challenges", ["puzzle_date"], unique=False, if_not_exists=True)
    op.create_index(
        "ix_challenges_created_by_token",
        "challenges",
        ["created_by_token"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index("ix_challenges_created_at", "challenges", ["created_at"], unique=False, if_not_exists=True)

    op.create_table(
        "challenge_members",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("challenge_id", sa.Integer(), nullable=False),
        sa.Column("player_token", sa.String(length=128), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("challenge_id", "player_token", name="uq_challenge_member"),
    )
    op.create_index(
        "ix_challenge_members_challenge_id",
        "challenge_members",
        ["challenge_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_challenge_members_player_token",
        "challenge_members",
        ["player_token"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index("ix_challenge_members_joined_at", "challenge_members", ["joined_at"], unique=False, if_not_exists=True)

    op.create_table(
        "leaderboard_submissions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("player_token", sa.String(length=128), nullable=False),
        sa.Column("game_type", sa.String(length=32), nullable=False),
        sa.Column("puzzle_id", sa.String(length=64), nullable=False),
        sa.Column("puzzle_date", sa.Date(), nullable=False),
        sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("solve_time_ms", sa.Integer(), nullable=True),
        sa.Column("used_assists", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("used_reveals", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("player_token", "puzzle_id", name="uq_leaderboard_player_puzzle"),
    )
    op.create_index(
        "ix_leaderboard_submissions_player_token",
        "leaderboard_submissions",
        ["player_token"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_leaderboard_submissions_game_type",
        "leaderboard_submissions",
        ["game_type"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_leaderboard_submissions_puzzle_id",
        "leaderboard_submissions",
        ["puzzle_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_leaderboard_submissions_puzzle_date",
        "leaderboard_submissions",
        ["puzzle_date"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_leaderboard_submissions_completed",
        "leaderboard_submissions",
        ["completed"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_leaderboard_submissions_solve_time_ms",
        "leaderboard_submissions",
        ["solve_time_ms"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_leaderboard_submissions_session_id",
        "leaderboard_submissions",
        ["session_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_leaderboard_submissions_submitted_at",
        "leaderboard_submissions",
        ["submitted_at"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_leaderboard_submissions_updated_at",
        "leaderboard_submissions",
        ["updated_at"],
        unique=False,
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_leaderboard_submissions_updated_at", table_name="leaderboard_submissions")
    op.drop_index("ix_leaderboard_submissions_submitted_at", table_name="leaderboard_submissions")
    op.drop_index("ix_leaderboard_submissions_session_id", table_name="leaderboard_submissions")
    op.drop_index("ix_leaderboard_submissions_solve_time_ms", table_name="leaderboard_submissions")
    op.drop_index("ix_leaderboard_submissions_completed", table_name="leaderboard_submissions")
    op.drop_index("ix_leaderboard_submissions_puzzle_date", table_name="leaderboard_submissions")
    op.drop_index("ix_leaderboard_submissions_puzzle_id", table_name="leaderboard_submissions")
    op.drop_index("ix_leaderboard_submissions_game_type", table_name="leaderboard_submissions")
    op.drop_index("ix_leaderboard_submissions_player_token", table_name="leaderboard_submissions")
    op.drop_table("leaderboard_submissions")

    op.drop_index("ix_challenge_members_joined_at", table_name="challenge_members")
    op.drop_index("ix_challenge_members_player_token", table_name="challenge_members")
    op.drop_index("ix_challenge_members_challenge_id", table_name="challenge_members")
    op.drop_table("challenge_members")

    op.drop_index("ix_challenges_created_at", table_name="challenges")
    op.drop_index("ix_challenges_created_by_token", table_name="challenges")
    op.drop_index("ix_challenges_puzzle_date", table_name="challenges")
    op.drop_index("ix_challenges_puzzle_id", table_name="challenges")
    op.drop_index("ix_challenges_game_type", table_name="challenges")
    op.drop_index("ix_challenges_challenge_code", table_name="challenges")
    op.drop_table("challenges")

    op.drop_index("ix_player_profiles_updated_at", table_name="player_profiles")
    op.drop_index("ix_player_profiles_created_at", table_name="player_profiles")
    op.drop_index("ix_player_profiles_leaderboard_visible", table_name="player_profiles")
    op.drop_table("player_profiles")
