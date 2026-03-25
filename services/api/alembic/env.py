from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy import engine_from_config, pool
from alembic import context

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(BASE_DIR))

from app.db.models import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def ensure_alembic_version_table(connection) -> None:
    # Newer revision identifiers exceed Alembic's default VARCHAR(32) width.
    connection.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS alembic_version (
                version_num VARCHAR(255) NOT NULL PRIMARY KEY
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            ALTER TABLE alembic_version
            ALTER COLUMN version_num TYPE VARCHAR(255)
            """
        )
    )
    connection.commit()


def get_database_url() -> str:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")
    return database_url


def run_migrations_offline() -> None:
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_database_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        ensure_alembic_version_table(connection)
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


def main() -> None:
    if context.is_offline_mode():
        run_migrations_offline()
    else:
        run_migrations_online()


main()
