from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.db import get_db
from app.core.models import Job
from app.core.security import require_csrf
from app.formatting.config import FormattingConfig, get_formatting_config
from app.formatting.opencode_client import OpenCodeClient, OpenCodeUnavailable
from app.formatting.repository import (
    ActiveFormattingJobError,
    cancel_job,
    create_job,
    disable_skill_with_replacement,
    get_artifact,
    get_job,
    get_settings,
    get_skill,
    get_skill_by_sha,
    has_active_jobs,
    insert_skill,
    latest_for_sources,
    list_artifacts,
    list_jobs,
    list_skills,
    new_id,
    set_skill_enabled,
    update_settings,
)
from app.formatting.runtime import (
    FormattingRuntimeError,
    FormattingStorageCapacityError,
    discard_persistent_job_workspace,
    ensure_formatting_storage_capacity,
    persistent_artifact_path,
    require_file_hash,
    require_safe_export_file,
    sha256_file,
    stage_input_snapshot,
)
from app.formatting.skills import SkillArchiveError, install_skill_archive
from app.services.export_service import ensure_exports
from app.services.log_service import audit

router = APIRouter(prefix="/api/formatting", tags=["formatting"])
Db = Annotated[Session, Depends(get_db)]
Admin = Annotated[str, Depends(require_csrf)]
Reasoning = Literal["low", "medium", "high", "xhigh"]


class SettingsPayload(BaseModel):
    enabled: bool = True
    default_model: str = Field(min_length=2, max_length=200)
    default_reasoning: Reasoning = "high"
    default_skill_id: str | None = None


class CreateFormattingJob(BaseModel):
    source_job_id: str = Field(min_length=1, max_length=100)
    skill_id: str | None = None
    model: str | None = Field(default=None, max_length=200)
    reasoning: Reasoning | None = None


class OAuthStart(BaseModel):
    provider_id: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$",
    )
    method_index: int = Field(ge=0, le=50)
    inputs: dict[str, str] = Field(default_factory=dict)


class OAuthCallback(BaseModel):
    provider_id: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$",
    )
    method_index: int = Field(ge=0, le=50)
    code: str | None = Field(default=None, max_length=8000)


