"""Jobs API endpoints for the transcription pipeline."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from app.core.db import get_db
from app.core.models import Export, Job, Transcript
from app.core.security import require_auth, require_csrf
from app.services.export_service import ensure_exports

router = APIRouter(prefix="/api", tags=["jobs"])
Db = Depends(get_db)
Admin = Depends(require_csrf)


class CreateJobRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    language: Optional[str] = Field(default=None, max_length=10)
    model: Optional[str] = Field(default=None, max_length=100)


@router.post("/jobs")
def create_job(payload: CreateJobRequest, db: Session = Db, admin: str = Admin) -> dict:
    """Create a new transcription job."""
    job_id = str(uuid.uuid4())
    language = payload.language or os.getenv("DEFAULT_LANGUAGE", "ar")
    model = payload.model or os.getenv("DEFAULT_DEEPGRAM_MODEL", "whisper-large")

    job = Job(
        id=job_id,
        url=payload.url,
        status="pending",
        language=language,
        model=model,
    )
    db.add(job)
    db.commit()

    # Dispatch to Celery
    from app.celery_app import celery_app
    celery_app.send_task(
        "app.tasks.transcribe",
        args=[job_id],
        queue="default",
    )

    return {"id": job_id, "status": "pending", "url": payload.url}


@router.get("/jobs")
def list_jobs(
    db: Session = Db,
    _: str = Depends(require_auth),
    status: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[dict]:
    """List transcription jobs."""
    query = select(Job).order_by(Job.created_at.desc()).offset(offset).limit(limit)
    if status:
        query = query.where(Job.status == status)

    jobs = db.execute(query).scalars().all()
    return [
        {
            "id": job.id,
            "url": job.url,
            "title": job.title,
            "status": job.status,
            "language": job.language,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        }
        for job in jobs
    ]


@router.get("/jobs/{job_id}")
def get_job(job_id: str, db: Session = Db, _: str = Depends(require_auth)) -> dict:
    """Get details of a specific job."""
    job = db.execute(
        select(Job)
        .where(Job.id == job_id)
        .options(selectinload(Job.transcript), selectinload(Job.exports))
    ).scalar_one_or_none()

    if not job:
        raise HTTPException(404, "المهمة غير موجودة")

    result = {
        "id": job.id,
        "url": job.url,
        "title": job.title,
        "status": job.status,
        "language": job.language,
        "model": job.model,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }

    if job.transcript:
        result["transcript"] = {
            "text": job.transcript.text,
            "id": job.transcript.id,
        }

    if job.exports:
        result["exports"] = [
            {
                "id": export.id,
                "format": export.format,
                "file_name": export.file_name,
                "size_bytes": export.size_bytes,
            }
            for export in job.exports
        ]

    return result


@router.get("/jobs/{job_id}/exports/{export_id}/download")
def download_export(
    job_id: str,
    export_id: int,
    db: Session = Db,
    _: str = Depends(require_auth),
) -> FileResponse:
    """Download a specific export file."""
    export = db.execute(
        select(Export).where(
            Export.id == export_id,
            Export.job_id == job_id,
        )
    ).scalar_one_or_none()

    if not export:
        raise HTTPException(404, "الملف غير موجود")

    path = Path(export.file_path)
    if not path.is_file():
        raise HTTPException(404, "الملف غير موجود على التخزين")

    return FileResponse(
        path,
        media_type=export.mime_type,
        filename=export.file_name,
    )


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: str, db: Session = Db, admin: str = Admin) -> dict:
    """Retry a failed job."""
    job = db.execute(select(Job).where(Job.id == job_id)).scalar_one_or_none()
    if not job:
        raise HTTPException(404, "المهمة غير موجودة")
    if job.status not in ("failed", "cancelled"):
        raise HTTPException(409, "لا يمكن إعادة محاولة مهمة نشطة")

    job.status = "pending"
    job.error_message = None
    db.commit()

    from app.celery_app import celery_app
    celery_app.send_task(
        "app.tasks.transcribe",
        args=[job_id],
        queue="default",
    )

    return {"id": job_id, "status": "pending"}


@router.delete("/jobs/{job_id}")
def cancel_job(job_id: str, db: Session = Db, admin: str = Admin) -> dict:
    """Cancel a pending job."""
    job = db.execute(select(Job).where(Job.id == job_id)).scalar_one_or_none()
    if not job:
        raise HTTPException(404, "المهمة غير موجودة")
    if job.status not in ("pending", "queued"):
        raise HTTPException(409, "لا يمكن إلغاء مهمة مكتملة")

    job.status = "cancelled"
    db.commit()
    return {"id": job_id, "status": "cancelled"}
