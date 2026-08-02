"""Database connection, session management, and startup utilities."""

from __future__ import annotations

import os
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Base class for all ORM models."""


def _database_url() -> str:
    value = os.getenv("DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL is required")
    # SQLAlchemy does not understand the legacy Heroku-style postgres:// prefix.
    if value.startswith("postgres://"):
        value = "postgresql://" + value[len("postgres://"):]
    # Normalize the bare postgresql:// prefix to postgresql+psycopg:// so
    # SQLAlchemy selects the psycopg3 driver (this project installs only
    # psycopg[binary], not psycopg2). Without this, create_engine() raises:
    # ModuleNotFoundError: No module named 'psycopg2'.
    if value.startswith("postgresql://"):
        value = "postgresql+psycopg://" + value[len("postgresql://"):]
    return value


engine = create_engine(
    _database_url(),
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_recycle=300,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
