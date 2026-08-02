#!/usr/bin/env python3
"""Apply the optional formatting subsystem to the latest transcriber source tree.

The script is intentionally conservative:
- validates the expected project shape;
- detects the existing Alembic head before copying the new migration;
- backs up every replaced/patched file;
- stops on ambiguous Alembic history;
- leaves the Deepgram/YouTube task modules untouched.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

import yaml

if __package__:
    from scripts.formatting_integration_tree import (
        UnsafeTreeObjectError,
        discover_project_root,
        legacy_overlay_paths,
        validate_path_boundary,
        validate_regular_tree,
    )
else:  # Direct execution from scripts/ or copied tools/formatting-integration/.
    from formatting_integration_tree import (
        UnsafeTreeObjectError,
        discover_project_root,
        legacy_overlay_paths,
        validate_path_boundary,
        validate_regular_tree,
    )

SCRIPT_PATH = Path(__file__).resolve()
ROOT = discover_project_root(SCRIPT_PATH)
MIGRATION_NAME = "20260801_0100_add_formatting_subsystem.py"
MIGRATION_PATH = Path("backend/alembic/versions") / MIGRATION_NAME
FORMATTING_REVISION = "20260801_0100"
DOWN_REVISION_PLACEHOLDER = 'down_revision = "REPLACE_WITH_CURRENT_HEAD"'
BACKUP_METADATA_NAME = "integration-backup.json"
FileIdentity = tuple[int, int, int, int]
FileSnapshot = tuple[FileIdentity, str]
ProjectLock = tuple[Path, BinaryIO, FileIdentity]
DirectoryOwnership = tuple[int, int]

NEW_SOURCE_FILES = (
    Path(".dockerignore"),
    Path("backend/Dockerfile"),
    Path("backend/Dockerfile.formatting"),
    Path("backend/requirements-formatting.txt"),
    Path("backend/app/api/formatting.py"),
    Path("backend/app/formatting/__init__.py"),
    Path("backend/app/formatting/celery_bootstrap.py"),
    Path("backend/app/formatting/config.py"),
    Path("backend/app/formatting/opencode_client.py"),
    Path("backend/app/formatting/opencode_control.py"),
    Path("backend/app/formatting/repository.py"),
    Path("backend/app/formatting/outbox_dispatcher.py"),
    Path("backend/app/formatting/runtime.py"),
    Path("backend/app/formatting/skills.py"),
    Path("backend/app/formatting/tasks.py"),
    Path("frontend/src/components/FormatTranscriptButton.tsx"),
    Path("frontend/src/components/FormattingNavigationLink.tsx"),
    Path("frontend/src/components/FormattingSettingsPanel.tsx"),
    Path("frontend/Dockerfile"),
    Path("frontend/src/formatting.ts"),
    Path("frontend/src/pages/FormattingDetail.tsx"),
    Path("frontend/src/pages/Skills.tsx"),
    Path("frontend/src/pages/formatting.css"),
    Path(".env.formatting.example"),
)
DOCUMENTATION_FILES = {
    Path(".env.coolify.manual.example"): Path(".env.coolify.manual.example"),
    Path("COOLIFY_ENVIRONMENT_VARIABLES_AR.md"): Path(
        "COOLIFY_ENVIRONMENT_VARIABLES_AR.md"
    ),
    Path("UPLOAD_NOW_README_AR.md"): Path("UPLOAD_NOW_README_AR.md"),
    Path("docs/DEPLOYMENT_CHECKLIST_AR.md"): Path(
        "docs/formatting-integration/DEPLOYMENT_CHECKLIST_AR.md"
    ),
    Path("docs/FORMATTING_ARCHITECTURE_AR.md"): Path(
        "docs/formatting-integration/FORMATTING_ARCHITECTURE_AR.md"
    ),
    Path("docs/OPENCODE_CHATGPT_AND_SKILLS_AR.md"): Path(
        "docs/formatting-integration/OPENCODE_CHATGPT_AND_SKILLS_AR.md"
    ),
    Path("README_INTEGRATION_AR.md"): Path(
        "docs/formatting-integration/README_INTEGRATION_AR.md"
    ),
}
TOOLING_FILES = {
    Path("scripts/apply_formatting_integration.py"): Path(
        "tools/formatting-integration/apply_formatting_integration.py"
    ),
    Path("scripts/verify_coolify_bundle.py"): Path(
        "tools/formatting-integration/verify_coolify_bundle.py"
    ),
    Path("scripts/build_full_source_from_original.py"): Path(
        "tools/formatting-integration/build_full_source_from_original.py"
    ),
    Path("scripts/formatting_integration_tree.py"): Path(
        "tools/formatting-integration/formatting_integration_tree.py"
    ),
}
DOCUMENTATION_SCRIPT_REPLACEMENTS = {
    "scripts/apply_formatting_integration.py": (
        "tools/formatting-integration/apply_formatting_integration.py"
    ),
    "scripts/verify_coolify_bundle.py": (
        "tools/formatting-integration/verify_coolify_bundle.py"
    ),
    "scripts/build_full_source_from_original.py": (
        "tools/formatting-integration/build_full_source_from_original.py"
    ),
}
PATCH_FILES = (
    Path("backend/app/main.py"),
    Path("backend/requirements.txt"),
    Path("frontend/src/App.tsx"),
    Path("frontend/src/pages/Jobs.tsx"),
)
OPTIONAL_PATCH_FILES = (
    Path("frontend/src/pages/Settings.tsx"),
    Path("frontend/src/components/ProtectedLayout.tsx"),
    Path("frontend/src/components/Layout.tsx"),
)
ORIGINAL_BASELINE_FILES = (
    Path("backend/Dockerfile"),
    Path("backend/requirements.txt"),
    Path("backend/alembic.ini"),
    Path("backend/alembic/env.py"),
    Path("backend/alembic/script.py.mako"),
    Path("backend/app/main.py"),
    Path("backend/app/celery_app.py"),
    Path("backend/app/db_wait.py"),
    Path("backend/app/scheduler.py"),
    Path("backend/app/core/db.py"),
    Path("backend/app/core/models.py"),
    Path("backend/app/core/security.py"),
    Path("backend/app/services/export_service.py"),
    Path("backend/app/services/log_service.py"),
    Path("frontend/Dockerfile"),
    Path("frontend/package.json"),
    Path("frontend/src/App.tsx"),
    Path("frontend/src/api.ts"),
    Path("frontend/src/hooks/useFetch.ts"),
    Path("frontend/src/pages/Jobs.tsx"),
    Path("docker-compose.yml"),
)
ORIGINAL_BASELINE_DIRECTORIES = (
    Path("backend/alembic/versions"),
    Path("backend/app/core"),
    Path("frontend/src/hooks"),
    Path("frontend/src/pages"),
)
CANONICAL_COMPOSE_SERVICES = {
    "storage-init",
    "formatting-storage-init",
    "postgres",
    "redis",
    "migrate",
    "api",
    "worker-1",
    "worker-2",
    "worker-3",
    "worker-4",
    "worker-5",
    "scheduler",
    "opencode-runtime",
    "formatting-worker",
    "formatting-dispatcher",
    "gateway",
}


class IntegrationError(RuntimeError):
    pass


def _file_identity(details: os.stat_result) -> FileIdentity:
    return details.st_dev, details.st_ino, details.st_size, details.st_mtime_ns


def _checked_regular_identity(
    details: os.stat_result,
    path: Path,
    label: str,
) -> FileIdentity:
    if getattr(details, "st_file_attributes", 0) & getattr(
        stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400
    ):
        raise IntegrationError(f"Refusing reparse point for {label}: {path}")
    if stat.S_ISLNK(details.st_mode) or not stat.S_ISREG(details.st_mode):
        raise IntegrationError(f"Refusing link or special file for {label}: {path}")
    if details.st_nlink != 1:
        raise IntegrationError(f"Refusing hard-linked file for {label}: {path}")
    return _file_identity(details)


def _stable_file_snapshot(boundary: Path, path: Path, label: str) -> FileSnapshot:
    path, _ = validate_path_boundary(
        boundary,
        path,
        expected=frozenset({"file"}),
        label=label,
    )
    initial = _checked_regular_identity(path.lstat(), path, label)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = _checked_regular_identity(os.fstat(descriptor), path, label)
        if opened != initial:
            raise IntegrationError(f"Identity changed while opening {label}: {path}")
        digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        after = _checked_regular_identity(os.fstat(descriptor), path, label)
        current = _checked_regular_identity(path.lstat(), path, label)
        if after != initial or current != initial:
            raise IntegrationError(f"Identity changed while reading {label}: {path}")
        return initial, digest.hexdigest()
    finally:
        os.close(descriptor)


def _target_snapshot(project: Path, relative: Path) -> FileSnapshot | None:
    target = project / relative
    return _optional_file_snapshot(
        project,
        target,
        "integration target identity",
    )


def _optional_file_snapshot(
    boundary: Path,
    path: Path,
    label: str,
) -> FileSnapshot | None:
    _, kind = validate_path_boundary(
        boundary,
        path,
        expected=frozenset({"file"}),
        allow_missing=True,
        label=label,
    )
    if kind == "missing":
        return None
    return _stable_file_snapshot(boundary, path, label)


def _assert_target_snapshot(
    project: Path,
    relative: Path,
    expected: FileSnapshot | None,
    label: str,
) -> None:
    if _target_snapshot(project, relative) != expected:
        raise IntegrationError(
            f"تغير الهدف بالتزامن قبل {label}: {relative.as_posix()}؛ رُفض الدمج"
        )


def _same_file_bytes(left: FileSnapshot, right: FileSnapshot) -> bool:
    return left[0][2] == right[0][2] and left[1] == right[1]


def _directory_ownership(boundary: Path, path: Path, label: str) -> DirectoryOwnership:
    path, _ = validate_path_boundary(
        boundary,
        path,
        expected=frozenset({"directory"}),
        label=label,
    )
    details = path.lstat()
    if getattr(details, "st_file_attributes", 0) & getattr(
        stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400
    ) or stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode):
        raise IntegrationError(f"Refusing unsafe directory for {label}: {path}")
    return details.st_dev, details.st_ino


def acquire_project_lock(project: Path) -> ProjectLock:
    lock_path = project.parent / f".{project.name}.formatting-integration.lock"
    validate_path_boundary(
        project.parent,
        project.parent,
        expected=frozenset({"directory"}),
        label="project integration lock parent",
    )
    _, lock_kind = validate_path_boundary(
        project.parent,
        lock_path,
        expected=frozenset({"file"}),
        allow_missing=True,
        label="exclusive project integration lock",
    )
    if lock_kind != "missing":
        raise IntegrationError(
            f"قفل دمج حصري موجود ولن يُحذف تلقائيًا: {lock_path}. "
            "تحقق يدويًا من عدم وجود عملية دمج عاملة قبل إزالة القفل القديم."
        )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except FileExistsError as exc:
        raise IntegrationError(f"رُفض الدمج المتزامن؛ القفل موجود: {lock_path}") from exc
    stream = os.fdopen(descriptor, "wb")
    try:
        stream.write(f"pid={os.getpid()}\nproject={project}\n".encode("utf-8"))
        stream.flush()
        os.fsync(stream.fileno())
        identity = _checked_regular_identity(
            os.fstat(stream.fileno()), lock_path, "exclusive project integration lock"
        )
        current = _checked_regular_identity(
            lock_path.lstat(), lock_path, "exclusive project integration lock"
        )
        if current != identity:
            raise IntegrationError("تغير مسار قفل الدمج أثناء إنشائه")
        return lock_path, stream, identity
    except BaseException:
        try:
            opened = _checked_regular_identity(
                os.fstat(stream.fileno()), lock_path, "failed project integration lock"
            )
        except (OSError, IntegrationError):
            opened = None
        stream.close()
        try:
            current = _checked_regular_identity(
                lock_path.lstat(), lock_path, "failed project integration lock"
            )
            if opened is not None and current == opened:
                lock_path.unlink()
        except (OSError, IntegrationError):
            pass
        raise


def assert_project_lock(project: Path, project_lock: ProjectLock) -> None:
    lock_path, stream, expected = project_lock
    opened = _checked_regular_identity(
        os.fstat(stream.fileno()), lock_path, "exclusive project integration lock"
    )
    current = _checked_regular_identity(
        lock_path.lstat(), lock_path, "exclusive project integration lock"
    )
    if opened != expected or current != expected:
        raise IntegrationError("تغيرت هوية قفل الدمج؛ أُوقفت العملية")


def release_project_lock(project: Path, project_lock: ProjectLock) -> None:
    lock_path, stream, expected = project_lock
    assert_project_lock(project, project_lock)
    stream.close()
    current = _checked_regular_identity(
        lock_path.lstat(), lock_path, "project integration lock before release"
    )
    if current != expected:
        raise IntegrationError("تغير قفل الدمج قبل تحريره؛ لن يُحذف")
    lock_path.unlink()


def _safe_mkdir(boundary: Path, directory: Path) -> None:
    boundary, _ = validate_path_boundary(
        boundary,
        boundary,
        expected=frozenset({"directory"}),
        label="write boundary",
    )
    directory, kind = validate_path_boundary(
        boundary,
        directory,
        expected=frozenset({"directory"}),
        allow_missing=True,
        label="directory creation target",
    )
    if kind == "directory":
        return
    current = boundary
    for part in directory.relative_to(boundary).parts:
        current = current / part
        _, current_kind = validate_path_boundary(
            boundary,
            current,
            expected=frozenset({"directory"}),
            allow_missing=True,
            label="directory creation target",
        )
        if current_kind == "missing":
            current.mkdir()
            validate_path_boundary(
                boundary,
                current,
                expected=frozenset({"directory"}),
                label="created directory",
            )


def _safe_unlink_regular(boundary: Path, path: Path) -> None:
    path, kind = validate_path_boundary(
        boundary,
        path,
        expected=frozenset({"file"}),
        allow_missing=True,
        label="unlink target",
    )
    if kind == "file":
        path.unlink()


def _atomic_copy(
    source_boundary: Path,
    source: Path,
    target_boundary: Path,
    target: Path,
    *,
    temporary_tag: str,
    ownership_registry: dict[Path, FileSnapshot] | None = None,
    ownership_key: Path | None = None,
    enforce_destination_identity: bool = False,
    expected_destination: FileSnapshot | None = None,
) -> FileSnapshot:
    source, _ = validate_path_boundary(
        source_boundary,
        source,
        expected=frozenset({"file"}),
        label="copy source",
    )
    target, _ = validate_path_boundary(
        target_boundary,
        target,
        expected=frozenset({"file"}),
        allow_missing=True,
        label="copy target",
    )
    _safe_mkdir(target_boundary, target.parent)
    temporary = target.with_name(f".{target.name}.{temporary_tag}.tmp")
    _, temporary_kind = validate_path_boundary(
        target_boundary,
        temporary,
        expected=frozenset({"file"}),
        allow_missing=True,
        label="atomic copy temporary",
    )
    if temporary_kind != "missing":
        raise IntegrationError(f"ملف مؤقت موجود مسبقًا ولن يُستبدل: {temporary}")
    try:
        source_snapshot = _stable_file_snapshot(
            source_boundary,
            source,
            "atomic copy stable source",
        )
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(source, flags)
        try:
            source_identity = _checked_regular_identity(
                os.fstat(descriptor), source, "atomic copy stable source"
            )
            if source_identity != source_snapshot[0]:
                raise IntegrationError(f"تغير مصدر النسخ أثناء فتحه: {source}")
            copied_digest = hashlib.sha256()
            with temporary.open("xb") as output:
                while True:
                    chunk = os.read(descriptor, 1024 * 1024)
                    if not chunk:
                        break
                    copied_digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            opened_after = _checked_regular_identity(
                os.fstat(descriptor), source, "atomic copy stable source"
            )
            current_source = _checked_regular_identity(
                source.lstat(), source, "atomic copy stable source"
            )
            if opened_after != source_snapshot[0] or current_source != source_snapshot[0]:
                raise IntegrationError(f"تغير مصدر النسخ أثناء قراءته: {source}")
            if copied_digest.hexdigest() != source_snapshot[1]:
                raise IntegrationError(f"تغيرت Bytes مصدر النسخ أثناء قراءته: {source}")
            os.chmod(temporary, stat.S_IMODE(os.fstat(descriptor).st_mode))
        finally:
            os.close(descriptor)
        validate_path_boundary(
            target_boundary,
            temporary,
            expected=frozenset({"file"}),
            label="atomic copy temporary",
        )
        validate_path_boundary(
            target_boundary,
            target,
            expected=frozenset({"file"}),
            allow_missing=True,
            label="atomic copy destination",
        )
        replacement_snapshot = _stable_file_snapshot(
            target_boundary,
            temporary,
            "atomic copy replacement ownership",
        )
        if enforce_destination_identity:
            current_destination = _optional_file_snapshot(
                target_boundary,
                target,
                "atomic copy destination immediately before replacement",
            )
            if current_destination != expected_destination:
                raise IntegrationError(
                    f"تغير هدف النسخ فورًا قبل الاستبدال؛ رُفضت الكتابة: {target}"
                )
        if ownership_registry is not None:
            if ownership_key is None:
                raise IntegrationError("مفتاح ملكية الاستبدال مطلوب قبل الالتزام")
            ownership_registry[ownership_key] = replacement_snapshot
        os.replace(temporary, target)
        validate_path_boundary(
            target_boundary,
            target,
            expected=frozenset({"file"}),
            label="atomic copy result",
        )
        if _stable_file_snapshot(
            target_boundary,
            target,
            "atomic copy result ownership",
        ) != replacement_snapshot:
            raise IntegrationError(f"لا تطابق هوية/Bytes ناتج النسخ الذري: {target}")
        return replacement_snapshot
    finally:
        _safe_unlink_regular(target_boundary, temporary)


def read_text(boundary: Path, path: Path) -> str:
    path, _ = validate_path_boundary(
        boundary,
        path,
        expected=frozenset({"file"}),
        label="text source",
    )
    return path.read_text(encoding="utf-8")


def write_text(boundary: Path, path: Path, content: str) -> None:
    _safe_mkdir(boundary, path.parent)
    temporary = path.with_name(f".{path.name}.formatting-write.tmp")
    _, target_kind = validate_path_boundary(
        boundary,
        path,
        expected=frozenset({"file"}),
        allow_missing=True,
        label="text target",
    )
    _, temporary_kind = validate_path_boundary(
        boundary,
        temporary,
        expected=frozenset({"file"}),
        allow_missing=True,
        label="text temporary",
    )
    if temporary_kind != "missing":
        raise IntegrationError(f"ملف كتابة مؤقت موجود مسبقًا ولن يُستبدل: {temporary}")
    try:
        with temporary.open("x", encoding="utf-8", newline="") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        validate_path_boundary(
            boundary,
            temporary,
            expected=frozenset({"file"}),
            label="text temporary",
        )
        validate_path_boundary(
            boundary,
            path,
            expected=frozenset({"file"}),
            allow_missing=target_kind == "missing",
            label="text target",
        )
        os.replace(temporary, path)
    finally:
        _safe_unlink_regular(boundary, temporary)


def tree_sha256(project: Path) -> str:
    """Return a deterministic identity over regular paths, directories, and bytes."""
    digest = hashlib.sha256(b"formatting-integration-tree-v1\0")
    validate_regular_tree(project, label="baseline identity tree")
    entries: list[tuple[Path, str]] = [(project, "directory")]
    for path in sorted(project.rglob("*")):
        path, kind = validate_path_boundary(
            project,
            path,
            expected=frozenset({"file", "directory"}),
            label="baseline identity entry",
        )
        entries.append((path, kind))
    file_snapshots = {
        path.relative_to(project): _stable_file_snapshot(
            project, path, "baseline identity file"
        )
        for path, kind in entries
        if kind == "file"
    }
    for path, kind in entries:
        relative = Path(".") if path == project else path.relative_to(project)
        encoded = relative.as_posix().encode("utf-8")
        marker = b"D" if kind == "directory" else b"F"
        digest.update(marker + len(encoded).to_bytes(8, "big") + encoded)
        if kind == "directory":
            continue
        identity, file_sha256 = file_snapshots[path.relative_to(project)]
        digest.update(identity[2].to_bytes(16, "big") + bytes.fromhex(file_sha256))
    validate_regular_tree(project, label="baseline identity tree recheck")
    final_entries: list[tuple[Path, str]] = [(project, "directory")]
    for path in sorted(project.rglob("*")):
        path, kind = validate_path_boundary(
            project,
            path,
            expected=frozenset({"file", "directory"}),
            label="baseline identity final entry",
        )
        final_entries.append((path, kind))
    if [
        (Path(".") if path == project else path.relative_to(project), kind)
        for path, kind in final_entries
    ] != [
        (Path(".") if path == project else path.relative_to(project), kind)
        for path, kind in entries
    ]:
        raise IntegrationError("تغيرت عضوية شجرة خط الأساس أثناء حساب هويتها")
    for relative, expected in file_snapshots.items():
        if _stable_file_snapshot(
            project,
            project / relative,
            "baseline identity final file recheck",
        ) != expected:
            raise IntegrationError(
                f"تغير ملف أثناء حساب هوية شجرة خط الأساس: {relative.as_posix()}"
            )
    return digest.hexdigest()


def tooling_source_path(
    source_root: Path,
    source_relative: Path,
    target_relative: Path,
) -> Path:
    package_source = source_root / source_relative
    _, kind = validate_path_boundary(
        source_root,
        package_source,
        expected=frozenset({"file"}),
        allow_missing=True,
        label="tooling source",
    )
    return package_source if kind == "file" else source_root / target_relative


def render_merged_documentation(target_relative: Path, content: str) -> str:
    if target_relative == Path("UPLOAD_NOW_README_AR.md"):
        content = """# التحقق والرفع بعد الدمج

