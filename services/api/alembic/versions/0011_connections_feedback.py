"""add connections feedback telemetry table

Revision ID: 0011_connections_feedback
Revises: 0010_challenges_leaderboard
Create Date: 2026-03-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0011_connections_feedback"
down_revision = "0010_challenges_leaderboard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "connections_feedback",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("puzzle_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("event_value", sa.JSON(), nullable=False),
        sa.Column("client_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_connections_feedback_puzzle_id",
        "connections_feedback",
        ["puzzle_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_connections_feedback_event_type",
        "connections_feedback",
        ["event_type"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_connections_feedback_session_id",
        "connections_feedback",
        ["session_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_connections_feedback_created_at",
        "connections_feedback",
        ["created_at"],
        unique=False,
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_connections_feedback_created_at", table_name="connections_feedback")
    op.drop_index("ix_connections_feedback_session_id", table_name="connections_feedback")
    op.drop_index("ix_connections_feedback_event_type", table_name="connections_feedback")
    op.drop_index("ix_connections_feedback_puzzle_id", table_name="connections_feedback")
    op.drop_table("connections_feedback")
