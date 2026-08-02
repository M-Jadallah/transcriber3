from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

FORMAT_JOB_TASK = "app.formatting.run_job"


class ActiveFormattingJobError(RuntimeError):
    def __init__(self, job_id: str) -> None:
        super().__init__(job_id)
        self.job_id = job_id


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid.uuid4())


def _insert_outbox(db: Session, formatting_job_id: str) -> str:
    outbox_id = new_id()
    db.execute(
        text(
            """
            INSERT INTO formatting_outbox
              (id, formatting_job_id, task_name, payload, status, attempts,
               available_at, created_at, updated_at)
            VALUES
              (:id, :job_id, :task_name, CAST(:payload AS jsonb), 'pending', 0,
               NOW(), NOW(), NOW())
            """
        ),
        {
            "id": outbox_id,
            "job_id": formatting_job_id,
            "task_name": FORMAT_JOB_TASK,
            "payload": json.dumps(
                {
                    "args": [formatting_job_id],
                    "kwargs": {},
                    "queue": "formatting",
                }
            ),
        },
    )
    return outbox_id


def _dict(row: Any) -> dict[str, Any] | None:
    return None if row is None else dict(row._mapping)


def get_settings(db: Session) -> dict[str, Any]:
    row = db.execute(text("SELECT * FROM formatting_settings WHERE id = 1")).first()
    if row is None:
        db.execute(
            text(
                "INSERT INTO formatting_settings (id) VALUES (1) "
                "ON CONFLICT (id) DO NOTHING"
            )
        )
        db.commit()
        row = db.execute(text("SELECT * FROM formatting_settings WHERE id = 1")).first()
    return _dict(row) or {}


def update_settings(
    db: Session,
    *,
    enabled: bool,
    default_model: str,
    default_reasoning: str,
    default_skill_id: str | None,
) -> dict[str, Any]:
    db.execute(
        text(
            """
            INSERT INTO formatting_settings
              (id, enabled, default_model, default_reasoning, default_skill_id, updated_at)
            VALUES
              (1, :enabled, :model, :reasoning, :skill, NOW())
            ON CONFLICT (id) DO UPDATE SET
              enabled = EXCLUDED.enabled,
              default_model = EXCLUDED.default_model,
              default_reasoning = EXCLUDED.default_reasoning,
              default_skill_id = EXCLUDED.default_skill_id,
              updated_at = NOW()
            """
        ),
        {
            "enabled": enabled,
            "model": default_model,
            "reasoning": default_reasoning,
            "skill": default_skill_id,
        },
    )
    db.commit()
    return get_settings(db)


def list_skills(db: Session, include_disabled: bool = False) -> list[dict[str, Any]]:
    clause = "" if include_disabled else "WHERE is_enabled = TRUE"
    rows = db.execute(
        text(f"SELECT * FROM formatting_skills {clause} ORDER BY created_at DESC, id DESC")
    ).all()
    return [dict(row._mapping) for row in rows]


def get_skill(db: Session, skill_id: str) -> dict[str, Any] | None:
    return _dict(
        db.execute(
            text("SELECT * FROM formatting_skills WHERE id = :id"),
            {"id": skill_id},
        ).first()
    )


def get_skill_by_sha(db: Session, sha256: str) -> dict[str, Any] | None:
    return _dict(
        db.execute(
            text("SELECT * FROM formatting_skills WHERE sha256 = :sha"),
            {"sha": sha256},
        ).first()
    )