هذا الملف موجود داخل مشروع مدمج بالفعل. لا تعِد تشغيل Builder أو سكربت الدمج على
هذه الشجرة. افحص مسار `.formatting-integration-backup-*` الذي طبعه سكربت الدمج.
إذا فشلت الاستعادة، استخدمه أولًا لاسترداد الملفات ولا تكمل. وإذا نجح الدمج، أرشف
المجلد كاملًا خارج جذر المشروع وتأكد من إمكان قراءته، ثم احذف نسخته من الشجرة.
بعدها فقط شغّل Verifier المرفق، وأوقف العملية عند أي خطأ:

```bash
python scripts/verify_coolify_bundle.py .
```

بعد نجاحه ارفع المشروع كاملًا، واختر `docker-compose.yml` في Coolify، وأدخل القيم
اليدوية من `COOLIFY_ENVIRONMENT_VARIABLES_AR.md`، واربط الدومين بخدمة `gateway`
على المنفذ 80. تحقق من عدم وجود متغيرات `GATEWAY_PEER_IP` أو
`GATEWAY_NETWORK_SUBNET` أو `FORWARDED_ALLOW_IPS` قديمة في إعدادات Coolify.

لا ترفع متغيرات `.env` غير الأمثلة المقصودة، أو Cookies، أو بيانات اعتماد
Docker/SSH/Kubernetes/Cloud، أو مفاتيح وشهادات، أو قواعد بيانات وكاش وحالة محلية.
إذا ظهر `docker-compose.formatting.yml` عند أي عمق فأوقف النشر وانقله خارج المشروع
بعد مراجعة إعداداته؛ لا تستخدمه مع Compose الموحد. يرفض Verifier أي Backup أو
overlay محظور بهذا الاسم عند أي عمق، ولا يجوز رفعه.
"""
    elif target_relative == Path("docs/formatting-integration/README_INTEGRATION_AR.md"):
        start = content.find("## الدمج الآمن")
        end = content.find("## العزل التشغيلي", start)
        if start < 0 or end < 0:
            raise IntegrationError("تعذر تحويل README_INTEGRATION_AR.md إلى دليل ما بعد الدمج")
        content = content[:start] + """## التحقق بعد الدمج

