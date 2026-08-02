from __future__ import annotations

import logging
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.models import Job
from app.formatting.config import get_formatting_config
from app.formatting.repository import (
    claim_job,
    complete_job,
    get_job,
    get_skill,
    heartbeat_job,
    update_owned_job,
)
from app.formatting.runtime import (
    FormattingExecutionCancelled,
    clean_execution_workspace,
    collect_artifacts,
    copy_execution_logs,
    copy_validated_outputs,
    persistent_input_path,
    prepare_workspace,
    read_persistent_result_preview,
    reconcile_generation_publications,
    reconcile_persistent_job_publications,
    require_file_hash,
    run_opencode,
    validate_formatting_job_id,
)

try:
    from app.celery_app import celery_app
except ImportError:  # pragma: no cover
    from app.celery_app import app as celery_app  # type: ignore


_SECRET_PATTERNS = [
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"(?i)(refresh[_ -]?token\s*[:=]\s*)[^\s,;]+"),
]
logger = logging.getLogger(__name__)


def _safe_error(exc: Exception) -> str:
    value = str(exc).strip()[:4000] or "فشل غير معروف في عامل التنسيق"
    for pattern in _SECRET_PATTERNS:
        value = pattern.sub(
            lambda match: (match.group(1) if match.lastindex else "") + "[REDACTED]",
            value,
        )
    return value


def _source_title(db, source_job_id: str) -> str:
    job = db.execute(select(Job).where(Job.id == source_job_id)).scalar_one_or_none()
    if job is None:
        return source_job_id
    return job.title or job.id


class FormattingJobCancelled(RuntimeError):
    pass


def _is_owned(current: dict | None, execution_generation: int) -> bool:
    if not current or current.get("status") != "running":
        return False
    if int(current.get("execution_generation") or 0) != execution_generation:
        return False
    lease_expires_at = current.get("lease_expires_at")
    try:
        return bool(lease_expires_at and lease_expires_at > datetime.now(UTC))
    except TypeError:
        return False


def _require_running(control: "_ExecutionControl") -> None:
    if control(force=True):
        raise FormattingJobCancelled()


class _ExecutionControl:
    def __init__(
        self,
        formatting_job_id: str,
        execution_generation: int,
        *,
        lease_seconds: int,
        heartbeat_seconds: int,
        status_seconds: float = 2.0,
    ) -> None:
        self.formatting_job_id = formatting_job_id
        self.execution_generation = execution_generation
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = heartbeat_seconds
        now = time.monotonic()
        self.next_status_check = now
        self.next_heartbeat = now + heartbeat_seconds
        self.status_seconds = status_seconds

    def __call__(self, force: bool = False) -> bool:
        now = time.monotonic()
        if not force and now < self.next_status_check:
            return False
        self.next_status_check = now + self.status_seconds
        with SessionLocal() as control_db:
            if force or now >= self.next_heartbeat:
                self.next_heartbeat = now + self.heartbeat_seconds
                return not heartbeat_job(
                    control_db,
                    self.formatting_job_id,
                    execution_generation=self.execution_generation,
                    lease_seconds=self.lease_seconds,
                )
            return not _is_owned(
                get_job(control_db, self.formatting_job_id),
                self.execution_generation,
            )


