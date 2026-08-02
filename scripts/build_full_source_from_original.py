#!/usr/bin/env python3
"""Build a true merged source ZIP from the known original project archive.

This utility is included because the original ZIP bytes were not mounted in the
artifact runtime that produced the integration package. It safely extracts the
operator-provided original archive from the same identity-bound handle it hashes,
applies the formatting integration with recovery outside the project, and publishes
an identity-checked quarantine under an exclusive output lock before hashing the
published bytes again.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import stat
import tempfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO

if __package__:
    from scripts.apply_formatting_integration import IntegrationError, apply
    from scripts.formatting_integration_tree import (
        REPARSE_POINT_ATTRIBUTE,
        UnsafeTreeObjectError,
        legacy_overlay_paths,
        prohibited_tree_reason,
        suspicious_secret_like,
        validate_path_boundary,
        validate_regular_tree,
    )
    from scripts.verify_coolify_bundle import verify
else:  # Direct execution from scripts/ or copied tools/formatting-integration/.
    from apply_formatting_integration import IntegrationError, apply
    from formatting_integration_tree import (
        REPARSE_POINT_ATTRIBUTE,
        UnsafeTreeObjectError,
        legacy_overlay_paths,
        prohibited_tree_reason,
        suspicious_secret_like,
        validate_path_boundary,
        validate_regular_tree,
    )
    from verify_coolify_bundle import verify

KNOWN_BASE_SHA256 = "58130f9529f6f362717ca4993002c052bf7252ecb5ff62655fd2618c9c0f300d"
MAX_SOURCE_FILES = 50_000
MAX_SOURCE_UNPACKED_BYTES = 5 * 1024 * 1024 * 1024
FileIdentity = tuple[int, int, int, int]
OutputLock = tuple[Path, BinaryIO, FileIdentity]

class BuildError(RuntimeError):
    pass


def file_identity(details: os.stat_result) -> FileIdentity:
    return (
        details.st_dev,
        details.st_ino,
        details.st_size,
        details.st_mtime_ns,
    )


def checked_regular_identity(
    details: os.stat_result,
    path: Path,
    label: str,
) -> FileIdentity:
    if getattr(details, "st_file_attributes", 0) & REPARSE_POINT_ATTRIBUTE:
        raise BuildError(f"Refusing reparse point for {label}: {path}")
    if stat.S_ISLNK(details.st_mode):
        raise BuildError(f"Refusing symlink for {label}: {path}")
    if not stat.S_ISREG(details.st_mode):
        raise BuildError(f"Refusing special filesystem object for {label}: {path}")
    if details.st_nlink != 1:
        raise BuildError(f"Refusing hard-linked file for {label}: {path}")
    return file_identity(details)


def path_identity(path: Path, boundary: Path, label: str) -> FileIdentity:
    path, _ = validate_path_boundary(
        boundary,
        path,
        expected=frozenset({"file"}),
        label=label,
    )
    return checked_regular_identity(path.lstat(), path, label)


def assert_path_identity(
    path: Path,
    boundary: Path,
    expected: FileIdentity,
    label: str,
) -> None:
    if path_identity(path, boundary, label) != expected:
        raise BuildError(f"تغيرت هوية {label} أثناء العملية؛ أُوقفت العملية")


def open_stable_regular_file(
    path: Path,
    boundary: Path,
    label: str,
) -> tuple[BinaryIO, FileIdentity]:
    initial = path_identity(path, boundary, label)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    stream = os.fdopen(descriptor, "rb")
    try:
        opened = checked_regular_identity(os.fstat(stream.fileno()), path, label)
        if opened != initial:
            raise BuildError(f"تغيرت هوية {label} أثناء فتحه؛ أُوقفت العملية")
        assert_path_identity(path, boundary, initial, label)
        return stream, initial
    except BaseException:
        stream.close()
        raise


def digest_open_file(
    stream: BinaryIO,
    path: Path,
    boundary: Path,
    expected: FileIdentity,
    label: str,
) -> str:
    opened_before = checked_regular_identity(os.fstat(stream.fileno()), path, label)
    if opened_before != expected:
        raise BuildError(f"تغيرت هوية {label} قبل حساب البصمة")
    assert_path_identity(path, boundary, expected, label)
    stream.seek(0)
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    opened_after = checked_regular_identity(os.fstat(stream.fileno()), path, label)
    if opened_after != expected:
        raise BuildError(f"تغيرت هوية {label} أثناء حساب البصمة")
    assert_path_identity(path, boundary, expected, label)
    return digest.hexdigest()


def stable_file_digest(
    path: Path,
    boundary: Path,
    label: str,
    expected: FileIdentity | None = None,
) -> tuple[FileIdentity, str]:
    stream, identity = open_stable_regular_file(path, boundary, label)
    try:
        if expected is not None and identity != expected:
            raise BuildError(f"تغيرت هوية {label}؛ أُوقفت العملية")
        return identity, digest_open_file(
            stream,
            path,
            boundary,
            identity,
            label,
        )
    finally:
        stream.close()


def sha256_file(path: Path, boundary: Path | None = None) -> str:
    path, _ = validate_path_boundary(
        boundary or path.parent,
        path,
        expected=frozenset({"file"}),
        label="SHA-256 input",
    )
    return stable_file_digest(
        path,
        boundary or path.parent,
        "SHA-256 input",
    )[1]


def safe_member(name: str) -> PurePosixPath:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or normalized.startswith("/") or path.is_absolute():
        raise BuildError("الأرشيف الأصلي يحتوي مسارًا مطلقًا غير آمن")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise BuildError("الأرشيف الأصلي يحتوي Path Traversal")
    if path.parts and ":" in path.parts[0]:
        raise BuildError("الأرشيف الأصلي يحتوي مسار Windows مطلقًا")
    return path


def is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(mode)


def validate_zip_member_type(info: zipfile.ZipInfo) -> None:
    mode = (info.external_attr >> 16) & 0xFFFF
    file_type = stat.S_IFMT(mode)
    dos_attributes = info.external_attr & 0xFFFF
    if dos_attributes & REPARSE_POINT_ATTRIBUTE:
        raise BuildError("الأرشيف الأصلي يحتوي Reparse Point؛ أوقف البناء للأمان")
    if is_symlink(info):
        raise BuildError("الأرشيف الأصلي يحتوي رابطًا رمزيًا؛ أوقف البناء للأمان")
    allowed_type = stat.S_IFDIR if info.is_dir() else stat.S_IFREG
    if file_type not in {0, allowed_type}:
        raise BuildError("الأرشيف الأصلي يحتوي ملفًا خاصًا أو نوعًا غير مدعوم")


def safe_mkdir(boundary: Path, directory: Path) -> None:
    directory, kind = validate_path_boundary(
        boundary,
        directory,
        expected=frozenset({"directory"}),
        allow_missing=True,
        label="builder directory target",
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
            label="builder directory target",
        )
        if current_kind == "missing":
            current.mkdir()
            validate_path_boundary(
                boundary,
                current,
                expected=frozenset({"directory"}),
                label="created builder directory",
            )


def safe_unlink(boundary: Path, path: Path) -> None:
    path, kind = validate_path_boundary(
        boundary,
        path,
        expected=frozenset({"file"}),
        allow_missing=True,
        label="builder unlink target",
    )
    if kind == "file":
        path.unlink()


def safe_extract(
    archive_stream: BinaryIO,
    archive_path: Path,
    archive_identity: FileIdentity,
    archive_sha256: str,
    destination: Path,
) -> None:
    before_extract = digest_open_file(
        archive_stream,
        archive_path,
        archive_path.parent,
        archive_identity,
        "source ZIP immediately before extraction",
    )
    if before_extract != archive_sha256:
        raise BuildError("تغيرت Bytes الأرشيف الأصلي قبل فكّه؛ أُوقف البناء")
    archive_stream.seek(0)
    validate_regular_tree(destination, label="extraction destination")
    try:
        archive = zipfile.ZipFile(archive_stream)
    except zipfile.BadZipFile as exc:
        raise BuildError("الأرشيف الأصلي ليس ZIP صالحًا") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_SOURCE_FILES:
            raise BuildError("عدد ملفات الأرشيف الأصلي أكبر من الحد الآمن")
        total_size = 0
        seen: set[str] = set()
        for info in infos:
            member = safe_member(info.filename)
            key = member.as_posix().casefold()
            if key in seen:
                raise BuildError("الأرشيف الأصلي يحتوي مسارات مكررة")
            seen.add(key)
            validate_zip_member_type(info)
            if not info.is_dir():
                total_size += max(0, info.file_size)
                if total_size > MAX_SOURCE_UNPACKED_BYTES:
                    raise BuildError("الحجم المفكوك للأرشيف الأصلي أكبر من الحد الآمن")
            target = destination / Path(*member.parts)
            if info.is_dir():
                safe_mkdir(destination, target)
                continue
            safe_mkdir(destination, target.parent)
            validate_path_boundary(
                destination,
                target,
                expected=frozenset({"file"}),
                allow_missing=True,
                label="extracted file target",
            )
            temporary = target.with_name(f".{target.name}.extract.tmp")
            _, temporary_kind = validate_path_boundary(
                destination,
                temporary,
                expected=frozenset({"file"}),
                allow_missing=True,
                label="extraction temporary",
            )
            if temporary_kind != "missing":
                raise BuildError(f"ملف فك مؤقت موجود مسبقًا ولن يُستبدل: {temporary}")
            try:
                with archive.open(info) as source, temporary.open("xb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                    output.flush()
                    os.fsync(output.fileno())
                validate_path_boundary(
                    destination,
                    temporary,
                    expected=frozenset({"file"}),
                    label="extraction temporary",
                )
                os.replace(temporary, target)
            finally:
                safe_unlink(destination, temporary)
    after_extract = digest_open_file(
        archive_stream,
        archive_path,
        archive_path.parent,
        archive_identity,
        "source ZIP after extraction",
    )
    if after_extract != archive_sha256:
        raise BuildError("تغيرت Bytes الأرشيف الأصلي أثناء فكّه؛ أُوقف البناء")
    validate_regular_tree(destination, label="extracted source tree")
    overlays = legacy_overlay_paths(destination)
    if overlays:
        raise BuildError(
            "الأرشيف الأصلي يحتوي overlay قديمًا عند مسار متداخل: "
            + overlays[0].relative_to(destination).as_posix()
        )


def project_root(extracted: Path) -> Path:
    def valid(path: Path) -> bool:
        return all(
            validate_path_boundary(
                extracted,
                path / marker,
                expected=frozenset({"file"}),
                allow_missing=True,
                label="extracted project marker",
            )[1]
            == "file"
            for marker in (
                "backend/app/main.py",
                "frontend/src/App.tsx",
                "docker-compose.yml",
            )
        )

    validate_regular_tree(extracted, label="project-root discovery tree")
    if valid(extracted):
        return extracted
    candidates = []
    for path in extracted.iterdir():
        _, kind = validate_path_boundary(
            extracted,
            path,
            expected=frozenset({"file", "directory"}),
            label="project-root candidate",
        )
        if kind == "directory" and valid(path):
            candidates.append(path)
    if len(candidates) != 1:
        raise BuildError(
            "تعذر تحديد جذر المشروع داخل الأرشيف. يجب أن توجد بنية backend/frontend واحدة."
        )
    return candidates[0]


def excluded(relative: Path) -> bool:
    return prohibited_tree_reason(relative) is not None


def validate_package_tree(project: Path) -> None:
    validate_regular_tree(project, label="package tree")
    prohibited: list[str] = []
    for path in sorted(project.rglob("*")):
        relative = path.relative_to(project)
        validate_path_boundary(
            project,
            path,
            expected=frozenset({"file", "directory"}),
            label="package tree entry",
        )
        reason = prohibited_tree_reason(relative)
        if reason is not None:
            prohibited.append(f"{relative.as_posix()} ({reason})")
    if prohibited:
        raise BuildError(
            "توجد ملفات محظورة أو مشتبه بأنها أسرار/حالة محلية. راجعها وانقلها "
            "يدويًا قبل التحقق والتغليف؛ لن تُحذف بصمت: " + ", ".join(prohibited)
        )


def write_zip(project: Path, output_zip: Path) -> None:
    """Build and validate an unpublished ZIP at a new quarantine path."""
    validate_package_tree(project)
    source_snapshot: dict[Path, tuple[FileIdentity, str]] = {}
    for path in validate_regular_tree(project, label="ZIP snapshot source tree"):
        relative = path.relative_to(project)
        if excluded(relative):
            raise BuildError(
                "تغيرت شجرة المشروع بعد الفحص وظهر ملف محظور: "
                + relative.as_posix()
            )
        source_snapshot[relative] = stable_file_digest(
            path,
            project,
            "ZIP snapshot source",
        )
    validate_path_boundary(
        output_zip.parent,
        output_zip.parent,
        expected=frozenset({"directory"}),
        label="ZIP output parent",
    )
    _, output_kind = validate_path_boundary(
        output_zip.parent,
        output_zip,
        expected=frozenset({"file"}),
        allow_missing=True,
        label="ZIP quarantine output",
    )
    if output_kind != "missing":
        raise BuildError(f"مسار ZIP الحجر موجود مسبقًا ولن يُستبدل: {output_zip}")
    try:
        with zipfile.ZipFile(
            output_zip,
            mode="x",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as archive:
            root_name = project.name or "youtube-deepgram-transcriber"
            for relative, (expected_identity, expected_sha256) in source_snapshot.items():
                path = project / relative
                source, opened_identity = open_stable_regular_file(
                    path,
                    project,
                    "ZIP archive source",
                )
                if opened_identity != expected_identity:
                    source.close()
                    raise BuildError(
                        f"تغيرت هوية ملف التغليف قبل قراءته: {relative.as_posix()}"
                    )
                info = zipfile.ZipInfo(
                    (Path(root_name) / relative).as_posix(),
                    date_time=(1980, 1, 1, 0, 0, 0),
                )
                info.create_system = 3
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                streamed_digest = hashlib.sha256()
                with source, archive.open(info, mode="w", force_zip64=True) as target:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        streamed_digest.update(chunk)
                        target.write(chunk)
                    opened_after = checked_regular_identity(
                        os.fstat(source.fileno()),
                        path,
                        "ZIP archive source after read",
                    )
                    assert_path_identity(
                        path,
                        project,
                        expected_identity,
                        "ZIP archive source after read",
                    )
                if opened_after != expected_identity:
                    raise BuildError(
                        f"تغيرت هوية ملف التغليف أثناء قراءته: {relative.as_posix()}"
                    )
                if streamed_digest.hexdigest() != expected_sha256:
                    raise BuildError(
                        f"تغيرت Bytes ملف التغليف أثناء قراءته: {relative.as_posix()}"
                    )
            final_files = validate_regular_tree(
                project,
                label="ZIP source tree after archive reads",
            )
            if [path.relative_to(project) for path in final_files] != list(
                source_snapshot
            ):
                raise BuildError("تغيرت عضوية شجرة المصدر أثناء التغليف")
            for relative, expected in source_snapshot.items():
                current = stable_file_digest(
                    project / relative,
                    project,
                    "ZIP source final snapshot recheck",
                    expected=expected[0],
                )
                if current != expected:
                    raise BuildError(
                        f"تغير ملف بعد قراءته أثناء التغليف: {relative.as_posix()}"
                    )
        validate_path_boundary(
            output_zip.parent,
            output_zip,
            expected=frozenset({"file"}),
            label="completed ZIP quarantine",
        )
        if not zipfile.is_zipfile(output_zip):
            raise BuildError("تعذر إنشاء ZIP نهائي صالح")
        with zipfile.ZipFile(output_zip) as archive:
            broken = archive.testzip()
            if broken:
                raise BuildError(f"ملف تالف داخل ZIP النهائي: {broken}")
    except BaseException as exc:
        try:
            safe_unlink(output_zip.parent, output_zip)
        except BaseException as cleanup_error:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                if hasattr(exc, "add_note"):
                    exc.add_note(f"تعذر تنظيف ZIP الحجر: {cleanup_error}")
                raise
            if isinstance(cleanup_error, (KeyboardInterrupt, SystemExit)):
                if hasattr(cleanup_error, "add_note"):
                    cleanup_error.add_note(f"خطأ إنشاء ZIP الأصلي: {exc}")
                raise
            raise BuildError(
                f"فشل إنشاء ZIP الحجر وتعذر تنظيفه: {output_zip}: {cleanup_error}"
            ) from exc
        raise


def private_output_path(output_zip: Path, tag: str) -> Path:
    for _ in range(10):
        candidate = output_zip.with_name(
            f".{output_zip.name}.{uuid.uuid4().hex}.{tag}"
        )
        _, kind = validate_path_boundary(
            output_zip.parent,
            candidate,
            expected=frozenset({"file"}),
            allow_missing=True,
            label=f"private output {tag}",
        )
        if kind == "missing":
            return candidate
    raise BuildError(f"تعذر حجز مسار خاص آمن بجانب الناتج: {tag}")


def acquire_output_lock(output_zip: Path) -> OutputLock:
    lock_path = output_zip.with_name(f".{output_zip.name}.build.lock")
    validate_path_boundary(
        output_zip.parent,
        output_zip.parent,
        expected=frozenset({"directory"}),
        label="output lock parent",
    )
    _, lock_kind = validate_path_boundary(
        output_zip.parent,
        lock_path,
        expected=frozenset({"file"}),
        allow_missing=True,
        label="exclusive output lock",
    )
    if lock_kind != "missing":
        raise BuildError(
            f"قفل بناء حصري موجود ولن يُحذف تلقائيًا: {lock_path}. "
            "تحقق يدويًا من عدم وجود Builder عامل قبل إزالة القفل."
        )
    try:
        stream = lock_path.open("xb")
    except FileExistsError as exc:
        raise BuildError(f"رفض البناء المتزامن؛ قفل الناتج موجود: {lock_path}") from exc
    identity: FileIdentity | None = None
    try:
        stream.write(f"pid={os.getpid()}\noutput={output_zip}\n".encode("utf-8"))
        stream.flush()
        os.fsync(stream.fileno())
        identity = checked_regular_identity(
            os.fstat(stream.fileno()),
            lock_path,
            "exclusive output lock",
        )
        assert_path_identity(
            lock_path,
            output_zip.parent,
            identity,
            "exclusive output lock",
        )
        return lock_path, stream, identity
    except BaseException:
        stream.close()
        if identity is not None:
            try:
                assert_path_identity(
                    lock_path,
                    output_zip.parent,
                    identity,
                    "failed exclusive output lock",
                )
                lock_path.unlink()
            except OSError:
                pass
        raise


def assert_output_lock(output_zip: Path, output_lock: OutputLock) -> None:
    lock_path, stream, expected = output_lock
    opened = checked_regular_identity(
        os.fstat(stream.fileno()),
        lock_path,
        "exclusive output lock",
    )
    if opened != expected:
        raise BuildError("تغيرت هوية مقبض قفل الناتج؛ أُوقف النشر")
    assert_path_identity(
        lock_path,
        output_zip.parent,
        expected,
        "exclusive output lock",
    )


def release_output_lock(output_zip: Path, output_lock: OutputLock) -> None:
    lock_path, stream, expected = output_lock
    assert_output_lock(output_zip, output_lock)
    stream.close()
    assert_path_identity(
        lock_path,
        output_zip.parent,
        expected,
        "exclusive output lock before release",
    )
    lock_path.unlink()


def publish_no_clobber(
    source: Path,
    output_zip: Path,
    expected_identity: FileIdentity,
    output_lock: OutputLock,
) -> FileIdentity:
    assert_output_lock(output_zip, output_lock)
    assert_path_identity(
        source,
        output_zip.parent,
        expected_identity,
        "unpublished artifact",
    )
    try:
        os.link(source, output_zip)
    except FileExistsError as exc:
        raise BuildError(
            f"ظهر ناتج متزامن ولن يُستبدل: {output_zip}"
        ) from exc
    try:
        source.unlink()
    except BaseException as unlink_error:
        try:
            assert_output_lock(output_zip, output_lock)
            published_details = output_zip.lstat()
            if (
                getattr(published_details, "st_file_attributes", 0)
                & REPARSE_POINT_ATTRIBUTE
                or not stat.S_ISREG(published_details.st_mode)
                or file_identity(published_details) != expected_identity
            ):
                raise BuildError(
                    "تغير ناتج no-clobber بعد الربط؛ لم يُحذف مسار غير مملوك"
                )
            output_zip.unlink()
        except BaseException as cleanup_error:
            if hasattr(unlink_error, "add_note"):
                unlink_error.add_note(
                    f"تعذر إزالة ناتج no-clobber المملوك بعد فشل فك رابط الحجر: "
                    f"{cleanup_error}"
                )
        raise
    published = path_identity(output_zip, output_zip.parent, "published output")
    if published != expected_identity:
        raise BuildError("هوية الناتج المنشور لا تطابق أثر الحجر")
    return published


def build(
    base_zip: Path,
    output_zip: Path,
    allow_different_base: bool,
    source_root: Path | None = None,
    acknowledge_unverified_base: bool = False,
) -> list[str]:
    base_zip = Path(os.path.abspath(os.fspath(base_zip)))
    output_zip = Path(os.path.abspath(os.fspath(output_zip)))
    if os.path.normcase(os.fspath(base_zip)) == os.path.normcase(os.fspath(output_zip)):
        raise BuildError("يجب أن يختلف base_zip عن output_zip دائمًا؛ رُفض استبدال المصدر")
    validate_path_boundary(
        output_zip.parent,
        output_zip.parent,
        expected=frozenset({"directory"}),
        label="output parent",
    )
    output_lock = acquire_output_lock(output_zip)
    try:
        return _build_locked(
            base_zip,
            output_zip,
            allow_different_base,
            source_root=source_root,
            acknowledge_unverified_base=acknowledge_unverified_base,
            output_lock=output_lock,
        )
    finally:
        release_output_lock(output_zip, output_lock)


def _build_locked(
    base_zip: Path,
    output_zip: Path,
    allow_different_base: bool,
    *,
    source_root: Path | None,
    acknowledge_unverified_base: bool,
    output_lock: OutputLock,
) -> list[str]:
    assert_output_lock(output_zip, output_lock)
    _, base_kind = validate_path_boundary(
        base_zip.parent,
        base_zip,
        expected=frozenset({"file"}),
        allow_missing=True,
        label="base ZIP",
    )
    if base_kind != "file":
        raise BuildError(f"الأرشيف الأصلي غير موجود: {base_zip}")
    _, output_kind = validate_path_boundary(
        output_zip.parent,
        output_zip,
        expected=frozenset({"file"}),
        allow_missing=True,
        label="output ZIP",
    )
    if output_kind != "missing":
        raise BuildError(
            f"مسار الناتج موجود ولن يُستبدل: {output_zip}. اختر مسارًا جديدًا، "
            "أو أزل الناتج القديم يدويًا قبل بدء Builder."
        )

    base_stream, base_identity = open_stable_regular_file(
        base_zip,
        base_zip.parent,
        "base ZIP",
    )
    try:
        actual_sha = digest_open_file(
            base_stream,
            base_zip,
            base_zip.parent,
            base_identity,
            "base ZIP identity hash",
        )
        if actual_sha != KNOWN_BASE_SHA256 and not allow_different_base:
            raise BuildError(
                "بصمة الأرشيف لا تطابق آخر نسخة معروفة. "
                "استخدم --allow-different-base فقط بعد مراجعة الفروقات يدويًا.\n"
                f"المتوقع: {KNOWN_BASE_SHA256}\nالفعلي: {actual_sha}"
            )
        if actual_sha != KNOWN_BASE_SHA256 and not acknowledge_unverified_base:
            raise BuildError(
                "المصدر المختلف يتطلب الإقرارين معًا: --allow-different-base و"
                "--acknowledge-unverified-base. تحذير شديد: الفحص التالي بنيوي فقط "
                "ولا يثبت هوية خط الأساس أو سلامة محتواه."
            )
        if actual_sha == KNOWN_BASE_SHA256 and acknowledge_unverified_base:
            raise BuildError(
                "لا تستخدم --acknowledge-unverified-base مع ZIP ذي البصمة المرجعية الدقيقة"
            )
    except BaseException:
        base_stream.close()
        raise

    quarantine_zip = private_output_path(output_zip, "quarantine")
    work_root: Path | None = None
    recovery_parent: Path | None = None
    recovery_backups: list[Path] = []
    output_sha: str | None = None
    quarantine_identity: FileIdentity | None = None
    quarantine_sha256: str | None = None
    publication_identity: FileIdentity | None = None
    publication_attempted = False
    messages: list[str] = []
    try:
        work_root = Path(tempfile.mkdtemp(prefix="tafreeg-full-source-"))
        extracted = work_root / "source"
        extracted.mkdir()
        validate_regular_tree(extracted, label="empty extraction tree")
        try:
            safe_extract(
                base_stream,
                base_zip,
                base_identity,
                actual_sha,
                extracted,
            )
        finally:
            base_stream.close()
        project = project_root(extracted)
        validate_package_tree(project)

        recovery_parent = Path(
            tempfile.mkdtemp(
                prefix=".formatting-integration-recovery-",
                dir=output_zip.parent,
            )
        )
        validate_regular_tree(recovery_parent, label="external recovery root")
        messages = apply(
            project,
            source_root=source_root,
            backup_parent=recovery_parent,
            acknowledge_unverified_base=actual_sha != KNOWN_BASE_SHA256,
            _verified_zip_base=actual_sha == KNOWN_BASE_SHA256,
        )
        validate_regular_tree(recovery_parent, label="external recovery tree")
        recovery_backups = list(
            recovery_parent.glob(".formatting-integration-backup-*")
        )
        if len(recovery_backups) != 1:
            raise BuildError(
                "تعذر تأكيد وجود نسخة استرداد خارج شجرة المشروع قبل Verifier"
            )
        if any(
            path.name.casefold().startswith(".formatting-integration-backup-")
            for path in project.rglob("*")
        ):
            raise BuildError(
                "بقي Backup داخل شجرة المشروع؛ أُلغي Verifier والتغليف"
            )
        verification_errors = verify(project)
        if verification_errors:
            raise BuildError(
                "فشل Verifier للمصدر المدمج؛ لم يُنشر ZIP:\n- "
                + "\n- ".join(verification_errors)
        )
        validate_package_tree(project)
        write_zip(project, quarantine_zip)
        quarantine_identity, quarantine_sha256 = stable_file_digest(
            quarantine_zip,
            output_zip.parent,
            "completed ZIP quarantine",
        )

        validate_regular_tree(
            recovery_backups[0],
            label="recovery backup before final cleanup",
        )
        shutil.rmtree(recovery_backups[0])
        recovery_parent.rmdir()
        recovery_parent = None
        shutil.rmtree(work_root)
        if work_root.exists():
            raise BuildError("تعذر تأكيد تنظيف شجرة العمل المؤقتة قبل نشر ZIP")

        if quarantine_identity is None or quarantine_sha256 is None:
            raise BuildError("لم تُثبت هوية وبصمة ZIP الحجر؛ رُفض النشر")
        prepublish_identity, prepublish_sha256 = stable_file_digest(
            quarantine_zip,
            output_zip.parent,
            "ZIP quarantine immediately before publication",
            expected=quarantine_identity,
        )
        if (
            prepublish_identity != quarantine_identity
            or prepublish_sha256 != quarantine_sha256
        ):
            raise BuildError("تغير ZIP الحجر قبل النشر؛ رُفض نشر Bytes قديمة التحقق")
        assert_output_lock(output_zip, output_lock)
        _, final_output_kind = validate_path_boundary(
            output_zip.parent,
            output_zip,
            expected=frozenset({"file"}),
            allow_missing=True,
            label="atomic ZIP destination",
        )
        if final_output_kind != "missing":
            raise BuildError(
                "ظهر مسار الناتج أثناء البناء؛ رُفض النشر الذري دون استبداله"
            )
        publication_attempted = True
        publication_identity = publish_no_clobber(
            quarantine_zip,
            output_zip,
            quarantine_identity,
            output_lock,
        )

        final_identity, final_sha256 = stable_file_digest(
            output_zip,
            output_zip.parent,
            "final published output",
            expected=publication_identity,
        )
        if final_identity != publication_identity or final_sha256 != quarantine_sha256:
            raise BuildError(
                "بصمة الناتج النهائي لا تطابق ZIP الحجر؛ سيُحجر الناتج المملوك أو يُزال"
            )
        output_sha = final_sha256
    except BaseException as exc:
        if not base_stream.closed:
            base_stream.close()
        cleanup_errors: list[str] = []
        cleanup_interrupt: BaseException | None = (
            exc if isinstance(exc, (KeyboardInterrupt, SystemExit)) else None
        )
        if publication_attempted and publication_identity is not None:
            try:
                assert_output_lock(output_zip, output_lock)
                _, current_output_kind = validate_path_boundary(
                    output_zip.parent,
                    output_zip,
                    expected=frozenset({"file"}),
                    allow_missing=True,
                    label="failed publication output",
                )
                if current_output_kind == "file":
                    current_identity = path_identity(
                        output_zip,
                        output_zip.parent,
                        "failed publication output",
                    )
                    if current_identity == publication_identity:
                        assert_path_identity(
                            output_zip,
                            output_zip.parent,
                            publication_identity,
                            "owned failed publication output",
                        )
                        output_zip.unlink()
                    else:
                        cleanup_errors.append(
                            "تغير الناتج النهائي إلى هوية غير مملوكة؛ لم يُحذف ولم يُستبدل"
                        )
            except BaseException as cleanup_error:
                if isinstance(cleanup_error, (KeyboardInterrupt, SystemExit)):
                    cleanup_interrupt = cleanup_interrupt or cleanup_error
                cleanup_errors.append(
                    f"تعذر حجر/إزالة الناتج المنشور المملوك بأمان: {cleanup_error}"
                )
        for boundary, path, label in (
            (output_zip.parent, quarantine_zip, "ZIP الحجر"),
        ):
            try:
                safe_unlink(boundary, path)
            except BaseException as cleanup_error:
                if isinstance(cleanup_error, (KeyboardInterrupt, SystemExit)):
                    cleanup_interrupt = cleanup_interrupt or cleanup_error
                cleanup_errors.append(f"تعذر تنظيف {label} عند {path}: {cleanup_error}")
        if work_root is not None and work_root.exists():
            try:
                shutil.rmtree(work_root)
            except BaseException as cleanup_error:
                if isinstance(cleanup_error, (KeyboardInterrupt, SystemExit)):
                    cleanup_interrupt = cleanup_interrupt or cleanup_error
                cleanup_errors.append(
                    f"تعذر تنظيف شجرة العمل المؤقتة {work_root}: {cleanup_error}"
                )
        if recovery_parent is not None and recovery_parent.exists():
            recovery_backups = list(
                recovery_parent.glob(".formatting-integration-backup-*")
            )
            if not recovery_backups:
                try:
                    recovery_parent.rmdir()
                    recovery_parent = None
                except BaseException as cleanup_error:
                    if isinstance(cleanup_error, (KeyboardInterrupt, SystemExit)):
                        cleanup_interrupt = cleanup_interrupt or cleanup_error
                    cleanup_errors.append(
                        f"تعذر تنظيف حاوية الاسترداد الفارغة: {cleanup_error}"
                    )
        if cleanup_interrupt is not None:
            if cleanup_errors and hasattr(cleanup_interrupt, "add_note"):
                cleanup_interrupt.add_note("؛ ".join(cleanup_errors))
            if cleanup_interrupt is exc:
                raise
            raise cleanup_interrupt
        recovery_message = (
            f" حُفظ Backup الاسترداد للمراجعة عند: {recovery_parent}."
            if recovery_parent is not None and recovery_parent.exists()
            else ""
        )
        cleanup_message = (
            " أخطاء التنظيف/الاستعادة: " + "؛ ".join(cleanup_errors)
            if cleanup_errors
            else ""
        )
        raise BuildError(
            f"فشل البناء قبل نشر ZIP النهائي؛ لم يُنشر أثر غير مكتمل.{recovery_message} "
            f"السبب: {exc}.{cleanup_message}"
        ) from exc
    if output_sha is None:
        raise BuildError("لم تُثبت بصمة Bytes الناتج المنشور؛ لا يوجد نجاح قابل للإرجاع")
    verification_message = "اجتاز المصدر المدمج Verifier الكامل قبل التغليف."
    if actual_sha != KNOWN_BASE_SHA256:
        verification_message = (
            "تحذير: استُخدم --allow-different-base بصورة يدوية غير آمنة. "
            "اكتمل فحص خط الأساس ونجحت فحوص Verifier البنيوية فقط، لكن الناتج "
            "غير مُتحقق من "
            "مطابقة خط الأساس ولا يجوز وصفه بأنه مصدر كامل حقيقي مُتحقق."
        )
    return [
        f"SHA-256 للمصدر: {actual_sha}",
        *(message for message in messages if not message.startswith("النسخ الاحتياطية:")),
        verification_message,
        f"نجاح صريح: ZIP الناتج صالح ومنشور بقفل حصري، وتطابق Hash Bytes المنشورة: {output_zip}",
        f"SHA-256 للناتج: {output_sha}",
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="إنشاء ZIP مصدر كامل بعد دمج ميزة التنسيق"
    )
    parser.add_argument("base_zip", type=Path, help="آخر ZIP أصلي لتطبيق التفريغ")
    parser.add_argument("output_zip", type=Path, help="مسار ZIP النهائي")
    parser.add_argument(
        "--allow-different-base",
        action="store_true",
        help=(
            "تجاوز يدوي غير آمن لبصمة المصدر بعد مراجعة كاملة؛ الناتج لا يُعد "
            "متحققًا من خط الأساس أو مصدرًا كاملًا حقيقيًا متحققًا"
        ),
    )
    parser.add_argument(
        "--acknowledge-unverified-base",
        action="store_true",
        help=(
            "إقرار ثان إلزامي مع --allow-different-base بأن الفحص بنيوي فقط ولا "
            "يثبت هوية خط الأساس أو سلامة محتواه"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        messages = build(
            args.base_zip.expanduser().resolve(),
            args.output_zip.expanduser().resolve(),
            args.allow_different_base,
            acknowledge_unverified_base=args.acknowledge_unverified_base,
        )
    except (BuildError, IntegrationError, UnsafeTreeObjectError, OSError) as exc:
        print(f"خطأ: {exc}")
        return 1
    for message in messages:
        print(f"- {message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