هذه النسخة موجودة داخل المشروع المدمج. لا تعِد تشغيل Builder أو سكربت الدمج عليها.
افحص مسار `.formatting-integration-backup-*` المطبوع. عند فشل الاستعادة استرد الملفات
ولا تكمل. وبعد نجاح الدمج أرشف المجلد خارج جذر المشروع وتأكد من إمكان قراءته، ثم
احذف نسخته من الشجرة. بعدها فقط شغّل Verifier المرفق وأوقف العملية عند أي خطأ:

```bash
python scripts/verify_coolify_bundle.py .
```

يرفض Verifier أي `.formatting-integration-backup-*` أو
`docker-compose.formatting.yml` عند أي عمق. لا يحذف أي مسار آمن هذه الملفات بصمت.

""" + content[end:]
    elif target_relative == Path("docs/formatting-integration/DEPLOYMENT_CHECKLIST_AR.md"):
        start = content.find("## الدمج")
        end = content.find("## البناء", start)
        if start < 0 or end < 0:
            raise IntegrationError("تعذر تحويل DEPLOYMENT_CHECKLIST_AR.md إلى دليل ما بعد الدمج")
        content = content[:start] + """## التحقق الإلزامي بعد الدمج

لا تعِد تشغيل Builder أو سكربت الدمج على هذه الشجرة. افحص Backup المطبوع؛ استرد منه
عند أي فشل، أو أرشفه خارج المشروع وتأكد من إمكان قراءته ثم احذف نسخته من الشجرة
بعد نجاح الدمج. شغّل Verifier بعدها فقط، قبل الرفع أو Alembic أو Deploy:

```bash
python scripts/verify_coolify_bundle.py .
```

يجب ألا يوجد `.formatting-integration-backup-*` أو
`docker-compose.formatting.yml` عند أي عمق. Verifier يرفضهما ولا يستثني Backup.

""" + content[end:]
    elif target_relative == Path(
        "docs/formatting-integration/OPENCODE_CHATGPT_AND_SKILLS_AR.md"
    ):
        start = content.find("## 10. إنشاء ZIP مصدر كامل من الأرشيف الأصلي")
        end = content.find("\n---", start)
        if start < 0 or end < 0:
            raise IntegrationError("تعذر تحويل دليل OpenCode إلى دليل ما بعد الدمج")
        content = content[:start] + """## 10. التحقق من المشروع المدمج

هذه الشجرة مدمجة بالفعل؛ لا تعِد تشغيل Builder أو سكربت الدمج عليها. لا تشغّل
Verifier قبل أرشفة Backup المطبوع خارج جذر المشروع، والتأكد من إمكان قراءته، وحذف
نسخته من الشجرة بعد تأكيد نجاح الدمج. بعدها شغّله وأوقف العملية عند أي خطأ:

