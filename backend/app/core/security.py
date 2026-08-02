"""Authentication, session management, and CSRF protection."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from fastapi import Cookie, Depends, HTTPException, Request, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from itsdangerous import SignatureExpired, URLSafeTimedSerializer
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.models import User


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

SESSION_COOKIE_NAME = "session"
CSRF_COOKIE_NAME = "csrf_token"

_serializer: Optional[URLSafeTimedSerializer] = None


def _get_serializer() -> URLSafeTimedSerializer:
    global _serializer
    if _serializer is None:
        secret = os.getenv("SESSION_SECRET", "")
        if not secret:
            raise RuntimeError("SESSION_SECRET is required")
        _serializer = URLSafeTimedSerializer(secret)
    return _serializer


def create_session(response: Response, username: str) -> str:
    """Create a signed session token and set cookies."""
    serializer = _get_serializer()
    csrf_token = secrets.token_hex(32)
    payload = {"username": username, "csrf": csrf_token}
    token = serializer.dumps(payload)

    ttl_minutes = int(os.getenv("SESSION_TTL_MINUTES", "720"))
    max_age = ttl_minutes * 60
    secure = os.getenv("COOKIE_SECURE", "false").lower() in ("true", "1", "yes")

    # Do NOT set the Domain attribute on the cookie. When Domain is omitted,
    # the browser uses "host-only" matching: the cookie is sent only to the
    # exact host that set it. This is the most reliable approach for same-
    # origin authentication and avoids subtle domain-matching bugs.
    #
    # Previously, Domain was derived from TRUSTED_HOSTS. If TRUSTED_HOSTS
    # contained unexpected formatting (trailing spaces, a port number, mixed
    # case, or a comma-separated list with a malformed first entry), the
    # browser would silently reject the Set-Cookie header — causing the
    # login to "succeed" (200 OK) but the session cookie to never be stored,
    # so the immediate /api/auth/me check returned 401 and the user was
    # bounced back to the login page.
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        csrf_token,
        max_age=max_age,
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/",
    )
    return token


def _get_session_payload(request: Request) -> dict[str, Any]:
    """Extract and validate the session payload from the request."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(401, "غير مسجل الدخول")

    serializer = _get_serializer()
    idle_minutes = int(os.getenv("SESSION_IDLE_MINUTES", "120"))
    try:
        payload = serializer.loads(token, max_age=idle_minutes * 60)
    except SignatureExpired:
        raise HTTPException(401, "انتهت صلاحية الجلسة")
    except Exception:
        raise HTTPException(401, "جلسة غير صالحة")

    if not isinstance(payload, dict) or "username" not in payload or "csrf" not in payload:
        raise HTTPException(401, "جلسة غير صالحة")
    return payload


def require_auth(request: Request) -> str:
    """Return the authenticated username or raise 401."""
    payload = _get_session_payload(request)
    return str(payload["username"])


def require_csrf(request: Request) -> str:
    """Validate CSRF token and return the authenticated username."""
    payload = _get_session_payload(request)
    csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME, "")
    csrf_header = request.headers.get("X-CSRF-Token", "")
    expected_csrf = payload.get("csrf", "")

    if not expected_csrf:
        raise HTTPException(401, "جلسة غير صالحة")

    # The CSRF token must come from either the cookie or the header
    if not hmac.compare_digest(csrf_cookie, expected_csrf) and not hmac.compare_digest(
        csrf_header, expected_csrf
    ):
        raise HTTPException(403, "رمز CSRF غير صالح")

    return str(payload["username"])


def destroy_session(response: Response) -> None:
    """Clear session and CSRF cookies."""
    # Match the attributes used in create_session (no Domain, path="/").
    # If Domain were set here but not in create_session (or vice versa), the
    # browser would not delete the cookie.
    secure = os.getenv("COOKIE_SECURE", "false").lower() in ("true", "1", "yes")

    response.delete_cookie(SESSION_COOKIE_NAME, path="/", secure=secure)
    response.delete_cookie(CSRF_COOKIE_NAME, path="/", secure=secure)
