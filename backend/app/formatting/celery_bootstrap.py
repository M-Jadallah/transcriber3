"""Celery entry point that registers the optional formatting task."""

try:
    from app.celery_app import celery_app
except ImportError:  # pragma: no cover
    from app.celery_app import app as celery_app  # type: ignore

import app.formatting.tasks  # noqa: E402,F401
