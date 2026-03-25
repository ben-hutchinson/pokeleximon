"""add avatar preset to player profiles

Revision ID: 0013_player_profile_avatar_preset
Revises: 0012_player_auth_and_public_profiles
Create Date: 2026-03-12 19:20:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0013_player_profile_avatar_preset"
down_revision = "0012_player_auth_and_public_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("player_profiles", sa.Column("avatar_preset", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("player_profiles", "avatar_preset")