def insert_skill(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    skill_id = new_id()
    db.execute(
        text(
            """
            INSERT INTO formatting_skills
              (id, name, slug, description, sha256, archive_path, extracted_path,
               metadata_json, is_enabled, created_at)
            VALUES
              (:id, :name, :slug, :description, :sha256, :archive_path,
               :extracted_path, CAST(:metadata AS jsonb), TRUE, NOW())
            """
        ),
        {
            "id": skill_id,
            "name": payload["name"],
            "slug": payload["slug"],
            "description": payload.get("description", ""),
            "sha256": payload["sha256"],
            "archive_path": payload["archive_path"],
            "extracted_path": payload["extracted_path"],
            "metadata": json.dumps(payload.get("metadata", {}), ensure_ascii=False),
        },
    )
    db.commit()
    return get_skill(db, skill_id) or {}


def set_skill_enabled(db: Session, skill_id: str, enabled: bool) -> None:
    db.execute(
        text("UPDATE formatting_skills SET is_enabled = :enabled WHERE id = :id"),
        {"id": skill_id, "enabled": enabled},
    )
    if not enabled:
        db.execute(
            text(
                "UPDATE formatting_settings SET default_skill_id = NULL, updated_at = NOW() "
                "WHERE id = 1 AND default_skill_id = :id"
            ),
            {"id": skill_id},
        )
    db.commit()


def disable_skill_with_replacement(db: Session, skill_id: str) -> str | None:
    settings = db.execute(
        text("SELECT * FROM formatting_settings WHERE id = 1 FOR UPDATE")
    ).first()
    current_default = (
        str(settings._mapping.get("default_skill_id") or "") if settings else ""
    )
    replacement_id: str | None = None
    if current_default == skill_id:
        replacement = db.execute(
            text(
                "SELECT id FROM formatting_skills "
                "WHERE is_enabled = TRUE AND id <> :id "
                "ORDER BY created_at DESC, id DESC LIMIT 1"
            ),
            {"id": skill_id},
        ).first()
        replacement_id = str(replacement._mapping["id"]) if replacement else None
        db.execute(
            text(
                "UPDATE formatting_settings SET default_skill_id = :replacement, "
                "updated_at = NOW() WHERE id = 1 AND default_skill_id = :id"
            ),
            {"id": skill_id, "replacement": replacement_id},
        )
    db.execute(
        text("UPDATE formatting_skills SET is_enabled = FALSE WHERE id = :id"),
        {"id": skill_id},
    )
    db.commit()
    return replacement_id


def create_job(
    db: Session,
    *,
    job_id: str | None = None,
    source_job_id: str,
    skill: dict[str, Any],
    model: str,
    reasoning: str,
    input_hash: str,
    requested_by: str,
) -> dict[str, Any]:
    job_id = job_id or new_id()
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext('formatting:auth'))"))
    # Serialize attempt-number allocation per source transcript. This prevents
    # two rapid clicks from producing the same attempt number.
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:source))"),
        {"source": source_job_id},
    )
    active = db.execute(
        text(
            "SELECT id FROM formatting_jobs WHERE source_job_id = :source "
            "AND status IN ('queued', 'running') "
            "ORDER BY attempt_number DESC, created_at DESC, id DESC LIMIT 1"
        ),
        {"source": source_job_id},
    ).first()
    if active is not None:
        active_id = str(active._mapping["id"])
        db.rollback()
        raise ActiveFormattingJobError(active_id)
    attempt = db.execute(
        text(
            "SELECT COALESCE(MAX(attempt_number), 0) + 1 "
            "FROM formatting_jobs WHERE source_job_id = :source"
        ),
        {"source": source_job_id},
    ).scalar_one()
    db.execute(
        text(
            """
            INSERT INTO formatting_jobs
              (id, source_job_id, skill_id, skill_name_snapshot,
               skill_sha256_snapshot, model_snapshot, reasoning_snapshot,
               input_hash, status, progress, attempt_number, requested_by,
               created_at, updated_at)
            VALUES
              (:id, :source, :skill_id, :skill_name, :skill_sha, :model,
               :reasoning, :input_hash, 'queued', 0, :attempt, :requested_by,
               NOW(), NOW())
            """
        ),
        {
            "id": job_id,
            "source": source_job_id,
            "skill_id": skill["id"],
            "skill_name": skill["name"],
            "skill_sha": skill["sha256"],
            "model": model,
            "reasoning": reasoning,
            "input_hash": input_hash,
            "attempt": attempt,
            "requested_by": requested_by,
        },
    )
    _insert_outbox(db, job_id)
    db.commit()
    return get_job(db, job_id) or {}


