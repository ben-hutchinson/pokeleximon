"""add alert resolution fields

Revision ID: 0004_alert_resolution_fields
Revises: 0003_reserve_publish_ops
Create Date: 2026-02-11
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0004_alert_resolution_fields"
down_revision = "0003_reserve_publish_ops"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("operational_alerts", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("operational_alerts", sa.Column("resolved_by", sa.String(length=64), nullable=True))
    op.add_column("operational_alerts", sa.Column("resolution_note", sa.Text(), nullable=True))
    op.create_index(
        "ix_operational_alerts_resolved_at",
        "operational_alerts",
        ["resolved_at"],
        unique=False,
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_operational_alerts_resolved_at", table_name="operational_alerts")
    op.drop_column("operational_alerts", "resolution_note")
    op.drop_column("operational_alerts", "resolved_by")
    op.drop_column("operational_alerts", "resolved_at")
