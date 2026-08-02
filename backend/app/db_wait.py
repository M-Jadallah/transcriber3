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
    if value.startswith("postgres://"):
        value = "postgresql://" + value[len("postgres://"):]
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
