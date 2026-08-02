"""Audit logging service."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session


def audit(
    db: Session,
    *,
    action: str,
    actor: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
) -> None:
    """Write an audit log entry. Non-critical: failures are logged but do not raise."""
    import json
    import logging

    logger = logging.getLogger(__name__)

    try:
        details_json = json.dumps(details, ensure_ascii=False, default=str) if details else None
        db.execute(
            text(
                """
                INSERT INTO audit_log (action, actor, details, created_at)
                VALUES (:action, :actor, :details, NOW())
                """
            ),
            {"action": action, "actor": actor, "details": details_json},
        )
    except Exception as exc:
        logger.warning("Audit log write failed for action=%s: %s", action, exc)