def _serialize(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _clean(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _serialize(value) for key, value in row.items()}


def _public_skill(row: dict[str, Any]) -> dict[str, Any]:
    return _clean({
        key: value
        for key, value in row.items()
        if key not in {"archive_path", "extracted_path"}
    })


def _public_artifact(row: dict[str, Any]) -> dict[str, Any]:
    return _clean({key: value for key, value in row.items() if key != "file_path"})


def _opencode_client() -> OpenCodeClient:
    return OpenCodeClient(get_formatting_config())


def _status_name(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip().casefold()
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, str):
        return enum_value.strip().casefold()
    enum_name = getattr(value, "name", None)
    if isinstance(enum_name, str):
        return enum_name.strip().casefold()
    return None


def _discard_staged_job(config: FormattingConfig, formatting_job_id: str) -> None:
    try:
        discard_persistent_job_workspace(config, formatting_job_id)
    except (FormattingRuntimeError, OSError):
        # Unsafe cleanup targets are deliberately retained for operator review.
        pass


@router.get("/settings")
def read_formatting_settings(db: Db, _: Admin) -> dict[str, Any]:
    settings = _clean(get_settings(db))
    settings["skills"] = [_public_skill(item) for item in list_skills(db)]
    return settings


@router.put("/settings")
def save_formatting_settings(
    payload: SettingsPayload,
    db: Db,
    admin: Admin,
) -> dict[str, Any]:
    clean_model = payload.default_model.strip()
    if not clean_model or "/" not in clean_model:
        raise HTTPException(422, "معرّف النموذج يجب أن يكون بصيغة provider/model")
    if payload.default_skill_id:
        skill = get_skill(db, payload.default_skill_id)
        if not skill or not skill.get("is_enabled"):
            raise HTTPException(422, "المهارة الافتراضية غير متاحة")
    result = update_settings(
        db,
        enabled=payload.enabled,
        default_model=clean_model,
        default_reasoning=payload.default_reasoning,
        default_skill_id=payload.default_skill_id,
    )
    audit(
        db,
        action="update_formatting_settings",
        actor=admin,
        details={
            "model": clean_model,
            "reasoning": payload.default_reasoning,
            "skill_id": payload.default_skill_id,
        },
    )
    response = _clean(result)
    response["skills"] = [_public_skill(item) for item in list_skills(db)]
    return response


@router.get("/skills")
def skills(
    db: Db,
    _: Admin,
    include_disabled: bool = False,
) -> list[dict[str, Any]]:
    return [_public_skill(item) for item in list_skills(db, include_disabled)]


@router.post("/skills")
async def upload_skill(
    db: Db,
    admin: Admin,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    config = get_formatting_config()
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(422, "يجب رفع ملف ZIP")
    blob = await file.read(config.skill_max_archive_bytes + 1)
    if len(blob) > config.skill_max_archive_bytes:
        raise HTTPException(413, "حجم ملف المهارة أكبر من الحد المسموح")
    try:
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext('formatting:storage'))")
        )
        active_reservations = int(
            db.execute(
                text(
                    "SELECT COUNT(*) FROM formatting_jobs "
                    "WHERE status IN ('queued', 'running')"
                )
            ).scalar_one()
        )
        ensure_formatting_storage_capacity(
            config,
            existing_reservations=active_reservations,
            additional_reservation_bytes=(
                len(blob) + config.skill_max_unpacked_bytes
            ),
        )
    except FormattingStorageCapacityError as exc:
        db.rollback()
        raise HTTPException(507, str(exc)) from exc
    except FormattingRuntimeError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
    try:
        installed = install_skill_archive(blob, config)
    except SkillArchiveError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc

    existing = get_skill_by_sha(db, installed.sha256)
    if existing:
        if not existing.get("is_enabled"):
            set_skill_enabled(db, str(existing["id"]), True)
            existing = get_skill(db, str(existing["id"])) or existing
        current = get_settings(db)
        if not current.get("default_skill_id"):
            update_settings(
                db,
                enabled=bool(current.get("enabled", True)),
                default_model=str(current.get("default_model") or config.default_model),
                default_reasoning=str(
                    current.get("default_reasoning") or config.default_reasoning
                ),
                default_skill_id=str(existing["id"]),
            )
        return _public_skill(existing)

    try:
        record = insert_skill(
            db,
            {
                "name": installed.name,
                "slug": installed.slug,
                "description": installed.description,
                "sha256": installed.sha256,
                "archive_path": str(installed.archive_path),
                "extracted_path": str(installed.extracted_path),
                "metadata": installed.metadata,
            },
        )
    except IntegrityError:
        # Another request stored the same content-addressed archive first.
        db.rollback()
        existing = get_skill_by_sha(db, installed.sha256)
        if not existing:
            raise
        if not existing.get("is_enabled"):
            set_skill_enabled(db, str(existing["id"]), True)
            existing = get_skill(db, str(existing["id"])) or existing
        current = get_settings(db)
        if not current.get("default_skill_id"):
            update_settings(
                db,
                enabled=bool(current.get("enabled", True)),
                default_model=str(current.get("default_model") or config.default_model),
                default_reasoning=str(
                    current.get("default_reasoning") or config.default_reasoning
                ),
                default_skill_id=str(existing["id"]),
            )
        return _public_skill(existing)
    current = get_settings(db)
    if not current.get("default_skill_id"):
        update_settings(
            db,
            enabled=bool(current.get("enabled", True)),
            default_model=str(current.get("default_model") or config.default_model),
            default_reasoning=str(
                current.get("default_reasoning") or config.default_reasoning
            ),
            default_skill_id=str(record["id"]),
        )
    audit(
        db,
        action="upload_formatting_skill",
        actor=admin,
        details={"skill_id": record["id"], "sha256": installed.sha256},
    )
    return _public_skill(record)


@router.post("/skills/{skill_id}/enable")
def enable_skill(skill_id: str, db: Db, admin: Admin) -> dict[str, str]:
    if not get_skill(db, skill_id):
        raise HTTPException(404, "المهارة غير موجودة")
    set_skill_enabled(db, skill_id, True)
    audit(
        db,
        action="enable_formatting_skill",
        actor=admin,
        details={"skill_id": skill_id},
    )
    return {"message": "تم تفعيل المهارة"}


@router.delete("/skills/{skill_id}")
def disable_skill(skill_id: str, db: Db, admin: Admin) -> dict[str, str]:
    if not get_skill(db, skill_id):
        raise HTTPException(404, "المهارة غير موجودة")
    disable_skill_with_replacement(db, skill_id)
    audit(
        db,
        action="disable_formatting_skill",
        actor=admin,
        details={"skill_id": skill_id},
    )
    return {"message": "تم تعطيل المهارة دون التأثير على المهام السابقة"}


@router.get("/auth/status")
def auth_status(_: Admin) -> dict[str, Any]:
    client = _opencode_client()
    health = client.health()
    if health is None:
        return {
            "available": False,
            "connected": False,
            "connected_providers": [],
            "auth_methods": {},
            "providers": [],
        }
    try:
        providers = client.providers()
        methods = client.auth_methods()
    except OpenCodeUnavailable as exc:
        return {
            "available": False,
            "connected": False,
            "error": str(exc),
            "connected_providers": [],
            "auth_methods": {},
            "providers": [],
        }
    connected = providers.get("connected", []) if isinstance(providers, dict) else []
    all_providers = providers.get("all", []) if isinstance(providers, dict) else []
    return {
        "available": True,
        "version": health.get("version"),
        "connected": bool(connected),
        "connected_providers": connected,
        "auth_methods": methods,
        "providers": all_providers,
        "default_models": providers.get("default", {}),
    }


