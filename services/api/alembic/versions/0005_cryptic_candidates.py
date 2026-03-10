"""add cryptic candidate storage

Revision ID: 0005_cryptic_candidates
Revises: 0004_alert_resolution_fields
Create Date: 2026-02-11
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0005_cryptic_candidates"
down_revision = "0004_alert_resolution_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cryptic_candidates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("puzzle_id", sa.String(length=64), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("source_ref", sa.String(length=128), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("answer_key", sa.String(length=64), nullable=False),
        sa.Column("answer_display", sa.String(length=200), nullable=False),
        sa.Column("clue_text", sa.Text(), nullable=False),
        sa.Column("mechanism", sa.String(length=32), nullable=False),
        sa.Column("wordplay_plan", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("validator_passed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("validator_issues", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("rank_score", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("rank_position", sa.Integer(), nullable=False, server_default=sa.text("999")),
        sa.Column("selected", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_cryptic_candidates_job_id", "cryptic_candidates", ["job_id"], unique=False, if_not_exists=True)
    op.create_index(
        "ix_cryptic_candidates_puzzle_id", "cryptic_candidates", ["puzzle_id"], unique=False, if_not_exists=True
    )
    op.create_index(
        "ix_cryptic_candidates_target_date", "cryptic_candidates", ["target_date"], unique=False, if_not_exists=True
    )
    op.create_index(
        "ix_cryptic_candidates_source_type", "cryptic_candidates", ["source_type"], unique=False, if_not_exists=True
    )
    op.create_index(
        "ix_cryptic_candidates_answer_key", "cryptic_candidates", ["answer_key"], unique=False, if_not_exists=True
    )
    op.create_index(
        "ix_cryptic_candidates_mechanism", "cryptic_candidates", ["mechanism"], unique=False, if_not_exists=True
    )
    op.create_index(
        "ix_cryptic_candidates_validator_passed",
        "cryptic_candidates",
        ["validator_passed"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_cryptic_candidates_rank_score", "cryptic_candidates", ["rank_score"], unique=False, if_not_exists=True
    )
    op.create_index(
        "ix_cryptic_candidates_selected", "cryptic_candidates", ["selected"], unique=False, if_not_exists=True
    )
    op.create_index(
        "ix_cryptic_candidates_created_at", "cryptic_candidates", ["created_at"], unique=False, if_not_exists=True
    )


def downgrade() -> None:
    op.drop_index("ix_cryptic_candidates_created_at", table_name="cryptic_candidates")
    op.drop_index("ix_cryptic_candidates_selected", table_name="cryptic_candidates")
    op.drop_index("ix_cryptic_candidates_rank_score", table_name="cryptic_candidates")
    op.drop_index("ix_cryptic_candidates_validator_passed", table_name="cryptic_candidates")
    op.drop_index("ix_cryptic_candidates_mechanism", table_name="cryptic_candidates")
    op.drop_index("ix_cryptic_candidates_answer_key", table_name="cryptic_candidates")
    op.drop_index("ix_cryptic_candidates_source_type", table_name="cryptic_candidates")
    op.drop_index("ix_cryptic_candidates_target_date", table_name="cryptic_candidates")
    op.drop_index("ix_cryptic_candidates_puzzle_id", table_name="cryptic_candidates")
    op.drop_index("ix_cryptic_candidates_job_id", table_name="cryptic_candidates")
    op.drop_table("cryptic_candidates")
