from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]


def test_copied_verifier_discovers_namespaced_root_by_canonical_markers_textually() -> None:
    verifier = (ROOT / "scripts/verify_coolify_bundle.py").read_text(encoding="utf-8")
    tree_rules = (ROOT / "scripts/formatting_integration_tree.py").read_text(
        encoding="utf-8"
    )

    assert "ROOT = discover_project_root(SCRIPT_PATH)" in verifier
    assert "script_path.resolve().parents" in tree_rules
    assert '"docker-compose.yml"' in tree_rules
    assert '"backend/Dockerfile"' in tree_rules
    assert '"frontend/Dockerfile"' in tree_rules
    assert "if not candidates:" in tree_rules
    assert "if len(candidates) != 1:" in tree_rules
    assert "SCRIPT_PATH.parents[2]" not in verifier
    assert "tools/formatting-integration/." in verifier

    copied_script = PurePosixPath(
        "/merged/tools/formatting-integration/verify_coolify_bundle.py"
    )
    marker_roots = {PurePosixPath("/merged")}
    candidates = [parent for parent in copied_script.parents if parent in marker_roots]
    assert candidates == [PurePosixPath("/merged")]


def test_builder_hash_gate_message_compares_expected_and_actual_digest_textually() -> None:
    builder = (ROOT / "scripts/build_full_source_from_original.py").read_text(
        encoding="utf-8"
    )
    assert "actual_sha != KNOWN_BASE_SHA256 and not allow_different_base" in builder
    assert 'f"المتوقع: {KNOWN_BASE_SHA256}\\nالفعلي: {actual_sha}"' in builder
    assert 'open_stable_regular_file(\n        base_zip' in builder
    assert 'digest_open_file(\n            base_stream' in builder
    assert 'safe_extract(\n                base_stream' in builder
    assert '"source ZIP immediately before extraction"' in builder
    assert '"source ZIP after extraction"' in builder
    assert "after_extract != archive_sha256" in builder
    assert "not acknowledge_unverified_base" in builder
    assert "--allow-different-base" in builder
    assert "--acknowledge-unverified-base" in builder
    assert "_verified_zip_base=actual_sha == KNOWN_BASE_SHA256" in builder
    assert "acknowledge_unverified_base=actual_sha != KNOWN_BASE_SHA256" in builder


def test_builder_keeps_recovery_outside_project_through_verify_and_package_textually() -> None:
    builder = (ROOT / "scripts/build_full_source_from_original.py").read_text(
        encoding="utf-8"
    )
    external_backup = builder.index("backup_parent=recovery_parent")
    verifier = builder.index("verification_errors = verify(project)")
    package = builder.index("write_zip(project, quarantine_zip)")
    quarantine_hash = builder.index('"completed ZIP quarantine"', package)
    delete_backup = builder.index("shutil.rmtree(recovery_backups[0])")
    delete_work = builder.index("shutil.rmtree(work_root)")
    prepublish_hash = builder.index('"ZIP quarantine immediately before publication"')
    lock_check = builder.index("assert_output_lock(output_zip, output_lock)", prepublish_hash)
    no_clobber_publish = builder.index("publication_identity = publish_no_clobber(")
    final_hash = builder.index('"final published output"')
    assert external_backup < verifier < package < quarantine_hash < delete_backup
    assert delete_backup < delete_work < prepublish_hash < lock_check
    assert lock_check < no_clobber_publish < final_hash
    assert "final_sha256 != quarantine_sha256" in builder
    assert "output_sha = final_sha256" in builder
    assert 'f"SHA-256 للناتج: {output_sha}"' in builder
    assert "os.link(source, output_zip)" in builder
    assert "except FileExistsError as exc:" in builder
    assert "write_zip(project, output_zip)" not in builder
    assert 'if output_kind != "missing":' in builder
    assert "اختر مسارًا جديدًا" in builder
    assert "backup_existing_output(" not in builder
    assert "restore_existing_output_no_clobber(" not in builder
    assert "os.replace(quarantine_zip, output_zip)" not in builder
    assert "except BaseException as exc:" in builder
    assert "isinstance(exc, (KeyboardInterrupt, SystemExit))" in builder
    assert "--overwrite-output" not in builder
    assert "overwrite_output" not in builder
    assert "base_zip عن output_zip" in builder
    assert "ignore_errors=True" not in builder


