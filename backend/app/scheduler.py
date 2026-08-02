"""Periodic scheduler for maintenance tasks (audio cleanup, etc.)."""

from __future__ import annotations

import logging
import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.models import Job

logger = logging.getLogger(__name__)


def _retention_hours() -> int:
    return max(1, int(os.getenv("AUDIO_RETENTION_HOURS", "24")))


def _audio_root() -> Path:
    return Path(os.getenv("AUDIO_ROOT", "/data/audio"))


def _exports_root() -> Path:
    return Path(os.getenv("EXPORTS_ROOT", "/data/exports"))


def cleanup_expired_audio() -> int:
    """Remove audio files for jobs older than the retention period."""
    audio_root = _audio_root()
    if not audio_root.is_dir():
        return 0

    cutoff = datetime.now(UTC) - timedelta(hours=_retention_hours())
    removed = 0

    with SessionLocal() as db:
        jobs = db.execute(
            select(Job).where(Job.completed_at.isnot(None), Job.completed_at < cutoff)
        ).scalars().all()

        for job in jobs:
            job_dir = audio_root / job.id
            if job_dir.is_dir():
                try:
                    shutil.rmtree(job_dir)
                    removed += 1
                    logger.info("Removed expired audio for job %s", job.id)
                except OSError as exc:
                    logger.warning("Failed to remove audio for job %s: %s", job.id, exc)

    return removed


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    scheduler = BlockingScheduler(timezone="Asia/Amman")
    scheduler.add_job(
        cleanup_expired_audio,
        "interval",
        hours=1,
        id="cleanup_expired_audio",
        name="Clean up expired audio files",
    )

    logger.info("Scheduler started (audio retention: %d hours)", _retention_hours())

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")


if __name__ == "__main__":
    main()