def get_job(db: Session, job_id: str) -> dict[str, Any] | None:
    return _dict(
        db.execute(
            text("SELECT * FROM formatting_jobs WHERE id = :id"),
            {"id": job_id},
        ).first()
    )


def list_jobs(
    db: Session,
    source_job_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    if source_job_id:
        rows = db.execute(
            text(
                "SELECT * FROM formatting_jobs WHERE source_job_id = :source "
                "ORDER BY created_at DESC, attempt_number DESC, id DESC LIMIT :limit"
            ),
            {"source": source_job_id, "limit": limit},
        ).all()
    else:
        rows = db.execute(
            text(
                "SELECT * FROM formatting_jobs "
                "ORDER BY created_at DESC, attempt_number DESC, id DESC LIMIT :limit"
            ),
            {"limit": limit},
        ).all()
    return [dict(row._mapping) for row in rows]


def latest_for_sources(
    db: Session,
    source_ids: list[str],
) -> dict[str, dict[str, Any]]:
    if not source_ids:
        return {}
    statement = text(
        """
        SELECT DISTINCT ON (source_job_id) *
        FROM formatting_jobs
        WHERE source_job_id IN :ids
        ORDER BY source_job_id, attempt_number DESC, created_at DESC, id DESC
        """
    ).bindparams(bindparam("ids", expanding=True))
    rows = db.execute(statement, {"ids": source_ids}).all()
    return {
        str(row._mapping["source_job_id"]): dict(row._mapping)
        for row in rows
    }


def update_job(
    db: Session,
    job_id: str,
    *,
    execution_generation: int,
    **values: Any,
) -> bool:
    allowed = {
        "status",
        "progress",
        "celery_task_id",
        "worker_name",
        "error_code",
        "error_message",
        "started_at",
        "completed_at",
        "output_preview",
    }
    fields = {key: value for key, value in values.items() if key in allowed}
    if not fields:
        return False
    if fields.get("status") in {"completed", "failed", "cancelled"}:
        fields["lease_expires_at"] = None
    fields["updated_at"] = utcnow()
    assignments = ", ".join(f"{key} = :{key}" for key in fields)
    fields.update({"id": job_id, "generation": execution_generation})
    result = db.execute(
        text(
            f"UPDATE formatting_jobs SET {assignments} WHERE id = :id "
            "AND status = 'running' AND execution_generation = :generation "
            "AND lease_expires_at > NOW()"
        ),
        fields,
    )
    db.commit()
    return bool(result.rowcount)


def claim_job(
    db: Session,
    job_id: str,
    *,
    celery_task_id: str,
    worker_name: str,
    lease_seconds: int = 900,
) -> dict[str, Any] | None:
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext('formatting:auth'))"))
    row = db.execute(
        text(
            """
            UPDATE formatting_jobs SET
              status = 'running', progress = 5, celery_task_id = :task_id,
              execution_generation = execution_generation + 1,
              worker_name = :worker, started_at = NOW(), completed_at = NULL,
              lease_expires_at = NOW() + CAST(:lease_seconds AS integer) * INTERVAL '1 second',
              heartbeat_at = NOW(), error_code = NULL, error_message = NULL,
              updated_at = NOW()
            WHERE id = :id AND (
              status = 'queued'
              OR (status = 'running' AND lease_expires_at <= NOW())
            )
            RETURNING *
            """
        ),
        {
            "id": job_id,
            "task_id": celery_task_id,
            "worker": worker_name,
            "lease_seconds": max(300, lease_seconds),
        },
    ).first()
    db.commit()
    return _dict(row)