def test_builder_output_lock_identity_and_guarded_recovery_are_static_contracts() -> None:
    builder = (ROOT / "scripts/build_full_source_from_original.py").read_text(
        encoding="utf-8"
    )

    acquire = builder.index("output_lock = acquire_output_lock(output_zip)")
    locked_build = builder.index("return _build_locked(", acquire)
    release = builder.index("release_output_lock(output_zip, output_lock)", locked_build)
    assert acquire < locked_build < release
    assert 'lock_path.open("xb")' in builder
    assert "لن يُحذف تلقائيًا" in builder
    assert "st_dev" in builder
    assert "st_ino" in builder
    assert "st_size" in builder
    assert "st_mtime_ns" in builder
    assert "details.st_nlink != 1" in builder
    assert "os.fstat(stream.fileno())" in builder
    assert "expected=quarantine_identity" in builder
    assert "expected=publication_identity" in builder
    assert "current_identity == publication_identity" in builder
    assert "previous_output" not in builder


def test_builder_streams_verified_snapshot_without_archive_write_textually() -> None:
    builder = (ROOT / "scripts/build_full_source_from_original.py").read_text(
        encoding="utf-8"
    )

    snapshot = builder.index("source_snapshot: dict[")
    stable_open = builder.index("open_stable_regular_file(", snapshot)
    zip_info = builder.index("info = zipfile.ZipInfo(", stable_open)
    streamed_write = builder.index('archive.open(info, mode="w", force_zip64=True)')
    after_fstat = builder.index('"ZIP archive source after read"', streamed_write)
    digest_match = builder.index("streamed_digest.hexdigest() != expected_sha256")
    final_tree = builder.index('label="ZIP source tree after archive reads"')
    final_snapshot = builder.index('"ZIP source final snapshot recheck"')
    assert snapshot < stable_open < zip_info < streamed_write < after_fstat
    assert after_fstat < digest_match < final_tree < final_snapshot
    assert "os.O_NOFOLLOW" in builder
    assert "archive.write(" not in builder
    assert "date_time=(1980, 1, 1, 0, 0, 0)" in builder
    assert "info.external_attr = (stat.S_IFREG | 0o644) << 16" in builder


def test_canonical_formatting_requirement_duplicates_match_exactly() -> None:
    canonical = (ROOT / "backend/requirements.txt").read_text(encoding="utf-8")
    formatting = (ROOT / "backend/requirements-formatting.txt").read_text(
        encoding="utf-8"
    )
    expected_duplicates = {
        "PyYAML>=6.0,<7",
        "requests>=2.32,<3",
        "python-multipart>=0.0.20,<1",
        "python-docx>=1.1,<2",
    }

    assert set(formatting.splitlines()) == expected_duplicates
    assert expected_duplicates.issubset(set(canonical.splitlines()))


def test_dependency_overlap_requires_exact_text_equivalence_textually() -> None:
    apply_script = (ROOT / "scripts/apply_formatting_integration.py").read_text(
        encoding="utf-8"
    )

    normalize = apply_script.index('re.sub(r"[-_.]+", "-", match.group(1)).casefold()')
    exact_duplicate = apply_script.index("elif previous != equivalent_text:")
    conflict = apply_script.index("تعارض اعتماديات للحزمة")
    manual_merge = apply_script.index("أنشئ قيدًا موحدًا")
    assert normalize < exact_duplicate < conflict
    assert manual_merge < conflict
    assert "معاملة تثبيت ثانية" in apply_script