@celery_app.task(
    name="app.formatting.run_job",
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
)
def run_formatting_job(self, formatting_job_id: str) -> None:
    config = get_formatting_config()
    validate_formatting_job_id(formatting_job_id)
    task_id = str(self.request.id)
    lease_seconds = max(300, int(os.getenv("FORMATTING_LEASE_SECONDS", "900")))
    heartbeat_seconds = max(
        10,
        min(
            int(os.getenv("FORMATTING_HEARTBEAT_SECONDS", "30")),
            lease_seconds // 3,
        ),
    )
    execution_workspace: Path | None = None
    with SessionLocal() as db:
        job = claim_job(
            db,
            formatting_job_id,
            celery_task_id=task_id,
            worker_name=os.getenv("WORKER_NAME", "formatting-worker"),
            lease_seconds=lease_seconds,
        )
        if not job:
            return

        execution_generation = int(job["execution_generation"])
        execution_key = f"{formatting_job_id}-g{execution_generation}"
        control = _ExecutionControl(
            formatting_job_id,
            execution_generation,
            lease_seconds=lease_seconds,
            heartbeat_seconds=heartbeat_seconds,
        )

        try:
            _require_running(control)
            reconcile_persistent_job_publications(
                config,
                formatting_job_id,
                control,
            )
            _require_running(control)
            skill = get_skill(db, str(job["skill_id"]))
            if not skill:
                raise RuntimeError("إصدار المهارة المحدد غير موجود")
            if str(skill["sha256"]) != str(job["skill_sha256_snapshot"]):
                raise RuntimeError("بصمة إصدار المهارة لا تطابق Snapshot المهمة")
            # The schema stores only the skill's display name and content hash as
            # snapshots (there is no ``skill_slug_snapshot`` column). Comparing the
            # slug against the name snapshot would always fail for skills whose
            # slug differs from its display name, so we only validate the name.
            if str(skill["name"]) != str(job["skill_name_snapshot"]):
                raise RuntimeError("اسم إصدار المهارة لا يطابق Snapshot المهمة")
            _require_running(control)

            input_path = persistent_input_path(config, formatting_job_id)
            _require_running(control)
            require_file_hash(
                input_path,
                str(job["input_hash"]),
                "نسخة النص الأصلية الخاصة بالمهمة",
                max_bytes=config.input_max_bytes,
                cancellation_callback=control,
            )
            _require_running(control)

            if not update_owned_job(
                db, formatting_job_id, execution_generation, progress=15
            ):
                raise FormattingJobCancelled()
            _require_running(control)
            execution_workspace = prepare_workspace(
                config,
                formatting_job_id,
                execution_key,
                Path(str(skill["archive_path"])),
                str(job["skill_sha256_snapshot"]),
                str(job["skill_name_snapshot"]),
                str(skill["slug"]),
                str(job["input_hash"]),
                control,
            )
            _require_running(control)
            if not update_owned_job(
                db, formatting_job_id, execution_generation, progress=25
            ):
                raise FormattingJobCancelled()

            _require_running(control)
            source_title = _source_title(db, str(job["source_job_id"]))
            _require_running(control)
            run_opencode(
                config,
                execution_workspace,
                str(job["model_snapshot"]),
                str(job["reasoning_snapshot"]),
                str(skill["slug"]),
                source_title,
                control,
            )
            _require_running(control)
            if not update_owned_job(
                db, formatting_job_id, execution_generation, progress=90
            ):
                raise FormattingJobCancelled()

            _require_running(control)
            validated_artifacts = collect_artifacts(
                config,
                execution_workspace,
                formatting_job_id,
                execution_key,
                control,
            )
            _require_running(control)
            persistent_workspace = copy_validated_outputs(
                config,
                formatting_job_id,
                execution_key,
                execution_workspace,
                validated_artifacts,
                control,
            )
            _require_running(control)
            try:
                copy_execution_logs(
                    config,
                    formatting_job_id,
                    execution_key,
                    execution_workspace,
                    control,
                )
            except Exception:
                logger.warning(
                    "Best-effort formatting execution log copy failed for job %s generation %s",
                    formatting_job_id,
                    execution_generation,
                    exc_info=True,
                )
            _require_running(control)
            reconcile_generation_publications(
                config,
                formatting_job_id,
                execution_key,
                control,
            )
            _require_running(control)
            artifacts = collect_artifacts(
                config,
                persistent_workspace,
                formatting_job_id,
                execution_key,
                control,
            )
            _require_running(control)
            preview = read_persistent_result_preview(
                config,
                persistent_workspace,
                formatting_job_id,
                execution_key,
            )
            _require_running(control)
            if not complete_job(
                db,
                formatting_job_id,
                execution_generation,
                artifacts,
                preview,
            ):
                raise FormattingJobCancelled()
        except (FormattingJobCancelled, FormattingExecutionCancelled):
            db.rollback()
            return
        except Exception as exc:
            db.rollback()
            current = get_job(db, formatting_job_id)
            if current and current.get("status") == "cancelled":
                return
            safe_message = _safe_error(exc)
            failed = update_owned_job(
                db,
                formatting_job_id,
                execution_generation,
                status="failed",
                progress=100,
                completed_at=datetime.now(UTC),
                error_code=exc.__class__.__name__,
                error_message=safe_message,
            )
            if failed:
                raise
            return
        finally:
            try:
                clean_execution_workspace(config, formatting_job_id, execution_key)
            except Exception:
                logger.warning(
                    "Best-effort formatting execution cleanup failed for job %s "
                    "generation %s; the dispatcher exchange janitor may recover it",
                    formatting_job_id,
                    execution_generation,
                    exc_info=True,
                )
