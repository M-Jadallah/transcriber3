from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_cancellation_db_throttle_is_not_layered() -> None:
    tasks = (ROOT / "backend/app/formatting/tasks.py").read_text(encoding="utf-8")
    runtime = (ROOT / "backend/app/formatting/runtime.py").read_text(encoding="utf-8")

    assert "status_seconds: float = 2.0" in tasks
    assert "next_cancellation_check" not in runtime
    assert "cancellation_callback is not None and cancellation_callback()" in runtime
    assert "deadline = time.monotonic() + config.task_timeout_seconds" in runtime
    assert "_output_quota_error(config, workspace / \"output\")" in runtime
    assert "_execution_workspace_quota_error(config, workspace)" in runtime


def test_whole_workspace_quota_and_persistent_parent_guards_are_wired() -> None:
    config = (ROOT / "backend/app/formatting/config.py").read_text(encoding="utf-8")
    runtime = (ROOT / "backend/app/formatting/runtime.py").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "FORMATTING_EXECUTION_WORKSPACE_MAX_ENTRIES" in config
    assert "FORMATTING_EXECUTION_WORKSPACE_MAX_BYTES" in config
    assert compose.count("FORMATTING_EXECUTION_WORKSPACE_MAX_ENTRIES:") == 2
    assert compose.count("FORMATTING_EXECUTION_WORKSPACE_MAX_BYTES:") == 2
    assert "def _execution_workspace_quota_error(" in runtime
    assert "config.execution_workspace_max_entries" in runtime
    assert "config.execution_workspace_max_bytes" in runtime
    assert "تحتوي مساحة التنفيذ رابطًا" in runtime
    assert "تحتوي مساحة التنفيذ عنصرًا خاصًا" in runtime
    assert "def _require_safe_components(" in runtime
    assert "current.lstat()" in runtime
    assert "resolved.relative_to(root_resolved)" in runtime
    assert "مجلد تنفيذات المهمة" in runtime
    assert "مجلد جيل التنفيذ الدائم" in runtime
    assert "مجلد النتيجة الدائم" in runtime
    assert "مجلد سجلات التنفيذ" in runtime


def test_artifact_collection_has_no_uncontained_workspace_fallback() -> None:
    runtime = (ROOT / "backend/app/formatting/runtime.py").read_text(encoding="utf-8")
    repository = (ROOT / "backend/app/formatting/repository.py").read_text(
        encoding="utf-8"
    )

    assert "def _require_artifact_workspace(" in runtime
    assert "مساحة جمع المخرجات ليست مساحة الجيل المطلوبة" in runtime
    assert "stored_workspace = Path(workspace.name)" not in runtime
    assert "def replace_artifacts(" not in repository


def test_worker_materializes_only_the_verified_skill_archive() -> None:
    tasks = (ROOT / "backend/app/formatting/tasks.py").read_text(encoding="utf-8")
    runtime = (ROOT / "backend/app/formatting/runtime.py").read_text(encoding="utf-8")
    skills = (ROOT / "backend/app/formatting/skills.py").read_text(encoding="utf-8")

    assert "def materialize_verified_skill(" in skills
    assert "_read_verified_archive(" in skills
    assert "_validate_archive_contents(archive, config)" in skills
    assert "expected_name != expected_slug" in skills
    materializer = skills[skills.index("def materialize_verified_skill(") :]
    assert "archive_path != expected_archive" in materializer
    assert "extracted_path" not in materializer
    assert "cache_valid = False" in skills
    assert "os.replace(temp_root, version_root)" in skills
    assert "SkillArchiveCancelled" in runtime
    assert "cancellation_callback=cancellation_callback" in runtime
    assert "destination=skill_target" in runtime
    assert "shutil.copytree(skill_path" not in runtime
    assert 'str(skill["name"]) != str(job["skill_name_snapshot"])' in tasks
    assert 'str(skill["slug"]) != str(job["skill_name_snapshot"])' in tasks


def test_live_scans_are_incremental_bounded_and_cancellable() -> None:
    runtime = (ROOT / "backend/app/formatting/runtime.py").read_text(encoding="utf-8")
    skills = (ROOT / "backend/app/formatting/skills.py").read_text(encoding="utf-8")

    assert "list(iterator)" not in runtime
    assert "sorted(iterator" not in runtime
    assert "list(iterator)" not in skills
    assert "entries = sorted(iterator" not in skills
    assert "if entry_count > config.output_max_files" in runtime
    assert "if total_bytes > config.output_max_total_bytes" in runtime
    assert "sorted(\n        output_files, key=lambda item: item[2]" in runtime
    assert runtime.count("_check_cancellation(cancellation_callback)") >= 8
    assert "cancellation_callback: Callable[[], bool] | None = None" in skills