@router.post("/auth/start")
def auth_start(payload: OAuthStart, _: Admin) -> dict[str, Any]:
    try:
        return _opencode_client().start_oauth(
            payload.provider_id,
            payload.method_index,
            payload.inputs,
        )
    except OpenCodeUnavailable as exc:
        raise HTTPException(502, str(exc)) from exc


@router.post("/auth/callback")
def auth_callback(payload: OAuthCallback, _: Admin) -> dict[str, Any]:
    try:
        success = _opencode_client().finish_oauth(
            payload.provider_id,
            payload.method_index,
            payload.code,
        )
    except OpenCodeUnavailable as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"success": success}


@router.post("/auth/logout")
def auth_logout(admin: Admin, db: Db) -> dict[str, Any]:
    if has_active_jobs(db):
        raise HTTPException(409, "لا يمكن فصل الحساب أثناء وجود مهام تنسيق نشطة")
    try:
        result = _opencode_client().logout()
    except OpenCodeUnavailable as exc:
        raise HTTPException(502, str(exc)) from exc
    audit(
        db,
        action="logout_formatting_provider",
        actor=admin,
        details={"restarting": bool(result.get("restarting"))},
    )
    return result


@router.post("/jobs")
def enqueue_formatting(
    payload: CreateFormattingJob,
    db: Db,
    admin: Admin,
) -> dict[str, Any]:
    config = get_formatting_config()
    settings = get_settings(db)
    if not settings.get("enabled", True):
        raise HTTPException(422, "ميزة التنسيق معطلة من الإعدادات")

    skill_id = payload.skill_id or settings.get("default_skill_id")
    if not skill_id:
        raise HTTPException(422, "اختر مهارة أولًا")
    skill = get_skill(db, str(skill_id))
    if not skill or not skill.get("is_enabled"):
        raise HTTPException(422, "المهارة غير متاحة")

    source = db.execute(
        select(Job)
        .where(Job.id == payload.source_job_id)
        .options(selectinload(Job.transcript), selectinload(Job.exports))
    ).scalar_one_or_none()
    if (
        source is None
        or source.transcript is None
        or _status_name(getattr(source, "status", None)) != "completed"
    ):
        raise HTTPException(422, "التفريغ الأصلي غير مكتمل")

    exports = ensure_exports(db, source)
    txt = next((item for item in exports if item.format == "txt"), None)
    if txt is None:
        raise HTTPException(422, "تعذر تجهيز نص TXT من التفريغ الأصلي")
    try:
        transcript_path, transcript_stat = require_safe_export_file(
            config,
            Path(txt.file_path),
        )
    except FormattingRuntimeError as exc:
        raise HTTPException(422, str(exc)) from exc

    model = str(payload.model or settings.get("default_model") or config.default_model).strip()
    if not model or len(model) > 200 or "/" not in model:
        raise HTTPException(422, "معرّف النموذج يجب أن يكون بصيغة provider/model")
    reasoning = str(
        payload.reasoning
        or settings.get("default_reasoning")
        or config.default_reasoning
    )
    formatting_job_id = new_id()
    try:
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext('formatting:storage'))")
        )
        active_reservations = int(
            db.execute(
                text(
                    "SELECT COUNT(*) FROM formatting_jobs "
                    "WHERE status IN ('queued', 'running')"
                )
            ).scalar_one()
        )
        ensure_formatting_storage_capacity(
            config,
            existing_reservations=active_reservations,
        )
    except FormattingStorageCapacityError as exc:
        db.rollback()
        raise HTTPException(507, str(exc)) from exc
    except FormattingRuntimeError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc

    try:
        input_hash = sha256_file(
            transcript_path,
            max_bytes=config.input_max_bytes,
        )
        snapshot_path = stage_input_snapshot(
            config,
            formatting_job_id,
            transcript_path,
            transcript_stat.st_size,
            input_hash,
        )
        require_file_hash(
            snapshot_path,
            input_hash,
            "Snapshot إدخال مهمة التنسيق",
            max_bytes=config.input_max_bytes,
        )
        if snapshot_path.lstat().st_size != transcript_stat.st_size:
            raise FormattingRuntimeError("حجم Snapshot الإدخال لا يطابق تصدير TXT")
    except Exception as exc:
        db.rollback()
        _discard_staged_job(config, formatting_job_id)
        raise HTTPException(500, "تعذر تجهيز مهمة التنسيق") from exc

    try:
        record = create_job(
            db,
            job_id=formatting_job_id,
            source_job_id=payload.source_job_id,
            skill=skill,
            model=model,
            reasoning=reasoning,
            input_hash=input_hash,
            requested_by=admin,
        )
    except ActiveFormattingJobError as exc:
        _discard_staged_job(config, formatting_job_id)
        raise HTTPException(
            409,
            f"توجد محاولة تنسيق نشطة لهذا التفريغ: {exc.job_id}",
        ) from exc
    except Exception as exc:
        db.rollback()
        _discard_staged_job(config, formatting_job_id)
        raise HTTPException(500, "تعذر إنشاء سجل مهمة التنسيق") from exc

    try:
        audit(
            db,
            action="enqueue_formatting_job",
            actor=admin,
            details={
                "formatting_job_id": record["id"],
                "source_job_id": payload.source_job_id,
                "skill_id": skill_id,
                "model": model,
                "reasoning": reasoning,
            },
        )
    except Exception:
        # The job and outbox event are already durable. Audit availability must
        # not turn a successfully queued request into an API failure.
        db.rollback()
    return _clean(record)


