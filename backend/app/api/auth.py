"""Authentication API endpoints."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from app.core.db import get_db
from app.core.security import (
    create_session,
    destroy_session,
    hash_password,
    require_auth,
    verify_password,
)

router = APIRouter(prefix="/api", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/auth/login")
def login(payload: LoginRequest, request: Request, response: Response) -> dict:
    """Authenticate and create a session."""
    admin_username = os.getenv("ADMIN_USERNAME", "admin")
    admin_password = os.getenv("ADMIN_PASSWORD", "")

    if not admin_password:
        raise HTTPException(500, "ADMIN_PASSWORD not configured")

    # The admin password is stored in plaintext as an env variable.
    # The hashed version is stored in the database for the User record.
    # For login, we compare against the env variable directly.
    if payload.username != admin_username or payload.password != admin_password:
        raise HTTPException(401, "اسم المستخدم أو كلمة المرور غير صحيحة")

    create_session(response, payload.username)
    return {"message": "تم تسجيل الدخول بنجاح"}


@router.post("/auth/logout")
def logout(request: Request, response: Response) -> dict:
    """Destroy the current session."""
    destroy_session(response)
    return {"message": "تم تسجيل الخروج"}


@router.get("/auth/me")
def get_current_user(username: str = Depends(require_auth)) -> dict:
    """Return the currently authenticated user."""
    return {"username": username}
