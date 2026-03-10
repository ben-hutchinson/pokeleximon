"""add crossword feedback telemetry storage

Revision ID: 0008_crossword_feedback
Revises: 0007_cryptic_model_registry
Create Date: 2026-02-17
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0008_crossword_feedback"
down_revision = "0007_cryptic_model_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crossword_feedback",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("puzzle_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("event_value", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("client_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["puzzle_id"], ["puzzles.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_crossword_feedback_puzzle_id",
        "crossword_feedback",
        ["puzzle_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_crossword_feedback_event_type",
        "crossword_feedback",
        ["event_type"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_crossword_feedback_session_id",
        "crossword_feedback",
        ["session_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_crossword_feedback_created_at",
        "crossword_feedback",
        ["created_at"],
        unique=False,
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_crossword_feedback_created_at", table_name="crossword_feedback")
    op.drop_index("ix_crossword_feedback_session_id", table_name="crossword_feedback")
    op.drop_index("ix_crossword_feedback_event_type", table_name="crossword_feedback")
    op.drop_index("ix_crossword_feedback_puzzle_id", table_name="crossword_feedback")
    op.drop_table("crossword_feedback")