```bash
python scripts/verify_coolify_bundle.py .
```
""" + content[end:]

    for old_path, merged_path in DOCUMENTATION_SCRIPT_REPLACEMENTS.items():
        content = content.replace(old_path, merged_path)
    return content


def parse_revision_value(text_value: str, key: str) -> str | None:
    assignments = re.findall(
        rf"^\s*{re.escape(key)}\s*(?::[^=]+)?=",
        text_value,
        re.MULTILINE,
    )
    if len(assignments) != 1:
        return None
    pattern = (
        rf"^\s*{re.escape(key)}\s*(?::[^=]+)?=\s*"
        rf"(['\"])([^'\"]+)\1\s*(?:#.*)?$"
    )
    match = re.search(pattern, text_value, re.MULTILINE)
    return match.group(2) if match else None


def parse_revision_collection(text_value: str, key: str) -> set[str]:
    assignments = re.findall(
        rf"^\s*{re.escape(key)}\s*(?::[^=]+)?=",
        text_value,
        re.MULTILINE,
    )
    if len(assignments) != 1:
        raise ValueError(f"{key} must have exactly one assignment")

    single = parse_revision_value(text_value, key)
    if single:
        return {single}
    if re.search(
        rf"^\s*{re.escape(key)}\s*(?::[^=]+)?=\s*None\s*(?:#.*)?$",
        text_value,
        re.MULTILINE,
    ):
        return set()

    collection_match = re.search(
        rf"^\s*{re.escape(key)}\s*(?::[^=]+)?=\s*"
        r"(?:\[(.*?)\]|\((.*?)\))\s*(?:#.*)?$",
        text_value,
        re.MULTILINE | re.DOTALL,
    )
    if not collection_match:
        raise ValueError(f"missing or unsupported {key} assignment")
    body = next(group for group in collection_match.groups() if group is not None)
    revisions = re.findall(r"['\"]([^'\"]+)['\"]", body)
    residue = re.sub(r"['\"][^'\"]+['\"]", "", body)
    if (
        not revisions
        or len(revisions) != len(set(revisions))
        or residue.strip(" \t\r\n,")
    ):
        raise ValueError(f"invalid or ambiguous {key} collection")
    return set(revisions)


def parse_down_revisions(text_value: str) -> set[str]:
    return parse_revision_collection(text_value, "down_revision")


def parse_dependencies(text_value: str) -> set[str]:
    if not re.search(
        r"^\s*depends_on\s*(?::[^=]+)?=",
        text_value,
        re.MULTILINE,
    ):
        return set()
    return parse_revision_collection(text_value, "depends_on")


def _is_formatting_migration(text_value: str) -> bool:
    return all(
        marker in text_value
        for marker in (
            "Add the optional AI formatting subsystem",
            '"formatting_jobs"',
            '"formatting_outbox"',
        )
    )


def _assert_acyclic(parents: dict[str, set[str]]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(revision: str) -> None:
        if revision in visiting:
            raise IntegrationError(
                f"تم اكتشاف دورة في تاريخ Alembic عند Revision: {revision}"
            )
        if revision in visited:
            return
        visiting.add(revision)
        for parent in parents[revision]:
            visit(parent)
        visiting.remove(revision)
        visited.add(revision)

    for revision in parents:
        visit(revision)


def _depends_on(
    revision: str,
    ancestor: str,
    parents: dict[str, set[str]],
) -> bool:
    return ancestor in parents[revision] or any(
        _depends_on(parent, ancestor, parents) for parent in parents[revision]
    )


def current_alembic_head(project: Path) -> str:
    versions = project / "backend" / "alembic" / "versions"
    _, versions_kind = validate_path_boundary(
        project,
        versions,
        expected=frozenset({"directory"}),
        allow_missing=True,
        label="Alembic versions directory",
    )
    if versions_kind != "directory":
        raise IntegrationError("لم يتم العثور على backend/alembic/versions")

    revision_files: dict[str, list[Path]] = {}
    down_parents: dict[str, set[str]] = {}
    graph_parents: dict[str, set[str]] = {}
    contents: dict[str, str] = {}
    reserved_filename_revision: str | None = None
    for file in sorted(versions.glob("*.py")):
        if file.name == "__init__.py":
            continue
        text_value = read_text(project, file)
        revision = parse_revision_value(text_value, "revision")
        if not revision:
            raise IntegrationError(
                f"ملف ترحيل Alembic لا يعرّف revision صالحًا: {file.name}"
            )
        try:
            down_revisions = parse_down_revisions(text_value)
            dependencies = parse_dependencies(text_value)
        except ValueError as exc:
            raise IntegrationError(
                "تعذر تحليل down_revision أو depends_on في ملف Alembic: "
                f"{file.name}"
            ) from exc
        revision_files.setdefault(revision, []).append(file)
        down_parents[revision] = down_revisions
        graph_parents[revision] = down_revisions | dependencies
        contents[revision] = text_value
        if file.name == MIGRATION_NAME:
            reserved_filename_revision = revision

    duplicates = {
        revision: files
        for revision, files in revision_files.items()
        if len(files) > 1
    }
    if duplicates:
        details = ", ".join(
            f"{revision}: {[file.name for file in files]}"
            for revision, files in sorted(duplicates.items())
        )
        raise IntegrationError(f"توجد Alembic Revision IDs مكررة: {details}")

    if reserved_filename_revision not in {None, FORMATTING_REVISION}:
        raise IntegrationError(
            f"اسم ملف ترحيل التنسيق محجوز لكنه يعرّف Revision مختلفًا: "
            f"{reserved_filename_revision}"
        )

    revisions = set(graph_parents)
    referenced = set().union(*graph_parents.values()) if graph_parents else set()
    if FORMATTING_REVISION in revisions:
        formatting_text = contents[FORMATTING_REVISION]
        formatting_file = revision_files[FORMATTING_REVISION][0]
        if not _is_formatting_migration(formatting_text):
            raise IntegrationError(
                f"يوجد ترحيل آخر يستخدم Revision ID المحجوز "
                f"{FORMATTING_REVISION}: {formatting_file.name}"
            )
        if DOWN_REVISION_PLACEHOLDER in formatting_text:
            raise IntegrationError(
                "ترحيل التنسيق موجود في الهدف لكنه غير مربوط بتاريخ Alembic؛ "
                "أزله يدويًا بعد المراجعة ثم أعد الدمج."
            )
    dangling = sorted(referenced - revisions)
    if dangling:
        raise IntegrationError(
            f"تاريخ Alembic يحتوي down_revision أو depends_on معلّقًا: {dangling}"
        )
    _assert_acyclic(graph_parents)

    if FORMATTING_REVISION in revisions:
        descendants = sorted(
            revision
            for revision in graph_parents
            if revision != FORMATTING_REVISION
            and _depends_on(revision, FORMATTING_REVISION, graph_parents)
        )
        if descendants:
            raise IntegrationError(
                "يوجد ترحيل أحدث يعتمد على ترحيل التنسيق؛ لن يعاد الدمج: "
                f"{descendants}"
            )
        raise IntegrationError(
            "ترحيل التنسيق مدمج مسبقًا في الهدف؛ الدمج متوقف بصورة آمنة "
            "ولم تتم إعادة كتابة أي ملف."
        )

    down_referenced = (
        set().union(*down_parents.values()) if down_parents else set()
    )
    heads = sorted(revisions - down_referenced)
    if len(heads) != 1:
        raise IntegrationError(
            "تعذر تحديد رأس Alembic واحد بأمان. "
            f"الرؤوس المكتشفة: {heads or 'لا يوجد'}"
        )
    return heads[0]


def add_import(text_value: str, import_line: str) -> str:
    if import_line in text_value:
        return text_value
    export_index = text_value.find("export default")
    if export_index < 0:
        raise IntegrationError("تعذر العثور على export default في ملف React")
    return text_value[:export_index] + import_line + "\n" + text_value[export_index:]


def insert_into_react_root(text_value: str, jsx: str) -> str:
    if jsx.strip() in text_value:
        return text_value

    return_match = re.search(r"return\s*\(\s*", text_value)
    if not return_match:
        raise IntegrationError("تعذر العثور على return (...) في ملف React")

    tail = text_value[return_match.end():]
    if tail.startswith("<>"):
        closing = text_value.rfind("</>")
        if closing < return_match.end():
            raise IntegrationError("تعذر العثور على إغلاق React Fragment")
        return text_value[:closing] + f"\n      {jsx}\n    " + text_value[closing:]

    tag_match = re.match(r"<([A-Za-z][A-Za-z0-9_.:-]*)\b", tail)
    if not tag_match:
        raise IntegrationError("بنية جذر JSX غير مدعومة للدمج الآلي")
    tag = tag_match.group(1)
    closing_token = f"</{tag}>"
    closing = text_value.rfind(closing_token)
    if closing < return_match.end():
        raise IntegrationError(f"تعذر العثور على إغلاق الجذر {closing_token}")
    return text_value[:closing] + f"\n      {jsx}\n    " + text_value[closing:]


def patch_settings(project: Path, backup_root: Path) -> str:
    path = project / "frontend" / "src" / "pages" / "Settings.tsx"
    _, path_kind = validate_path_boundary(
        project,
        path,
        expected=frozenset({"file"}),
        allow_missing=True,
        label="optional Settings.tsx",
    )
    if path_kind != "file":
        return "لم يوجد Settings.tsx؛ أضف FormattingSettingsPanel يدويًا."
    original = read_text(project, path)
    try:
        patched = add_import(
            original,
            "import FormattingSettingsPanel from '../components/FormattingSettingsPanel';",
        )
        patched = insert_into_react_root(patched, "<FormattingSettingsPanel />")
    except IntegrationError as exc:
        return f"تعذر تعديل Settings.tsx آليًا: {exc}"
    # Preserve the exact pre-integration page before applying the JSX insertion.
    backup = backup_root / path.relative_to(project)
    write_text(project, backup, original)
    write_text(project, path, patched)
    return "تمت إضافة إعدادات التنسيق داخل Settings.tsx."


def patch_navigation(project: Path, backup_root: Path) -> str:
    candidates = [
        project / "frontend" / "src" / "components" / "ProtectedLayout.tsx",
        project / "frontend" / "src" / "components" / "Layout.tsx",
    ]
    path = next(
        (
            candidate
            for candidate in candidates
            if validate_path_boundary(
                project,
                candidate,
                expected=frozenset({"file"}),
                allow_missing=True,
                label="optional navigation component",
            )[1]
            == "file"
        ),
        None,
    )
    if path is None:
        return "لم يوجد ProtectedLayout.tsx أو Layout.tsx؛ أضف رابط /skills يدويًا."

    original = read_text(project, path)
    component = "<FormattingNavigationLink />"
    if component in original:
        return f"رابط المهارات موجود مسبقًا في {path.name}."
    try:
        patched = add_import(
            original,
            "import FormattingNavigationLink from './FormattingNavigationLink';",
        )
        nav_end = patched.find("</nav>")
        if nav_end < 0:
            raise IntegrationError("تعذر العثور على عنصر <nav>")
        patched = patched[:nav_end] + f"  {component}\n        " + patched[nav_end:]
    except IntegrationError as exc:
        return f"تعذر تعديل {path.name} آليًا: {exc}"

    backup = backup_root / path.relative_to(project)
    write_text(project, backup, original)
    write_text(project, path, patched)
    return f"تمت إضافة رابط مهارات التنسيق إلى {path.name}."


def _backup_and_write(project: Path, backup_root: Path, path: Path, content: str) -> None:
    original = read_text(project, path)
    if original == content:
        return
    backup = backup_root / path.relative_to(project)
    _, backup_kind = validate_path_boundary(
        project,
        backup,
        expected=frozenset({"file"}),
        allow_missing=True,
        label="staging patch backup",
    )
    if backup_kind == "missing":
        write_text(project, backup, original)
    write_text(project, path, content)


def _replace_once(text_value: str, old: str, new: str, label: str) -> str:
    if new in text_value:
        return text_value
    count = text_value.count(old)
    if count != 1:
        raise IntegrationError(
            f"تعذر تعديل {label} بأمان؛ العلامة المتوقعة ظهرت {count} مرة"
        )
    return text_value.replace(old, new, 1)


def patch_backend_requirements(project: Path, backup_root: Path) -> str:
    path = project / "backend" / "requirements.txt"
    _, path_kind = validate_path_boundary(
        project,
        path,
        expected=frozenset({"file"}),
        allow_missing=True,
        label="backend requirements",
    )
    if path_kind != "file":
        raise IntegrationError("لم يتم العثور على backend/requirements.txt")
    original = read_text(project, path)
    formatting_path = project / "backend" / "requirements-formatting.txt"
    _, formatting_kind = validate_path_boundary(
        project,
        formatting_path,
        expected=frozenset({"file"}),
        allow_missing=True,
        label="formatting requirements",
    )
    if formatting_kind != "file":
        raise IntegrationError("لم يتم العثور على backend/requirements-formatting.txt")

    def requirement_entry(line: str, source: str) -> tuple[str, str] | None:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            return None
        if stripped.startswith("-"):
            raise IntegrationError(
                f"تعذر فحص تداخل الاعتماديات في {source} بسبب توجيه غير مدعوم: "
                f"{stripped!r}. ادمج القيود يدويًا في backend/requirements.txt."
            )
        requirement = re.split(r"\s+#", stripped, maxsplit=1)[0].rstrip()
        match = re.fullmatch(
            r"([A-Za-z0-9][A-Za-z0-9._-]*)(\[[A-Za-z0-9._,-]+\])?(.*)",
            requirement,
        )
        if not match or (match.group(3) and match.group(3)[0] not in "<>=!~@; \t"):
            raise IntegrationError(
                f"تعذر تحليل اعتمادية نصيًا بأمان في {source}: {stripped!r}. "
                "ادمجها يدويًا في backend/requirements.txt."
            )
        package = re.sub(r"[-_.]+", "-", match.group(1)).casefold()
        equivalent_text = package + (match.group(2) or "") + match.group(3)
        return package, equivalent_text

    existing: dict[str, str] = {}
    for line in original.splitlines():
        entry = requirement_entry(line, "backend/requirements.txt")
        if entry is None:
            continue
        package, equivalent_text = entry
        previous = existing.get(package)
        if previous is not None and previous != equivalent_text:
            raise IntegrationError(
                f"توجد قيود متعددة متعارضة نصيًا للحزمة {package!r} في "
                "backend/requirements.txt. أنشئ قيدًا موحدًا يدويًا قبل الدمج."
            )
        existing[package] = equivalent_text

    formatting_requirements: list[tuple[str, str, str]] = []
    formatting_seen: dict[str, str] = {}
    for line in read_text(project, formatting_path).splitlines():
        entry = requirement_entry(line, "backend/requirements-formatting.txt")
        if entry is None:
            continue
        package, equivalent_text = entry
        previous = formatting_seen.get(package)
        if previous is not None and previous != equivalent_text:
            raise IntegrationError(
                f"توجد قيود Formatting متعارضة نصيًا للحزمة {package!r}. "
                "أنشئ قيدًا موحدًا يدويًا قبل الدمج."
            )
        formatting_seen[package] = equivalent_text
        formatting_requirements.append((line.strip(), package, equivalent_text))

    appended: list[str] = []
    seen = dict(existing)
    for requirement, package, equivalent_text in formatting_requirements:
        previous = seen.get(package)
        if previous is None:
            appended.append(requirement)
            seen[package] = equivalent_text
        elif previous != equivalent_text:
            raise IntegrationError(
                f"تعارض اعتماديات للحزمة {package!r}: يحتوي "
                f"backend/requirements.txt على {previous!r} بينما تتطلب ميزة "
                f"التنسيق {equivalent_text!r}. لن يتجاوز الدمج القيد الأصلي ولن "
                "يعتمد على معاملة تثبيت ثانية لاستبداله؛ أنشئ قيدًا موحدًا "
                "يدويًا في backend/requirements.txt ثم أعد الدمج."
            )
    if not appended:
        return "اعتماديات Formatting API موجودة مسبقًا في requirements.txt."
    content = original.rstrip() + "\n\n# Optional AI formatting API dependencies\n" + "\n".join(appended) + "\n"
    _backup_and_write(project, backup_root, path, content)
    return "تمت إضافة اعتماديات Formatting API الناقصة إلى requirements.txt."


def patch_backend_main(project: Path, backup_root: Path) -> str:
    path = project / "backend" / "app" / "main.py"
    text_value = read_text(project, path)
    import_line = "from app.api.formatting import router as formatting_router"
    include_line = "app.include_router(formatting_router)"

    if import_line not in text_value:
        anchors = [
            "from app.api.bulk_exports import router as bulk_exports_router\n",
            "from app.api.routes import router\n",
        ]
        anchor = next((value for value in anchors if value in text_value), None)
        if anchor is None:
            raise IntegrationError("تعذر تحديد موضع استيراد formatting_router في main.py")
        text_value = text_value.replace(anchor, anchor + import_line + "\n", 1)

    if include_line not in text_value:
        anchors = [
            "app.include_router(bulk_exports_router)\n",
            "app.include_router(router)\n",
        ]
        anchor = next((value for value in anchors if value in text_value), None)
        if anchor is None:
            raise IntegrationError("تعذر تحديد موضع تسجيل formatting_router في main.py")
        text_value = text_value.replace(anchor, anchor + include_line + "\n", 1)

    _backup_and_write(project, backup_root, path, text_value)
    return "تم ربط Formatting API داخل main.py دون استبدال الملف."


def patch_app_routes(project: Path, backup_root: Path) -> str:
    path = project / "frontend" / "src" / "App.tsx"
    text_value = read_text(project, path)

    if "import FormattingDetail from './pages/FormattingDetail';" not in text_value:
        text_value = _replace_once(
            text_value,
            "import JobDetail from './pages/JobDetail';",
            "import FormattingDetail from './pages/FormattingDetail';\nimport JobDetail from './pages/JobDetail';",
            "App.tsx imports",
        )
    if "import Skills from './pages/Skills';" not in text_value:
        text_value = _replace_once(
            text_value,
            "import Workers from './pages/Workers';",
            "import Skills from './pages/Skills';\nimport Workers from './pages/Workers';",
            "App.tsx skill import",
        )
    if 'path="formatting/:id"' not in text_value:
        text_value = _replace_once(
            text_value,
            '        <Route path="jobs/:id" element={<JobDetail />} />',
            '        <Route path="jobs/:id" element={<JobDetail />} />\n'
            '        <Route path="formatting/:id" element={<FormattingDetail />} />\n'
            '        <Route path="skills" element={<Skills />} />',
            "App.tsx routes",
        )

    _backup_and_write(project, backup_root, path, text_value)
    return "تمت إضافة مسارات التنسيق والمهارات إلى App.tsx دون استبداله."


def patch_jobs_page(project: Path, backup_root: Path) -> str:
    path = project / "frontend" / "src" / "pages" / "Jobs.tsx"
    text_value = read_text(project, path)
    if "<FormatTranscriptButton" in text_value and "getLatestFormatting" in text_value:
        return "صفحة Jobs.tsx تحتوي تكامل التنسيق مسبقًا."

    text_value = _replace_once(
        text_value,
        "import StatusBadge from '../components/StatusBadge';",
        "import FormatTranscriptButton from '../components/FormatTranscriptButton';\n"
        "import StatusBadge from '../components/StatusBadge';\n"
        "import { getLatestFormatting, type FormattingJob } from '../formatting';",
        "Jobs.tsx imports",
    )
    text_value = _replace_once(
        text_value,
        "import './Jobs.bulk-download.css';",
        "import './Jobs.bulk-download.css';\nimport './formatting.css';",
        "Jobs.tsx styles",
    )
    text_value = _replace_once(
        text_value,
        "  const [message, setMessage] = useState('');",
        "  const [message, setMessage] = useState('');\n"
        "  const [latestFormatting, setLatestFormatting] = useState<Record<string, FormattingJob>>({});",
        "Jobs.tsx state",
    )

    selected_effect = """  useEffect(() => {
    const visible = new Set(data?.items.map((item) => item.id) ?? []);
    setSelected((current) => current.filter((id) => visible.has(id)));
  }, [data]);