def test_tree_boundary_preflight_rejects_links_reparse_and_special_objects_textually() -> None:
    tree_rules = (ROOT / "scripts/formatting_integration_tree.py").read_text(
        encoding="utf-8"
    )
    apply_script = (ROOT / "scripts/apply_formatting_integration.py").read_text(
        encoding="utf-8"
    )
    builder = (ROOT / "scripts/build_full_source_from_original.py").read_text(
        encoding="utf-8"
    )
    verifier = (ROOT / "scripts/verify_coolify_bundle.py").read_text(
        encoding="utf-8"
    )

    assert ".lstat()" in tree_rules
    assert "st_file_attributes" in tree_rules
    assert "FILE_ATTRIBUTE_REPARSE_POINT" in tree_rules
    assert "stat.S_ISLNK" in tree_rules
    assert "stat.S_ISREG" in tree_rules
    assert "stat.S_ISDIR" in tree_rules
    assert "details.st_nlink != 1" in tree_rules
    assert "hard-linked regular file" in tree_rules
    assert "special filesystem object" in tree_rules
    assert "resolved_path.relative_to(resolved_root)" in tree_rules
    assert "os.scandir(directory)" in tree_rules
    assert "validate_regular_tree(source_root" in apply_script
    assert "validate_regular_tree(project" in apply_script
    assert 'label="project commit target"' in apply_script
    assert 'label="copy source"' in apply_script
    assert 'label="copy target"' in apply_script
    assert "validate_zip_member_type(info)" in builder
    assert "file_type not in {0, allowed_type}" in builder
    assert "validate_regular_tree(destination" in builder
    assert "validate_regular_tree(project" in builder
    assert "source_overlays = legacy_overlay_paths(source_root)" in apply_script
    assert "overlays = legacy_overlay_paths(destination)" in builder
    assert 'validate_regular_tree(root, label="release tree")' in verifier
    assert "special filesystem object" in verifier


def test_direct_apply_identity_is_fail_closed_and_structural_override_is_explicit_textually() -> None:
    apply_script = (ROOT / "scripts/apply_formatting_integration.py").read_text(
        encoding="utf-8"
    )

    refusal = apply_script.index("رُفض التطبيق المباشر افتراضيًا")
    identity_check = apply_script.index("expected_baseline_tree_sha256 = tree_sha256(project)")
    commit = apply_script.index("            commit_staged_files(", identity_check)
    assert identity_check < commit
    assert refusal < commit
    assert "--expected-tree-sha256" in apply_script
    assert "--acknowledge-unverified-base" in apply_script
    assert "الفحص التمهيدي بنيوي فقط" in apply_script
    assert "تم إثبات خط الأساس من ZIP ذي البصمة المرجعية الدقيقة" in apply_script


def test_backup_inventory_and_atomic_restore_are_present_textually() -> None:
    apply_script = (ROOT / "scripts/apply_formatting_integration.py").read_text(
        encoding="utf-8"
    )

    metadata = apply_script.index('"created_files": [path.as_posix() for path in created]')
    first_backup = apply_script.index("# Finish every backup before replacing the first target file.")
    first_attempt = apply_script.index("attempted.append(relative)", first_backup)
    attempted_metadata = apply_script.index('metadata["attempted_destinations"]', first_attempt)
    first_replace = apply_script.index("_atomic_copy(", attempted_metadata)
    restore = apply_script.index('temporary_tag=f"restore-{backup_root.name}"')
    restoration_guard = apply_script.index("if restoration_errors:")
    delete_backup = apply_script.index("shutil.rmtree(backup_root)")
    assert metadata < first_backup < first_attempt < attempted_metadata < first_replace
    assert restore < restoration_guard < delete_backup
    assert '"commit_completed": False' in apply_script
    assert '"created_directories"' in apply_script
    assert 'metadata["commit_completed"] = True' in apply_script
    assert "os.replace(temporary, target)" in apply_script


def test_project_lock_final_identity_and_owned_rollback_are_static_contracts() -> None:
    apply_script = (ROOT / "scripts/apply_formatting_integration.py").read_text(
        encoding="utf-8"
    )

    acquire = apply_script.index("project_lock = acquire_project_lock(project)")
    final_tree = apply_script.index(
        "tree_sha256(project) != expected_baseline_tree_sha256", acquire
    )
    final_targets = apply_script.index("for relative in planned:", final_tree)
    commit = apply_script.index("            commit_staged_files(", final_targets)
    release = apply_script.index("release_project_lock(project, project_lock)", commit)
    assert acquire < final_tree < final_targets < commit < release
    assert "os.O_CREAT | os.O_EXCL" in apply_script
    assert "لن يُحذف تلقائيًا" in apply_script
    assert '"attempted_destinations": []' in apply_script
    assert "ownership_registry=committed_ownership" in apply_script
    assert "current_snapshot != owned_snapshot" in apply_script
    assert "created_directory_ownership" in apply_script
    assert "rollback directory ownership" in apply_script
    assert "atomic copy destination immediately before replacement" in apply_script
    assert "expected_destination=expected_targets[relative]" in apply_script
    assert "تغير الهدف إلى هوية غير مملوكة" in apply_script
    assert "_assert_target_snapshot(" in apply_script
    assert "expected_tree_sha256=expected_baseline_tree_sha256" in apply_script
