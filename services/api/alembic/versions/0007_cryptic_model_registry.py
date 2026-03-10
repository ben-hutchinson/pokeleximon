"""add cryptic model registry

Revision ID: 0007_cryptic_model_registry
Revises: 0006_cryptic_feedback
Create Date: 2026-02-11
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0007_cryptic_model_registry"
down_revision = "0006_cryptic_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cryptic_model_registry",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("model_version", sa.String(length=96), nullable=False),
        sa.Column("model_type", sa.String(length=32), nullable=False, server_default="ranker"),
        sa.Column("config", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("metrics", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("trained_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("model_version", name="uq_cryptic_model_registry_model_version"),
    )
    op.create_index(
        "ix_cryptic_model_registry_model_version",
        "cryptic_model_registry",
        ["model_version"],
        unique=True,
        if_not_exists=True,
    )
    op.create_index(
        "ix_cryptic_model_registry_model_type",
        "cryptic_model_registry",
        ["model_type"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_cryptic_model_registry_is_active",
        "cryptic_model_registry",
        ["is_active"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_cryptic_model_registry_trained_at",
        "cryptic_model_registry",
        ["trained_at"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_cryptic_model_registry_created_at",
        "cryptic_model_registry",
        ["created_at"],
        unique=False,
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_cryptic_model_registry_created_at", table_name="cryptic_model_registry")
    op.drop_index("ix_cryptic_model_registry_trained_at", table_name="cryptic_model_registry")
    op.drop_index("ix_cryptic_model_registry_is_active", table_name="cryptic_model_registry")
    op.drop_index("ix_cryptic_model_registry_model_type", table_name="cryptic_model_registry")
    op.drop_index("ix_cryptic_model_registry_model_version", table_name="cryptic_model_registry")
    op.drop_table("cryptic_model_registry")
