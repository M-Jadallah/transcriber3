"""Block until PostgreSQL is ready. Used as a pre-start health gate."""

from __future__ import annotations

import os
import sys
import time

import psycopg


def _database_url() -> str:
    value = os.getenv("DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL is required")
    # SQLAlchemy does not understand the legacy Heroku-style postgres:// prefix.
    if value.startswith("postgres://"):
        value = "postgresql://" + value[len("postgres://"):]
    # psycopg3 (used directly here, NOT through SQLAlchemy) only accepts the
    # bare postgresql:// prefix. SQLAlchemy's postgresql+psycopg:// prefix is
    # NOT understood by psycopg3's connect() and would raise:
    #   "missing '=' after 'postgresql+psycopg://...' in connection info string"
    # So if the URL uses the SQLAlchemy-style prefix, strip the driver suffix
    # for psycopg3's direct use. The SQLAlchemy engine in app.core.db still
    # uses the postgresql+psycopg:// prefix via its own _database_url().
    if value.startswith("postgresql+psycopg://"):
        value = "postgresql://" + value[len("postgresql+psycopg://"):]
    return value


def main() -> None:
    url = _database_url()
    max_attempts = 60
    wait_seconds = 2

    for attempt in range(1, max_attempts + 1):
        try:
            with psycopg.connect(url, connect_timeout=5) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
            print(f"Database is ready (attempt {attempt})", flush=True)
            return
        except Exception as exc:
            print(
                f"Waiting for database... attempt {attempt}/{max_attempts}: {exc}",
                flush=True,
            )
            if attempt == max_attempts:
                print("Database never became ready", file=sys.stderr, flush=True)
                sys.exit(1)
            time.sleep(wait_seconds)


if __name__ == "__main__":
    main()