"""
    formatting_effect = selected_effect + """

  useEffect(() => {
    let active = true;
    const ids = data?.items
      .filter((job) => job.status === 'completed')
      .map((job) => job.id) ?? [];

    if (!ids.length) {
      setLatestFormatting({});
      return () => {
        active = false;
      };
    }

    void getLatestFormatting(ids)
      .then((result) => {
        if (active) setLatestFormatting(result);
      })
      .catch(() => {
        // Formatting is optional and must never hide existing transcriptions.
      });

    return () => {
      active = false;
    };
  }, [data]);
"""
    text_value = _replace_once(
        text_value,
        selected_effect,
        formatting_effect,
        "Jobs.tsx formatting effect",
    )
    text_value = _replace_once(
        text_value,
        '                <th className="download-column">التنزيل</th>',
        '                <th>التنسيق</th>\n'
        '                <th className="download-column">التنزيل</th>',
        "Jobs.tsx table header",
    )

    row_anchor = """                  <td>{new Date(job.created_at).toLocaleDateString('ar-JO')}</td>
                  <td className="download-column">
"""
    row_replacement = """                  <td>{new Date(job.created_at).toLocaleDateString('ar-JO')}</td>
                  <td>
                    {job.status === 'completed' ? (
                      <FormatTranscriptButton
                        sourceJobId={job.id}
                        latest={latestFormatting[job.id]}
                        onStarted={(created) =>
                          setLatestFormatting((current) => ({
                            ...current,
                            [job.id]: created,
                          }))
                        }
                      />
                    ) : (
                      <span className="download-unavailable">—</span>
                    )}
                  </td>
                  <td className="download-column">