def test_generation_paths_and_baseline_quota_are_explicit() -> None:
    runtime = (ROOT / "backend/app/formatting/runtime.py").read_text(encoding="utf-8")

    assert "def validate_execution_key(" in runtime
    assert "validate_execution_key(persistent_job_id, execution_key)" in runtime
    assert "persistent_job_id: str,\n    execution_key: str," in runtime
    assert "baseline_quota_error = _execution_workspace_quota_error" in runtime
    assert "entry_stat.st_nlink != 1" in runtime
    assert "عنصرًا خاصًا غير مسموح أثناء التنفيذ" in runtime


def test_parent_link_guards_cover_job_generation_output_and_logs() -> None:
    runtime = (ROOT / "backend/app/formatting/runtime.py").read_text(encoding="utf-8")
    focused_tests = (ROOT / "tests/test_runtime_workspace.py").read_text(encoding="utf-8")

    assert "current_stat = current.lstat()" in runtime
    assert "resolved.relative_to(root_resolved)" in runtime
    assert "_remove_path(config.jobs_root, staging" in runtime
    assert "_remove_path(config.execution_root, workspace" in runtime
    assert 'workspace / "logs"' in runtime
    assert 'leaf_kind="file",\n            label="ملف سجل التنفيذ"' in runtime
    assert "test_input_snapshot_rejects_symlinked_job_parent" in focused_tests
    assert "test_input_snapshot_rejects_symlinked_export_parent" in focused_tests
    assert "test_output_copy_rejects_symlinked_executions_parent" in focused_tests


def test_best_effort_task_failures_are_warned_without_reraise() -> None:
    source = (ROOT / "backend/app/formatting/tasks.py").read_text(encoding="utf-8")

    assert "Best-effort formatting execution log copy failed" in source
    assert "Best-effort formatting execution cleanup failed" in source
    assert source.count("exc_info=True") >= 2


def test_success_contract_is_mandatory_before_completion() -> None:
    runtime = (ROOT / "backend/app/formatting/runtime.py").read_text(encoding="utf-8")
    tasks = (ROOT / "backend/app/formatting/tasks.py").read_text(encoding="utf-8")

    assert "def _validate_success_output_contract(" in runtime
    assert 'by_name.get("result.md")' in runtime
    assert 'by_name.get("manifest.json")' in runtime
    assert 'manifest.get("status") not in {"completed", "success"}' in runtime
    assert 'manifest.get("primary_output") != "result.md"' in runtime
    assert "set(normalized_outputs) != actual_outputs" in runtime
    assert "object_pairs_hook=_manifest_object" in runtime
    assert 'suffix in {".md", ".txt", ".html", ".json"}' in runtime
    assert 'codecs.getincrementaldecoder("utf-8")(errors="strict")' in runtime
    assert "0x7F <= ord(character) <= 0x9F" in runtime
    assert tasks.index("validated_artifacts = collect_artifacts(") < tasks.index(
        "persistent_workspace = copy_validated_outputs("
    )
    assert tasks.index("\n            artifacts = collect_artifacts(") < tasks.index(
        "if not complete_job("
    )


def test_interrupted_generation_publication_has_static_reconciliation() -> None:
    runtime = (ROOT / "backend/app/formatting/runtime.py").read_text(encoding="utf-8")
    tasks = (ROOT / "backend/app/formatting/tasks.py").read_text(encoding="utf-8")

    assert "def _publication_directory_snapshot(" in runtime
    assert "def reconcile_generation_publications(" in runtime
    assert "def reconcile_persistent_job_publications(" in runtime
    assert 'f".{publication_kind}.copying"' in runtime
    assert 'f".{publication_kind}.previous"' in runtime
    assert 'for publication_kind in ("output", "logs")' in runtime
    assert "if backup_state == \"valid\"" in runtime
    assert "elif staging_state == \"valid\"" in runtime
    assert "recovered_snapshot != source_snapshot" in runtime
    assert "target_snapshot != staging_snapshot" in runtime
    assert "دون حذف النسخة الوحيدة المحتملة" in runtime
    assert 'target_state == "missing"' in runtime
    assert 'backup_state == "missing"' in runtime
    assert 'staging_state == "invalid"' in runtime
    assert '_remove_path(config.jobs_root, backup, "مجلد النسخة السابقة")' in runtime
    worker_reconcile = tasks.index("reconcile_persistent_job_publications(")
    assert worker_reconcile < tasks.index('skill = get_skill(db, str(job["skill_id"]))')


