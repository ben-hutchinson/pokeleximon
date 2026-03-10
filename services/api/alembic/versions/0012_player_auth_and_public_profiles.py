"""add player auth tables and public profile slugs

Revision ID: 0012_player_auth_and_public_profiles
Revises: 0011_connections_feedback
Create Date: 2026-03-10
"""

from __future__ import annotations

import re

from alembic import op
import sqlalchemy as sa


revision = "0012_player_auth_and_public_profiles"
down_revision = "0011_connections_feedback"
branch_labels = None
depends_on = None

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(value: str, token: str) -> str:
    base = _SLUG_RE.sub("-", (value or "").strip().lower()).strip("-")
    if not base:
        tail = re.sub(r"[^a-z0-9]", "", token.lower())[-6:] or "player"
        base = f"player-{tail}"
    return base[:80].strip("-") or "player"


def upgrade() -> None:
    op.add_column("player_profiles", sa.Column("public_slug", sa.String(length=96), nullable=True))

    bind = op.get_bind()
    rows = list(
        bind.execute(
            sa.text("SELECT player_token, COALESCE(display_name, '') AS display_name FROM player_profiles ORDER BY created_at, player_token")
        ).mappings()
    )
    used: set[str] = set()
    for row in rows:
        token = str(row["player_token"])
        candidate = _slugify(str(row["display_name"]), token)
        slug = candidate
        suffix = 2
        while slug in used:
            slug = f"{candidate[: max(1, 80 - len(str(suffix)) - 1)]}-{suffix}"
            suffix += 1
        used.add(slug)
        bind.execute(
            sa.text("UPDATE player_profiles SET public_slug = :slug WHERE player_token = :player_token"),
            {"slug": slug, "player_token": token},
        )

    op.alter_column("player_profiles", "public_slug", nullable=False)
    op.create_index("ix_player_profiles_public_slug", "player_profiles", ["public_slug"], unique=True, if_not_exists=True)

    op.create_table(
        "player_accounts",
        sa.Column("player_token", sa.String(length=128), primary_key=True),
        sa.Column("username", sa.String(length=32), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("username", name="uq_player_accounts_username"),
    )
    op.create_index("ix_player_accounts_username", "player_accounts", ["username"], unique=True, if_not_exists=True)
    op.create_index("ix_player_accounts_created_at", "player_accounts", ["created_at"], unique=False, if_not_exists=True)
    op.create_index("ix_player_accounts_updated_at", "player_accounts", ["updated_at"], unique=False, if_not_exists=True)
    op.create_index("ix_player_accounts_last_login_at", "player_accounts", ["last_login_at"], unique=False, if_not_exists=True)

    op.create_table(
        "player_auth_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("player_token", sa.String(length=128), nullable=False),
        sa.Column("session_token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("session_token_hash", name="uq_player_auth_sessions_token_hash"),
    )
    op.create_index(
        "ix_player_auth_sessions_player_token",
        "player_auth_sessions",
        ["player_token"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_player_auth_sessions_session_token_hash",
        "player_auth_sessions",
        ["session_token_hash"],
        unique=True,
        if_not_exists=True,
    )
    op.create_index(
        "ix_player_auth_sessions_expires_at",
        "player_auth_sessions",
        ["expires_at"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_player_auth_sessions_revoked_at",
        "player_auth_sessions",
        ["revoked_at"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_player_auth_sessions_created_at",
        "player_auth_sessions",
        ["created_at"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_player_auth_sessions_last_seen_at",
        "player_auth_sessions",
        ["last_seen_at"],
        unique=False,
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_player_auth_sessions_last_seen_at", table_name="player_auth_sessions")
    op.drop_index("ix_player_auth_sessions_created_at", table_name="player_auth_sessions")
    op.drop_index("ix_player_auth_sessions_revoked_at", table_name="player_auth_sessions")
    op.drop_index("ix_player_auth_sessions_expires_at", table_name="player_auth_sessions")
    op.drop_index("ix_player_auth_sessions_session_token_hash", table_name="player_auth_sessions")
    op.drop_index("ix_player_auth_sessions_player_token", table_name="player_auth_sessions")
    op.drop_table("player_auth_sessions")

    op.drop_index("ix_player_accounts_last_login_at", table_name="player_accounts")
    op.drop_index("ix_player_accounts_updated_at", table_name="player_accounts")
    op.drop_index("ix_player_accounts_created_at", table_name="player_accounts")
    op.drop_index("ix_player_accounts_username", table_name="player_accounts")
    op.drop_table("player_accounts")

    op.drop_index("ix_player_profiles_public_slug", table_name="player_profiles")
    op.drop_column("player_profiles", "public_slug")