"""
    text_value = _replace_once(
        text_value,
        row_anchor,
        row_replacement,
        "Jobs.tsx formatting cell",
    )
    if 'colSpan={9}' in text_value:
        text_value = text_value.replace('colSpan={9}', 'colSpan={10}', 1)
    elif 'colSpan={10}' not in text_value:
        raise IntegrationError("تعذر تحديث عدد أعمدة الحالة الفارغة في Jobs.tsx")

    _backup_and_write(project, backup_root, path, text_value)
    return "تمت إضافة زر التنسيق وحالة آخر محاولة إلى Jobs.tsx دون استبدال الصفحة."


def validate_source_assets(source_root: Path) -> None:
    validate_regular_tree(source_root, label="integration source tree")
    source_overlays = legacy_overlay_paths(source_root)
    if source_overlays:
        raise IntegrationError(
            "حزمة الدمج تحتوي overlay قديمًا عند مسار متداخل: "
            + source_overlays[0].relative_to(source_root).as_posix()
        )
    required_sources = [
        *(source_root / relative for relative in NEW_SOURCE_FILES),
        *(source_root / relative for relative in DOCUMENTATION_FILES),
        *(
            tooling_source_path(source_root, source_relative, target_relative)
            for source_relative, target_relative in TOOLING_FILES.items()
        ),
        source_root / MIGRATION_PATH,
        source_root / "docker-compose.yml",
    ]
    missing = []
    for path in required_sources:
        _, kind = validate_path_boundary(
            source_root,
            path,
            expected=frozenset({"file"}),
            allow_missing=True,
            label="required integration source",
        )
        if kind != "file":
            missing.append(str(path.relative_to(source_root)))
    if missing:
        raise IntegrationError(
            "حزمة الدمج غير مكتملة. ملفات المصدر الناقصة: " + ", ".join(missing)
        )

    migration_text = read_text(source_root, source_root / MIGRATION_PATH)
    count = migration_text.count(DOWN_REVISION_PLACEHOLDER)
    if count != 1:
        raise IntegrationError(
            "يجب أن يحتوي ترحيل التنسيق على علامة down_revision واحدة بالضبط؛ "
            f"العدد الحالي: {count}"
        )
    if parse_revision_value(migration_text, "revision") != "20260801_0100":
        raise IntegrationError("Revision ID لترحيل التنسيق غير صالح")

    compose_text = read_text(source_root, source_root / "docker-compose.yml")
    if "docker-compose.formatting.yml" in compose_text.casefold():
        raise IntegrationError(
            "docker-compose.yml الموحد ما زال يعتمد على ملف overlay القديم"
        )
    try:
        compose_data = yaml.safe_load(compose_text)
    except yaml.YAMLError as exc:
        raise IntegrationError("docker-compose.yml الموحد ليس YAML صالحًا") from exc
    services = compose_data.get("services") if isinstance(compose_data, dict) else None
    if not isinstance(services, dict):
        raise IntegrationError("docker-compose.yml الموحد لا يحتوي services صالحة")
    service_names = set(services)
    if service_names != CANONICAL_COMPOSE_SERVICES:
        missing_services = sorted(CANONICAL_COMPOSE_SERVICES - service_names)
        extra_services = sorted(service_names - CANONICAL_COMPOSE_SERVICES)
        raise IntegrationError(
            "docker-compose.yml الموحد يجب أن يحتوي خدماته الست عشرة المحددة فقط. "
            f"الناقصة: {missing_services or 'لا يوجد'}؛ "
            f"الزائدة: {extra_services or 'لا يوجد'}"
        )


def render_migration(source_root: Path, alembic_head: str) -> str:
    migration_text = read_text(source_root, source_root / MIGRATION_PATH)
    if migration_text.count(DOWN_REVISION_PLACEHOLDER) != 1:
        raise IntegrationError(
            "تعذر ربط الترحيل: علامة down_revision يجب أن تظهر مرة واحدة بالضبط"
        )
    migration_text = migration_text.replace(
        DOWN_REVISION_PLACEHOLDER,
        f'down_revision = "{alembic_head}"',
        1,
    )
    revises_placeholder = "Revises: REPLACE_WITH_CURRENT_HEAD"
    if migration_text.count(revises_placeholder) != 1:
        raise IntegrationError("تعذر ربط توثيق Revises في ترحيل التنسيق بأمان")
    migration_text = migration_text.replace(
        revises_placeholder, f"Revises: {alembic_head}", 1
    )
    if "REPLACE_WITH_CURRENT_HEAD" in migration_text:
        raise IntegrationError("بقيت علامة Alembic غير مستبدلة بعد تجهيز الترحيل")
    return migration_text


def stage_integration(
    project: Path,
    source_root: Path,
    staging: Path,
    alembic_head: str,
) -> tuple[list[Path], list[str]]:
    for relative in (*PATCH_FILES, *OPTIONAL_PATCH_FILES):
        source = project / relative
        _, source_kind = validate_path_boundary(
            project,
            source,
            expected=frozenset({"file"}),
            allow_missing=True,
            label="project staging source",
        )
        if source_kind == "file":
            destination = staging / relative
            _atomic_copy(
                project,
                source,
                staging,
                destination,
                temporary_tag="stage",
            )

    planned: set[Path] = set()
    for relative in NEW_SOURCE_FILES:
        destination = staging / relative
        _atomic_copy(
            source_root,
            source_root / relative,
            staging,
            destination,
            temporary_tag="stage",
        )
        planned.add(relative)
    for source_relative, target_relative in DOCUMENTATION_FILES.items():
        destination = staging / target_relative
        content = read_text(source_root, source_root / source_relative)
        write_text(
            staging,
            destination,
            render_merged_documentation(target_relative, content),
        )
        planned.add(target_relative)
    for source_relative, target_relative in TOOLING_FILES.items():
        destination = staging / target_relative
        _atomic_copy(
            source_root,
            tooling_source_path(source_root, source_relative, target_relative),
            staging,
            destination,
            temporary_tag="stage",
        )
        planned.add(target_relative)

    compose_relative = Path("docker-compose.yml")
    _atomic_copy(
        source_root,
        source_root / compose_relative,
        staging,
        staging / compose_relative,
        temporary_tag="stage",
    )
    planned.add(compose_relative)
    write_text(
        staging,
        staging / MIGRATION_PATH,
        render_migration(source_root, alembic_head),
    )
    planned.add(MIGRATION_PATH)

    scratch_backup = staging / ".preflight-backup"
    _safe_mkdir(staging, scratch_backup)
    messages = [
        patch_backend_requirements(staging, scratch_backup),
        patch_backend_main(staging, scratch_backup),
        patch_app_routes(staging, scratch_backup),
        patch_jobs_page(staging, scratch_backup),
        patch_settings(staging, scratch_backup),
        patch_navigation(staging, scratch_backup),
    ]
    planned.update(PATCH_FILES)
    for relative in OPTIONAL_PATCH_FILES:
        _, kind = validate_path_boundary(
            staging,
            staging / relative,
            expected=frozenset({"file"}),
            allow_missing=True,
            label="optional staged patch",
        )
        if kind == "file":
            planned.add(relative)
    return sorted(planned, key=lambda path: path.as_posix()), messages


def commit_staged_files(
    project: Path,
    staging: Path,
    relative_files: list[Path],
    backup_root: Path,
    *,
    expected_tree_sha256: str,
    expected_targets: dict[Path, FileSnapshot | None],
    project_lock: ProjectLock,
) -> None:
    assert_project_lock(project, project_lock)
    if tree_sha256(project) != expected_tree_sha256:
        raise IntegrationError(
            "تغيرت شجرة خط الأساس قبل Backup/الالتزام؛ رُفضت تعديلات متزامنة"
        )
    validate_regular_tree(staging, label="staged integration tree")
    existing: list[Path] = []
    created: list[Path] = []
    created_directories: set[Path] = set()
    for relative in relative_files:
        validate_path_boundary(
            staging,
            staging / relative,
            expected=frozenset({"file"}),
            label="staged commit source",
        )
        _, target_kind = validate_path_boundary(
            project,
            project / relative,
            expected=frozenset({"file"}),
            allow_missing=True,
            label="project commit target",
        )
        if relative not in expected_targets:
            raise IntegrationError(
                f"لا توجد هوية خط أساس مسجلة للهدف: {relative.as_posix()}"
            )
        _assert_target_snapshot(
            project,
            relative,
            expected_targets[relative],
            "بدء Backup/الالتزام",
        )
        if target_kind == "file":
            existing.append(relative)
        else:
            created.append(relative)
        parent = relative.parent
        while parent != Path("."):
            _, parent_kind = validate_path_boundary(
                project,
                project / parent,
                expected=frozenset({"directory"}),
                allow_missing=True,
                label="project commit parent",
            )
            if parent_kind == "missing":
                created_directories.add(parent)
            parent = parent.parent

    backup_parent = backup_root.parent
    validate_path_boundary(
        backup_parent,
        backup_parent,
        expected=frozenset({"directory"}),
        label="backup parent",
    )
    _, backup_kind = validate_path_boundary(
        backup_parent,
        backup_root,
        expected=frozenset({"directory"}),
        allow_missing=True,
        label="backup root",
    )
    if backup_kind != "missing":
        raise IntegrationError(f"مسار Backup موجود مسبقًا ولن يُستخدم: {backup_root}")
    _safe_mkdir(backup_parent, backup_root)
    metadata_path = backup_root / BACKUP_METADATA_NAME
    metadata = {
        "schema_version": 2,
        "commit_completed": False,
        "created_files": [path.as_posix() for path in created],
        "created_directories": [
            path.as_posix()
            for path in sorted(created_directories, key=lambda item: item.as_posix())
        ],
        "replaced_files": [path.as_posix() for path in existing],
        "attempted_destinations": [],
    }
    write_text(
        backup_parent,
        metadata_path,
        json.dumps(metadata, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
    )
    attempted: list[Path] = []
    committed_ownership: dict[Path, FileSnapshot] = {}
    created_directory_ownership: dict[Path, DirectoryOwnership] = {}
    try:
        # Finish every backup before replacing the first target file.
        for relative in existing:
            assert_project_lock(project, project_lock)
            _assert_target_snapshot(
                project,
                relative,
                expected_targets[relative],
                "نسخ Backup",
            )
            backup = backup_root / relative
            _atomic_copy(
                project,
                project / relative,
                backup_parent,
                backup,
                temporary_tag=backup_root.name,
            )

        for relative in sorted(created_directories, key=lambda path: len(path.parts)):
            assert_project_lock(project, project_lock)
            directory = project / relative
            _, directory_kind = validate_path_boundary(
                project,
                directory,
                expected=frozenset({"directory"}),
                allow_missing=True,
                label="project commit directory immediately before creation",
            )
            if directory_kind != "missing":
                raise IntegrationError(
                    f"ظهر مجلد هدف بالتزامن قبل إنشائه: {relative.as_posix()}"
                )
            try:
                directory.mkdir()
            except FileExistsError as exc:
                raise IntegrationError(
                    f"ظهر مجلد هدف بالتزامن أثناء إنشائه: {relative.as_posix()}"
                ) from exc
            created_directory_ownership[relative] = _directory_ownership(
                project,
                directory,
                "owned project commit directory",
            )

        for relative in relative_files:
            assert_project_lock(project, project_lock)
            _assert_target_snapshot(
                project,
                relative,
                expected_targets[relative],
                "الاستبدال",
            )
            destination = project / relative
            attempted.append(relative)
            metadata["attempted_destinations"] = [
                path.as_posix() for path in attempted
            ]
            write_text(
                backup_parent,
                metadata_path,
                json.dumps(metadata, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            )
            _atomic_copy(
                staging,
                staging / relative,
                project,
                destination,
                temporary_tag=f"formatting-{backup_root.name}",
                ownership_registry=committed_ownership,
                ownership_key=relative,
                enforce_destination_identity=True,
                expected_destination=expected_targets[relative],
            )
        metadata["commit_completed"] = True
        write_text(
            backup_parent,
            metadata_path,
            json.dumps(metadata, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        )
    except BaseException as commit_error:
        restoration_errors: list[str] = []
        for relative in reversed(attempted):
            destination = project / relative
            backup = backup_root / relative
            try:
                assert_project_lock(project, project_lock)
                owned_snapshot = committed_ownership.get(relative)
                if owned_snapshot is None:
                    continue
                current_snapshot = _target_snapshot(project, relative)
                if current_snapshot == expected_targets[relative]:
                    continue
                if current_snapshot != owned_snapshot:
                    restoration_errors.append(
                        f"{relative.as_posix()}: تغير الهدف إلى هوية غير مملوكة؛ "
                        "لم يُحذف ولم يُستبدل"
                    )
                    continue
                if relative in existing:
                    restored_snapshot = _atomic_copy(
                        backup_parent,
                        backup,
                        project,
                        destination,
                        temporary_tag=f"restore-{backup_root.name}",
                        enforce_destination_identity=True,
                        expected_destination=owned_snapshot,
                    )
                    original_snapshot = expected_targets[relative]
                    if original_snapshot is None or not _same_file_bytes(
                        restored_snapshot, original_snapshot
                    ):
                        raise IntegrationError(
                            "لا تطابق الملف المستعاد هوية/Bytes خط الأساس"
                        )
                else:
                    if _optional_file_snapshot(
                        project,
                        destination,
                        "owned rollback deletion immediately before unlink",
                    ) != owned_snapshot:
                        raise IntegrationError(
                            "تغير الملف المنشأ إلى هوية غير مملوكة قبل الحذف"
                        )
                    destination.unlink()
                    if _target_snapshot(project, relative) is not None:
                        raise IntegrationError("تعذر إثبات حذف الملف المنشأ المملوك")
            except BaseException as restore_error:
                restoration_errors.append(f"{relative.as_posix()}: {restore_error}")
        for relative in sorted(
            created_directory_ownership,
            key=lambda path: len(path.parts),
            reverse=True,
        ):
            directory = project / relative
            try:
                _, directory_kind = validate_path_boundary(
                    project,
                    directory,
                    expected=frozenset({"directory"}),
                    allow_missing=True,
                    label="rollback directory cleanup",
                )
                if directory_kind == "directory":
                    if _directory_ownership(
                        project,
                        directory,
                        "rollback directory ownership",
                    ) != created_directory_ownership[relative]:
                        restoration_errors.append(
                            f"{directory}: تغير المجلد إلى هوية غير مملوكة؛ لم يُحذف"
                        )
                        continue
                    directory.rmdir()
            except OSError as cleanup_error:
                restoration_errors.append(
                    f"{directory}: تعذر حذف المجلد المملوك؛ قد يحتوي تعديلًا متزامنًا: "
                    f"{cleanup_error}"
                )
            except UnsafeTreeObjectError as cleanup_error:
                restoration_errors.append(f"{directory}: {cleanup_error}")

        if restoration_errors:
            raise IntegrationError(
                "فشل إرجاع بعض الملفات بعد تعثر الدمج. حُفظت كل النسخ "
                f"القابلة للاسترداد في: {backup_root}. الأخطاء: "
                + "; ".join(restoration_errors)
            ) from commit_error

        try:
            validate_regular_tree(backup_root, label="completed rollback backup")
            shutil.rmtree(backup_root)
        except (OSError, UnsafeTreeObjectError) as cleanup_error:
            raise IntegrationError(
                "اكتملت استعادة الملفات، لكن تعذر تأكيد حذف النسخة الاحتياطية: "
                f"{backup_root}. اتركها للمراجعة اليدوية. الخطأ: {cleanup_error}"
            ) from commit_error
        raise


def validate_project(project: Path) -> None:
    validate_regular_tree(project, label="target project tree")
    overlays = legacy_overlay_paths(project)
    if overlays:
        legacy_overlay = overlays[0]
        raise IntegrationError(
            f"اكتُشف {legacy_overlay.relative_to(project).as_posix()} قديم في المشروع الهدف. "
            "أزله أو انقله يدويًا بعد مراجعة إعداداته، ثم أعد الدمج؛ "
            "لم تُكتب أي ملفات."
        )
    missing: list[str] = []
    for relative in ORIGINAL_BASELINE_FILES:
        _, kind = validate_path_boundary(
            project,
            project / relative,
            expected=frozenset({"file"}),
            allow_missing=True,
            label="baseline file",
        )
        if kind != "file":
            missing.append(relative.as_posix())
    for relative in ORIGINAL_BASELINE_DIRECTORIES:
        _, kind = validate_path_boundary(
            project,
            project / relative,
            expected=frozenset({"directory"}),
            allow_missing=True,
            label="baseline directory",
        )
        if kind != "directory":
            missing.append(relative.as_posix() + "/")
    if missing:
        raise IntegrationError(
            "المجلد لا يطابق آخر بنية متوقعة للمشروع. الملفات الناقصة: "
            + ", ".join(missing)
        )


def apply(
    project: Path,
    source_root: Path | None = None,
    backup_parent: Path | None = None,
    *,
    expected_tree_sha256: str | None = None,
    acknowledge_unverified_base: bool = False,
    _verified_zip_base: bool = False,
) -> list[str]:
    project = Path(os.path.abspath(os.fspath(project)))
    source_root = Path(os.path.abspath(os.fspath(source_root or ROOT)))
    validate_source_assets(source_root)
    validate_project(project)
    expected_baseline_tree_sha256 = tree_sha256(project)
    baseline_message: str
    if expected_tree_sha256 and acknowledge_unverified_base:
        raise IntegrationError(
            "لا يجوز خلط هوية شجرة متوقعة مع إقرار خط أساس غير متحقق"
        )
    if _verified_zip_base:
        if expected_tree_sha256 or acknowledge_unverified_base:
            raise IntegrationError("لا يجوز خلط إثبات ZIP الداخلي مع إقرارات خط أساس أخرى")
        baseline_message = "تم إثبات خط الأساس من ZIP ذي البصمة المرجعية الدقيقة."
    elif expected_tree_sha256:
        normalized_identity = expected_tree_sha256.casefold()
        if not re.fullmatch(r"[0-9a-f]{64}", normalized_identity):
            raise IntegrationError("يجب أن تكون بصمة شجرة خط الأساس SHA-256 من 64 خانة")
        actual_tree_sha256 = expected_baseline_tree_sha256
        if actual_tree_sha256 != normalized_identity:
            raise IntegrationError(
                "هوية شجرة خط الأساس لا تطابق القيمة المتوقعة؛ لم تُكتب أي ملفات. "
                f"المتوقع: {normalized_identity}؛ الفعلي: {actual_tree_sha256}"
            )
        baseline_message = (
            f"طابقت هوية شجرة خط الأساس المتوقعة: {actual_tree_sha256}. "
            "يبقى الفحص التمهيدي بنيويًا لأنه لم يبدأ من ZIP المرجعي الدقيق."
        )
    elif acknowledge_unverified_base:
        baseline_message = (
            "تحذير شديد: أُقر تطبيق مباشر على مجلد غير مُثبت الهوية. الفحص "
            "التمهيدي بنيوي فقط ولا يثبت نسخة خط الأساس أو سلامة محتواها."
        )
    else:
        raise IntegrationError(
            "رُفض التطبيق المباشر افتراضيًا لأن هوية خط الأساس غير مُثبتة. "
            "استخدم --expected-tree-sha256 لهوية شجرة متوقعة مستقلة، أو "
            "--acknowledge-unverified-base فقط بعد مراجعة يدوية وقبول أن الفحص بنيوي فقط."
        )
    alembic_head = current_alembic_head(project)
    with tempfile.TemporaryDirectory(prefix="formatting-integration-stage-") as temp:
        staging = Path(temp) / "project"
        staging.mkdir()
        validate_regular_tree(staging, label="empty integration staging tree")
        planned, patch_messages = stage_integration(
            project, source_root, staging, alembic_head
        )
        if tree_sha256(project) != expected_baseline_tree_sha256:
            raise IntegrationError(
                "تغيرت شجرة خط الأساس أثناء التجهيز؛ لم يبدأ Backup أو الالتزام"
            )
        expected_targets = {
            relative: _target_snapshot(project, relative) for relative in planned
        }
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        backup_parent = Path(
            os.path.abspath(os.fspath(backup_parent or project))
        )
        validate_path_boundary(
            backup_parent,
            backup_parent,
            expected=frozenset({"directory"}),
            label="backup parent",
        )
        if backup_parent != project:
            try:
                backup_parent.resolve(strict=True).relative_to(project.resolve(strict=True))
            except ValueError:
                pass
            else:
                raise IntegrationError(
                    "يجب أن يكون مجلد Backup البديل خارج جذر المشروع بالكامل"
                )
        backup_root = backup_parent / f".formatting-integration-backup-{timestamp}"
        project_lock = acquire_project_lock(project)
        try:
            assert_project_lock(project, project_lock)
            if tree_sha256(project) != expected_baseline_tree_sha256:
                raise IntegrationError(
                    "تغيرت شجرة خط الأساس قبل Backup/الالتزام النهائي؛ رُفض الدمج"
                )
            for relative in planned:
                _assert_target_snapshot(
                    project,
                    relative,
                    expected_targets[relative],
                    "الفحص النهائي",
                )
            commit_staged_files(
                project,
                staging,
                planned,
                backup_root,
                expected_tree_sha256=expected_baseline_tree_sha256,
                expected_targets=expected_targets,
                project_lock=project_lock,
            )
        finally:
            release_project_lock(project, project_lock)

    messages: list[str] = [
        baseline_message,
        f"رأس Alembic الحالي: {alembic_head}",
        *patch_messages,
    ]
    messages.append(f"النسخ الاحتياطية: {backup_root}")
    if backup_parent == project:
        messages.append(
            "قبل Verifier أو الرفع: أرشف مجلد النسخ الاحتياطية خارج جذر المشروع، "
            "ثم أزله يدويًا من الشجرة فقط بعد تأكيد سلامة الدمج وإمكان الاسترداد."
        )
    messages.append(
        "لم يُعدّل السكربت app/tasks.py أو خدمات YouTube/Deepgram أو عمّال التفريغ."
    )
    return messages

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="دمج عامل التنسيق في تطبيق التفريغ")
    parser.add_argument("project", type=Path, help="مسار مجلد آخر نسخة من المشروع")
    identity = parser.add_mutually_exclusive_group()
    identity.add_argument(
        "--expected-tree-sha256",
        help="SHA-256 متوقع لهوية الشجرة القانونية التي يحسبها السكربت قبل أي كتابة",
    )
    identity.add_argument(
        "--acknowledge-unverified-base",
        action="store_true",
        help=(
            "تحذير: تطبيق مباشر على مجلد غير مثبت الهوية؛ الفحص بنيوي فقط ولا "
            "يثبت إصدار خط الأساس أو سلامة محتواه"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        messages = apply(
            args.project.expanduser(),
            expected_tree_sha256=args.expected_tree_sha256,
            acknowledge_unverified_base=args.acknowledge_unverified_base,
        )
    except (IntegrationError, UnsafeTreeObjectError, OSError) as exc:
        print(f"خطأ: {exc}", file=sys.stderr)
        return 1
    for message in messages:
        print(f"- {message}")
    print(
        "اكتمل الدمج المرحلي. لا تشغّل Verifier ولا ترفع المشروع حتى تؤرشف "
        "مجلد .formatting-integration-backup-* خارج جذر المشروع وتحذفه من الشجرة "
        "بعد تأكيد إمكان الاسترداد؛ بعدها شغّل Verifier وأوقف العملية عند أي خطأ."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
