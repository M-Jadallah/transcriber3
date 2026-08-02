from __future__ import annotations

from pathlib import Path


API = (
    Path(__file__).resolve().parents[1]
    / "backend"
    / "app"
    / "api"
    / "formatting.py"
)


def test_cancellation_audit_failure_does_not_reverse_durable_cancellation() -> None:
    source = API.read_text(encoding="utf-8")
    cancellation = source[
        source.index("def cancel_formatting_job(") : source.index(
            '@router.post("/jobs/{formatting_job_id}/rerun")'
        )
    ]

    assert "cancelled = cancel_job(db, formatting_job_id)" in cancellation
    assert "try:\n        audit(" in cancellation
    assert "except Exception:" in cancellation
    assert "db.rollback()" in cancellation
    assert "return _clean(cancelled)" in cancellation


def test_transcript_snapshot_is_contained_bounded_and_stream_hashed() -> None:
    root = Path(__file__).resolve().parents[1]
    api = API.read_text(encoding="utf-8")
    config = (root / "backend/app/formatting/config.py").read_text(encoding="utf-8")
    runtime = (root / "backend/app/formatting/runtime.py").read_text(encoding="utf-8")

    assert 'os.getenv("EXPORTS_ROOT", "/data/exports")' in config
    assert "FORMATTING_INPUT_MAX_BYTES" in config
    assert "def require_safe_export_file(" in runtime
    assert "resolved.relative_to(config.exports_root)" in runtime
    assert "source_stat.st_nlink != 1" in runtime
    assert "source_stat.st_size > config.input_max_bytes" in runtime
    assert "sha256_file(\n            transcript_path," in api
    assert "max_bytes=config.input_max_bytes" in api
    assert ".read_bytes()" not in api
    assert "require_file_hash(" in api
    assert "snapshot_path.lstat().st_size != transcript_stat.st_size" in api
    assert "shutil.rmtree(config.jobs_root" not in api


def test_new_jobs_have_cumulative_persistent_storage_admission() -> None:
    root = Path(__file__).resolve().parents[1]
    api = API.read_text(encoding="utf-8")
    config = (root / "backend/app/formatting/config.py").read_text(encoding="utf-8")
    runtime = (root / "backend/app/formatting/runtime.py").read_text(encoding="utf-8")

    assert "FORMATTING_STORAGE_MAX_BYTES" in config
    assert "20 * 1024 * 1024 * 1024" in config
    assert "def ensure_formatting_storage_capacity(" in runtime
    assert "config.input_max_bytes" in runtime
    assert "config.output_max_total_bytes" in runtime
    assert "config.execution_log_max_bytes" in runtime
    assert "with os.scandir(directory) as iterator:" in runtime
    assert "total_bytes > available_before_reservation" in runtime
    assert "formatting:storage" in api
    assert "WHERE status IN ('queued', 'running')" in api
    assert "existing_reservations=active_reservations" in api
    assert api.index("ensure_formatting_storage_capacity(") < api.index(
        "snapshot_path = stage_input_snapshot("
    )
    assert "raise HTTPException(507, str(exc))" in api
    assert "raise HTTPException(422, str(exc))" in api


def test_skill_and_job_admission_share_both_persistent_roots() -> None:
    root = Path(__file__).resolve().parents[1]
    api = API.read_text(encoding="utf-8")
    runtime = (root / "backend/app/formatting/runtime.py").read_text(encoding="utf-8")

    assert "storage_roots = (config.skills_root, config.jobs_root)" in runtime
    assert "for storage_root in storage_roots:" in runtime
    assert "directories = [storage_root]" in runtime
    assert "entry_stat.st_nlink == 1" in runtime
    assert "additional_reservation_bytes" in runtime
    upload = api[api.index("async def upload_skill(") : api.index(
        '@router.post("/skills/{skill_id}/enable")'
    )]
    assert "formatting:storage" in upload
    assert "existing_reservations=active_reservations" in upload
    assert "len(blob) + config.skill_max_unpacked_bytes" in upload
    assert "raise HTTPException(507, str(exc))" in upload
    assert upload.index("ensure_formatting_storage_capacity(") < upload.index(
        "installed = install_skill_archive("
    )


def test_repository_latest_queries_have_deterministic_tie_breakers() -> None:
    root = Path(__file__).resolve().parents[1]
    repository = (root / "backend/app/formatting/repository.py").read_text(
        encoding="utf-8"
    )

    assert "ORDER BY source_job_id, attempt_number DESC, created_at DESC, id DESC" in repository
    assert "ORDER BY created_at DESC, attempt_number DESC, id DESC LIMIT :limit" in repository
    assert "ORDER BY attempt_number DESC, created_at DESC, id DESC LIMIT 1" in repository


def test_artifact_download_requires_generation_specific_safe_path() -> None:
    root = Path(__file__).resolve().parents[1]
    api = API.read_text(encoding="utf-8")
    runtime = (root / "backend/app/formatting/runtime.py").read_text(encoding="utf-8")

    assert "def persistent_artifact_path(" in runtime
    assert 'parts[1] != "executions"' in runtime
    assert 'parts[3] != "output"' in runtime
    assert "validate_execution_key(job_id, parts[2])" in runtime
    assert "persistent_artifact_path(" in api
