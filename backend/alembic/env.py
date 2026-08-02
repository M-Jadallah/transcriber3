from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.engine import Connection
from sqlalchemy.pool import NullPool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The formatting migration uses explicit Alembic operations, so model metadata
# is intentionally not imported. This keeps migration startup independent from
# the application's ORM layout.
target_metadata = None


def _database_url() -> str:
    value = os.getenv("DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL is required to run Alembic migrations")

    # SQLAlchemy does not understand the legacy Heroku-style postgres:// prefix.
    if value.startswith("postgres://"):
        value = "postgresql://" + value[len("postgres://") :]

    # SQLAlchemy maps the bare postgresql:// prefix to the psycopg2 driver by
    # default. This project installs psycopg3 (psycopg[binary]) only, so we
    # rewrite the URL to use the psycopg3 driver explicitly. Without this,
    # create_engine() raises: ModuleNotFoundError: No module named 'psycopg2'.
    if value.startswith("postgresql://"):
        value = "postgresql+psycopg://" + value[len("postgresql://") :]
    return value


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def _run_with_connection(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        transaction_per_migration=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(
        _database_url(),
        poolclass=NullPool,
        pool_pre_ping=True,
    )
    try:
        with engine.connect() as connection:
            _run_with_connection(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
