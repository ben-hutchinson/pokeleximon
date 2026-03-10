"""reserve-first publishing ops schema

Revision ID: 0003_reserve_publish_ops
Revises: 0002_seed_sample
Create Date: 2026-02-11
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003_reserve_publish_ops"
down_revision = "0002_seed_sample"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operational_alerts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("alert_type", sa.String(length=64), nullable=False),
        sa.Column("game_type", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False, server_default="warning"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("dedupe_key", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("dedupe_key", name="uq_operational_alerts_dedupe_key"),
    )
    op.create_index(
        "ix_operational_alerts_alert_type",
        "operational_alerts",
        ["alert_type"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_operational_alerts_game_type",
        "operational_alerts",
        ["game_type"],
        unique=False,
        if_not_exists=True,
    )
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_puzzles_published_date "
            "ON puzzles (game_type, date) WHERE published_at IS NOT NULL"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS uq_puzzles_published_date"))
    op.drop_index("ix_operational_alerts_game_type", table_name="operational_alerts")
    op.drop_index("ix_operational_alerts_alert_type", table_name="operational_alerts")
    op.drop_table("operational_alerts")
