"""initial schema

Revision ID: 0001_initial
Revises: 
Create Date: 2026-02-10
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "puzzles",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("date", sa.Date(), nullable=False, index=True),
        sa.Column("game_type", sa.String(length=32), nullable=False, index=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="Europe/London"),
        sa.Column("grid", sa.JSON(), nullable=False),
        sa.Column("entries", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("ix_puzzles_date", "puzzles", ["date"], unique=False, if_not_exists=True)
    op.create_index("ix_puzzles_game_type", "puzzles", ["game_type"], unique=False, if_not_exists=True)

    op.create_table(
        "generation_jobs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("type", sa.String(length=32), nullable=False, index=True),
        sa.Column("date", sa.Date(), nullable=False, index=True),
        sa.Column("status", sa.String(length=32), nullable=False, index=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("logs_url", sa.Text(), nullable=True),
        sa.Column("model_version", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_jobs_type", "generation_jobs", ["type"], unique=False, if_not_exists=True)
    op.create_index("ix_jobs_date", "generation_jobs", ["date"], unique=False, if_not_exists=True)
    op.create_index("ix_jobs_status", "generation_jobs", ["status"], unique=False, if_not_exists=True)

    op.create_table(
        "poke_data_cache",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("resource_type", sa.String(length=64), nullable=False, index=True),
        sa.Column("resource_id", sa.String(length=64), nullable=False, index=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("cached_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("etag", sa.String(length=128), nullable=True),
        sa.UniqueConstraint("resource_type", "resource_id", name="uq_resource"),
    )
    op.create_index("ix_cache_type", "poke_data_cache", ["resource_type"], unique=False, if_not_exists=True)
    op.create_index("ix_cache_id", "poke_data_cache", ["resource_id"], unique=False, if_not_exists=True)


def downgrade() -> None:
    op.drop_index("ix_cache_id", table_name="poke_data_cache")
    op.drop_index("ix_cache_type", table_name="poke_data_cache")
    op.drop_table("poke_data_cache")

    op.drop_index("ix_jobs_status", table_name="generation_jobs")
    op.drop_index("ix_jobs_date", table_name="generation_jobs")
    op.drop_index("ix_jobs_type", table_name="generation_jobs")
    op.drop_table("generation_jobs")

    op.drop_index("ix_puzzles_game_type", table_name="puzzles")
    op.drop_index("ix_puzzles_date", table_name="puzzles")
    op.drop_table("puzzles")
