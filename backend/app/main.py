"""FastAPI application entry point."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, health, jobs, settings
from app.api.formatting import router as formatting_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    # Startup: ensure database tables exist
    from app.core.db import Base, engine
    from app.core.models import (  # noqa: F401 - ensure models are imported for create_all
        AuditLog,
        Export,
        Job,
        Setting,
        Transcript,
        User,
    )

    # Only create tables that don't exist yet; Alembic handles migrations
    # in production, but for first-run we ensure the base schema exists.
    if os.getenv("APP_ENV", "production") != "production":
        Base.metadata.create_all(bind=engine)

    # Ensure the admin user exists
    _ensure_admin_user()

    yield


def _ensure_admin_user() -> None:
    """Create the default admin user if it doesn't exist."""
    from app.core.db import SessionLocal
    from app.core.models import User
    from app.core.security import hash_password
    from sqlalchemy import select

    admin_username = os.getenv("ADMIN_USERNAME", "admin")
    admin_password = os.getenv("ADMIN_PASSWORD", "")

    if not admin_password:
        return

    with SessionLocal() as db:
        existing = db.execute(
            select(User).where(User.username == admin_username)
        ).scalar_one_or_none()

        if not existing:
            user = User(
                username=admin_username,
                password_hash=hash_password(admin_password),
            )
            db.add(user)
            db.commit()


app = FastAPI(
    title="YouTube Transcriber",
    description="YouTube video transcription and AI formatting service",
    version=os.getenv("APP_VERSION", "1.0.0"),
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)

# CORS middleware for development and cross-origin scenarios
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("APP_URL", "")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routers
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(jobs.router)
app.include_router(settings.router)
app.include_router(formatting_router)