def test_opencode_inputs_have_a_persisted_and_rechecked_immutable_manifest() -> None:
    runtime = (ROOT / "backend/app/formatting/runtime.py").read_text(encoding="utf-8")
    tasks = (ROOT / "backend/app/formatting/tasks.py").read_text(encoding="utf-8")

    assert 'EXECUTION_INPUT_MANIFEST = "execution-input-manifest.json"' in runtime
    assert "def _immutable_execution_snapshot(" in runtime
    assert '"input/transcript.txt"' in runtime
    assert '"input/source-title.json"' in runtime
    assert 'records["opencode.json"]' in runtime
    assert '"selected_skill": {"slug": skill_slug, "files": skill_files}' in runtime
    assert "path.removeprefix(prefix)" in runtime
    assert "expected_root_entries = {" in runtime
    assert "عنصر مباشر غير متوقع أو غير آمن" in runtime
    assert "path_stat.st_nlink != 1" in runtime
    assert "_protect_execution_inputs(workspace, input_snapshot, manifest_record[0])" in runtime
    assert 'os.chmod(path, 0o444, follow_symlinks=False)' in runtime
    assert 'os.chmod(path, 0o555, follow_symlinks=False)' in runtime
    assert runtime.count("_verify_execution_inputs(") >= 3
    assert runtime.index("_verify_execution_inputs(\n        config") < runtime.index(
        'result_md = workspace / "output" / "result.md"'
    )
    assert "FormattingInputMutationError" in runtime
    assert 'status="failed"' in tasks
    assert "execution_generation," in tasks


def test_exchange_janitor_is_db_aware_bounded_and_exchange_only() -> None:
    runtime = (ROOT / "backend/app/formatting/runtime.py").read_text(encoding="utf-8")
    repository = (ROOT / "backend/app/formatting/repository.py").read_text(
        encoding="utf-8"
    )
    dispatcher = (ROOT / "backend/app/formatting/outbox_dispatcher.py").read_text(
        encoding="utf-8"
    )
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "def active_running_execution_keys(" in repository
    assert "WHERE status = 'running'" in repository
    assert "lease_expires_at > NOW() -" in repository
    assert "execution_generation > 0" in repository
    assert "def cleanup_orphan_execution_workspaces(" in runtime
    assert "active_execution_keys" in runtime
    assert "path_stat.st_mtime > cutoff" in runtime
    assert "scanned_entries > max(1, max_entries)" in runtime
    assert "_split_execution_key(entry.name)" in runtime
    assert "رابطًا أو عنصرًا خاصًا" in runtime
    assert "def cleanup_exchange_once(" in dispatcher
    assert "FORMATTING_EXCHANGE_JANITOR_GRACE_SECONDS" in dispatcher
    assert "unsafe or unverified workspaces were retained" in dispatcher
    dispatcher_compose = compose[
        compose.index("  formatting-dispatcher:") : compose.index("  gateway:")
    ]
    assert dispatcher_compose.count("FORMATTING_EXECUTION_ROOT:") == 1
    assert dispatcher_compose.count(
        "formatting-execution-exchange:/data/formatting-execution"
    ) == 1
    assert "OPENCODE_SERVER_PASSWORD" not in dispatcher_compose
    assert "formatting-data:/data/formatting" not in dispatcher_compose
    assert "formatting-jobs-data:/data/formatting/jobs" not in dispatcher_compose


def test_failed_task_cleanup_is_left_recoverable_for_janitor() -> None:
    runtime = (ROOT / "backend/app/formatting/runtime.py").read_text(encoding="utf-8")
    tasks = (ROOT / "backend/app/formatting/tasks.py").read_text(encoding="utf-8")

    assert "_make_safe_tree_removable(" in runtime
    assert "dispatcher exchange janitor may recover it" in tasks
    assert "exc_info=True" in tasks