def heartbeat_job(
    db: Session,
    job_id: str,
    *,
    execution_generation: int,
    lease_seconds: int = 900,
) -> bool:
    result = db.execute(
        text(
            """
            UPDATE formatting_jobs SET
              heartbeat_at = NOW(),
              lease_expires_at = NOW() + CAST(:lease_seconds AS integer) * INTERVAL '1 second',
              updated_at = NOW()
            WHERE id = :id AND status = 'running'
              AND execution_generation = :generation
              AND lease_expires_at > NOW()
            """
        ),
        {
            "id": job_id,
            "generation": execution_generation,
            "lease_seconds": max(300, lease_seconds),
        },
    )
    db.commit()
    return bool(result.rowcount)


def update_owned_job(
    db: Session,
    job_id: str,
    execution_generation: int,
    **values: Any,
) -> bool:
    allowed = {
        "status",
        "progress",
        "error_code",
        "error_message",
        "completed_at",
        "output_preview",
    }
    fields = {key: value for key, value in values.items() if key in allowed}
    if not fields:
        return False
    if fields.get("status") in {"completed", "failed", "cancelled"}:
        fields["lease_expires_at"] = None
    fields["updated_at"] = utcnow()
    assignments = ", ".join(f"{key} = :{key}" for key in fields)
    fields.update({"id": job_id, "generation": execution_generation})
    result = db.execute(
        text(
            f"UPDATE formatting_jobs SET {assignments} WHERE id = :id "
            "AND status = 'running' AND execution_generation = :generation "
            "AND lease_expires_at > NOW()"
        ),
        fields,
    )
    db.commit()
    return bool(result.rowcount)


