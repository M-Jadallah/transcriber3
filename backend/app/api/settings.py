"""Application settings API endpoints."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.models import Setting
from app.core.security import require_auth, require_csrf

router = APIRouter(prefix="/api", tags=["settings"])
Db = Depends(get_db)
Admin = Depends(require_csrf)


@router.get("/settings")
def get_settings(db: Session = Db, _: str = Depends(require_auth)) -> dict:
    """Get all application settings."""
    settings = db.execute(select(Setting)).scalars().all()
    return {setting.key: setting.value for setting in settings}


@router.put("/settings")
def update_settings(
    payload: dict[str, str],
    db: Session = Db,
    admin: str = Admin,
) -> dict:
    """Update application settings."""
    for key, value in payload.items():
        existing = db.execute(
            select(Setting).where(Setting.key == key)
        ).scalar_one_or_none()
        if existing:
            existing.value = value
        else:
            db.add(Setting(key=key, value=value))
    db.commit()
    return {"message": "تم حفظ الإعدادات"}
