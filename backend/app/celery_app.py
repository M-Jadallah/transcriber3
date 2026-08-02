"""Celery application for the transcription workers."""

from __future__ import annotations

import os

from celery import Celery


def _redis_url() -> str:
    value = os.getenv("REDIS_URL", "").strip()
    if not value:
        raise RuntimeError("REDIS_URL is required")
    return value


celery_app = Celery(
    "transcriber",
    broker=_redis_url(),
    backend=_redis_url(),
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Amman",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    broker_transport_options={
        "visibility_timeout": 7200,
    },
)

# Auto-discover tasks from the transcription pipeline.
# Celery's autodiscover_tasks searches each listed package for a ``tasks``
# submodule, so passing ["app"] registers ``app.tasks.transcribe``.
celery_app.autodiscover_tasks(["app"])

# Make sure the transcription task is registered eagerly when this module is
# imported directly (e.g. by the API container that only needs to enqueue work
# via ``celery_app.send_task``). Without this, workers running with
# ``-A app.celery_app`` would not see the task on cold start.
try:
    import app.tasks  # noqa: F401, E402
except Exception:  # pragma: no cover - import-time errors are surfaced by the worker
    pass
