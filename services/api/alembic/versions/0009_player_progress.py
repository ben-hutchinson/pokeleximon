"""add player progress storage for cloud sync

Revision ID: 0009_player_progress
Revises: 0008_crossword_feedback
Create Date: 2026-03-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0009_player_progress"
down_revision = "0008_crossword_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "player_progress",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("player_token", sa.String(length=128), nullable=False),
        sa.Column("progress_key", sa.String(length=128), nullable=False),
        sa.Column("game_type", sa.String(length=32), nullable=True),
        sa.Column("puzzle_id", sa.String(length=64), nullable=True),
        sa.Column("progress", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("client_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("player_token", "progress_key", name="uq_player_progress_token_key"),
    )
    op.create_index(
        "ix_player_progress_player_token",
        "player_progress",
        ["player_token"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_player_progress_progress_key",
        "player_progress",
        ["progress_key"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_player_progress_game_type",
        "player_progress",
        ["game_type"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_player_progress_puzzle_id",
        "player_progress",
        ["puzzle_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_player_progress_client_updated_at",
        "player_progress",
        ["client_updated_at"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_player_progress_updated_at",
        "player_progress",
        ["updated_at"],
        unique=False,
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_player_progress_updated_at", table_name="player_progress")
    op.drop_index("ix_player_progress_client_updated_at", table_name="player_progress")
    op.drop_index("ix_player_progress_puzzle_id", table_name="player_progress")
    op.drop_index("ix_player_progress_game_type", table_name="player_progress")
    op.drop_index("ix_player_progress_progress_key", table_name="player_progress")
    op.drop_index("ix_player_progress_player_token", table_name="player_progress")
    op.drop_table("player_progress")