def cancel_job(db: Session, job_id: str) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            UPDATE formatting_jobs SET
              status = 'cancelled', completed_at = NOW(), updated_at = NOW(),
              lease_expires_at = NULL, heartbeat_at = NULL,
              error_code = NULL, error_message = NULL
            WHERE id = :id AND status IN ('queued', 'running')
            RETURNING *
            """
        ),
        {"id": job_id},
    ).first()
    if row is not None:
        db.execute(
            text(
                """
                UPDATE formatting_outbox SET
                  status = 'cancelled', locked_at = NULL, claim_token = NULL,
                  last_error = NULL,
                  updated_at = NOW()
                WHERE formatting_job_id = :id
                  AND status IN ('pending', 'processing')
                """
            ),
            {"id": job_id},
        )
    db.commit()
    return _dict(row)


def has_active_jobs(db: Session) -> bool:
    # Keep this transaction open through logout so enqueue/claim cannot race it.
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext('formatting:auth'))"))
    return bool(
        db.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM formatting_jobs "
                "WHERE status IN ('queued', 'running'))"
            )
        ).scalar_one()
    )


def active_running_execution_keys(
    db: Session,
    *,
    recent_lease_seconds: int = 300,
) -> set[str]:
    rows = db.execute(
        text(
            """
            SELECT id, execution_generation
            FROM formatting_jobs
            WHERE status = 'running'
              AND execution_generation > 0
              AND lease_expires_at IS NOT NULL
              AND lease_expires_at > NOW() -
                CAST(:recent_lease_seconds AS integer) * INTERVAL '1 second'
            """
        ),
        {"recent_lease_seconds": max(0, min(recent_lease_seconds, 86400))},
    ).all()
    return {
        f"{row._mapping['id']}-g{int(row._mapping['execution_generation'])}"
        for row in rows
    }


def recover_expired_jobs(db: Session, limit: int = 25) -> int:
    rows = db.execute(
        text(
            """
            WITH expired AS (
              SELECT id
              FROM formatting_jobs
              WHERE status = 'running' AND lease_expires_at <= NOW()
              ORDER BY lease_expires_at, attempt_number, id
              LIMIT :limit
              FOR UPDATE SKIP LOCKED
            )
            UPDATE formatting_jobs AS job SET
              status = 'queued', progress = 0, celery_task_id = NULL,
              worker_name = NULL, lease_expires_at = NULL, heartbeat_at = NULL,
              started_at = NULL, completed_at = NULL,
              error_code = NULL, error_message = NULL, updated_at = NOW()
            FROM expired
            WHERE job.id = expired.id AND job.status = 'running'
              AND job.lease_expires_at <= NOW()
            RETURNING job.id
            """
        ),
        {"limit": max(1, min(limit, 500))},
    ).all()
    for row in rows:
        job_id = str(row._mapping["id"])
        db.execute(
            text(
                """
                UPDATE formatting_outbox SET
                  status = 'cancelled', locked_at = NULL, claim_token = NULL,
                  updated_at = NOW()
                WHERE formatting_job_id = :id
                  AND status IN ('pending', 'processing')
                """
            ),
            {"id": job_id},
        )
        _insert_outbox(db, job_id)
    db.commit()
    return len(rows)


def reconcile_queued_jobs(
    db: Session,
    *,
    min_age_seconds: int = 300,
    limit: int = 25,
) -> int:
    rows = db.execute(
        text(
            """
            SELECT job.id
            FROM formatting_jobs AS job
            WHERE job.status = 'queued'
              AND job.updated_at <= NOW() -
                CAST(:min_age_seconds AS integer) * INTERVAL '1 second'
              AND NOT EXISTS (
                SELECT 1 FROM formatting_outbox AS event
                WHERE event.formatting_job_id = job.id
                  AND event.status IN ('pending', 'processing')
              )
            ORDER BY job.updated_at, job.created_at, job.attempt_number, job.id
            LIMIT :limit
            FOR UPDATE SKIP LOCKED
            """
        ),
        {
            "min_age_seconds": max(30, min_age_seconds),
            "limit": max(1, min(limit, 500)),
        },
    ).all()
    for row in rows:
        _insert_outbox(db, str(row._mapping["id"]))
    db.commit()
    return len(rows)


def claim_outbox(db: Session, stale_seconds: int = 120) -> dict[str, Any] | None:
    claim_token = new_id()
    row = db.execute(
        text(
            """
            WITH candidate AS (
              SELECT id
              FROM formatting_outbox
              WHERE
                (status = 'pending' AND available_at <= NOW())
                OR
                (status = 'processing' AND locked_at <=
                  NOW() - CAST(:stale_seconds AS integer) * INTERVAL '1 second')
              ORDER BY available_at, created_at, id
              LIMIT 1
              FOR UPDATE SKIP LOCKED
            )
            UPDATE formatting_outbox AS event SET
              status = 'processing', attempts = event.attempts + 1,
              locked_at = NOW(), claim_token = :claim_token,
              last_error = NULL, updated_at = NOW()
            FROM candidate
            WHERE event.id = candidate.id
            RETURNING event.*
            """
        ),
        {"stale_seconds": max(30, stale_seconds), "claim_token": claim_token},
    ).first()
    db.commit()
    return _dict(row)


def mark_outbox_published(db: Session, outbox_id: str, claim_token: str) -> bool:
    row = db.execute(
        text(
            """
            UPDATE formatting_outbox SET
              status = 'published', published_at = NOW(), locked_at = NULL,
              claim_token = NULL, last_error = NULL, updated_at = NOW()
            WHERE id = :id AND status = 'processing' AND claim_token = :claim_token
            RETURNING formatting_job_id
            """
        ),
        {"id": outbox_id, "claim_token": claim_token},
    ).first()
    if row is None:
        db.rollback()
        return False
    task_update = db.execute(
        text(
            """
            UPDATE formatting_jobs SET celery_task_id = :task_id, updated_at = NOW()
            WHERE id = :job_id AND (
              status = 'queued'
              OR (status = 'running' AND celery_task_id = :task_id)
            )
            """
        ),
        {
            "job_id": str(row._mapping["formatting_job_id"]),
            "task_id": outbox_id,
        },
    )
    db.commit()
    return bool(task_update.rowcount)


def cancel_invalid_outbox(
    db: Session,
    outbox_id: str,
    claim_token: str,
    *,
    error: str,
) -> bool:
    row = db.execute(
        text(
            """
            UPDATE formatting_outbox SET
              status = 'cancelled', locked_at = NULL, claim_token = NULL,
              last_error = :error, updated_at = NOW()
            WHERE id = :id AND status = 'processing' AND claim_token = :claim_token
            RETURNING formatting_job_id
            """
        ),
        {"id": outbox_id, "claim_token": claim_token, "error": error[:4000]},
    ).first()
    if row is None:
        db.rollback()
        return False
    db.execute(
        text(
            """
            UPDATE formatting_jobs SET
              status = 'cancelled', completed_at = NOW(), updated_at = NOW(),
              error_code = 'invalid_outbox_event', error_message = :error
            WHERE id = :job_id AND status = 'queued'
            """
        ),
        {
            "job_id": str(row._mapping["formatting_job_id"]),
            "error": error[:4000],
        },
    )
    db.commit()
    return True


def release_outbox(
    db: Session,
    outbox_id: str,
    claim_token: str,
    *,
    error: str,
    backoff_seconds: int,
) -> bool:
    result = db.execute(
        text(
            """
            UPDATE formatting_outbox SET
              status = 'pending', available_at = NOW() +
                CAST(:backoff_seconds AS integer) * INTERVAL '1 second',
              locked_at = NULL, claim_token = NULL, last_error = :error,
              updated_at = NOW()
            WHERE id = :id AND status = 'processing' AND claim_token = :claim_token
            """
        ),
        {
            "id": outbox_id,
            "claim_token": claim_token,
            "error": error[:4000],
            "backoff_seconds": max(1, backoff_seconds),
        },
    )
    db.commit()
    return bool(result.rowcount)


def complete_job(
    db: Session,
    job_id: str,
    execution_generation: int,
    artifacts: list[dict[str, Any]],
    preview: str,
) -> bool:
    locked = db.execute(
        text(
            "SELECT id FROM formatting_jobs "
            "WHERE id = :id AND status = 'running' "
            "AND execution_generation = :generation "
            "AND lease_expires_at > NOW() FOR UPDATE"
        ),
        {"id": job_id, "generation": execution_generation},
    ).first()
    if locked is None:
        db.rollback()
        return False

    db.execute(
        text("DELETE FROM formatting_artifacts WHERE formatting_job_id = :id"),
        {"id": job_id},
    )
    for item in artifacts:
        _insert_artifact(db, job_id, item)
    result = db.execute(
        text(
            "UPDATE formatting_jobs SET status = 'completed', progress = 100, "
            "completed_at = NOW(), updated_at = NOW(), output_preview = :preview, "
            "lease_expires_at = NULL "
            "WHERE id = :id AND status = 'running' "
            "AND execution_generation = :generation "
            "AND lease_expires_at > NOW()"
        ),
        {"id": job_id, "generation": execution_generation, "preview": preview},
    )
    if not result.rowcount:
        db.rollback()
        return False
    db.commit()
    return True


def _insert_artifact(db: Session, job_id: str, item: dict[str, Any]) -> None:
    db.execute(
        text(
            """
            INSERT INTO formatting_artifacts
              (id, formatting_job_id, format, file_name, file_path,
               mime_type, size_bytes, sha256, created_at)
            VALUES
              (:id, :job_id, :format, :name, :path, :mime, :size, :sha, NOW())
            """
        ),
        {
            "id": new_id(),
            "job_id": job_id,
            "format": item["format"],
            "name": item["file_name"],
            "path": item["file_path"],
            "mime": item["mime_type"],
            "size": item["size_bytes"],
            "sha": item["sha256"],
        },
    )


def list_artifacts(db: Session, job_id: str) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            "SELECT * FROM formatting_artifacts "
            "WHERE formatting_job_id = :id ORDER BY created_at, id"
        ),
        {"id": job_id},
    ).all()
    return [dict(row._mapping) for row in rows]


def get_artifact(db: Session, artifact_id: str) -> dict[str, Any] | None:
    return _dict(
        db.execute(
            text("SELECT * FROM formatting_artifacts WHERE id = :id"),
            {"id": artifact_id},
        ).first()
    )