@router.get("/jobs")
def formatting_jobs(
    db: Db,
    _: Admin,
    source_job_id: str | None = None,
    limit: int = Query(100, ge=1, le=500),
) -> list[dict[str, Any]]:
    return [_clean(item) for item in list_jobs(db, source_job_id, limit)]


@router.get("/jobs/latest")
def latest_jobs(db: Db, _: Admin, job_ids: str = "") -> dict[str, Any]:
    ids = [item.strip() for item in job_ids.split(",") if item.strip()][:100]
    return {
        key: _clean(value)
        for key, value in latest_for_sources(db, ids).items()
    }


@router.get("/jobs/{formatting_job_id}")
def formatting_job(
    formatting_job_id: str,
    db: Db,
    _: Admin,
) -> dict[str, Any]:
    job = get_job(db, formatting_job_id)
    if not job:
        raise HTTPException(404, "مهمة التنسيق غير موجودة")
    result = _clean(job)
    result["artifacts"] = [
        _public_artifact(item) for item in list_artifacts(db, formatting_job_id)
    ]
    return result


@router.post("/jobs/{formatting_job_id}/cancel")
def cancel_formatting_job(
    formatting_job_id: str,
    db: Db,
    admin: Admin,
) -> dict[str, Any]:
    previous = get_job(db, formatting_job_id)
    if not previous:
        raise HTTPException(404, "مهمة التنسيق غير موجودة")
    if previous.get("status") == "cancelled":
        return _clean(previous)

    cancelled = cancel_job(db, formatting_job_id)
    if not cancelled:
        raise HTTPException(409, "لا يمكن إلغاء مهمة تنسيق مكتملة أو فاشلة")

    try:
        audit(
            db,
            action="cancel_formatting_job",
            actor=admin,
            details={"formatting_job_id": formatting_job_id},
        )
    except Exception:
        # Cancellation is already durable and must not be reported as failed
        # merely because the secondary audit write is unavailable.
        db.rollback()
    return _clean(cancelled)


@router.post("/jobs/{formatting_job_id}/rerun")
def rerun(
    formatting_job_id: str,
    db: Db,
    admin: Admin,
) -> dict[str, Any]:
    previous = get_job(db, formatting_job_id)
    if not previous:
        raise HTTPException(404, "مهمة التنسيق غير موجودة")
    return enqueue_formatting(
        CreateFormattingJob(
            source_job_id=str(previous["source_job_id"]),
            skill_id=str(previous["skill_id"]),
            model=str(previous["model_snapshot"]),
            reasoning=previous["reasoning_snapshot"],
        ),
        db,
        admin,
    )


@router.get("/artifacts/{artifact_id}/download")
def download_artifact(artifact_id: str, db: Db, _: Admin) -> FileResponse:
    artifact = get_artifact(db, artifact_id)
    if not artifact:
        raise HTTPException(404, "الملف غير موجود")
    config = get_formatting_config()
    try:
        path = persistent_artifact_path(
            config,
            str(artifact["formatting_job_id"]),
            Path(str(artifact["file_path"])),
        )
    except FormattingRuntimeError as exc:
        raise HTTPException(403, str(exc)) from exc
    if not path.is_file():
        raise HTTPException(404, "الملف غير موجود على التخزين")
    if path.lstat().st_size != int(artifact["size_bytes"]):
        raise HTTPException(409, "تغيّر حجم الملف الناتج بعد اكتمال المهمة")
    if sha256_file(path) != str(artifact["sha256"]):
        raise HTTPException(409, "تغيّرت بصمة الملف الناتج بعد اكتمال المهمة")
    return FileResponse(
        path,
        media_type=str(artifact["mime_type"]),
        filename=Path(str(artifact["file_name"])).name,
        headers={"Cache-Control": "no-store"},
    )
