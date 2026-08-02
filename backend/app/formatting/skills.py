from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import stat
import tempfile
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable

import yaml

from app.formatting.config import FormattingConfig

SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---(?:\s*\n|\Z)", re.DOTALL)
_ARCHIVE_LOCKS_GUARD = threading.Lock()
_ARCHIVE_LOCKS: dict[str, threading.RLock] = {}


class SkillArchiveError(ValueError):
    pass


class SkillArchiveCancelled(SkillArchiveError):
    pass


def _check_cancellation(
    cancellation_callback: Callable[[], bool] | None,
) -> None:
    if cancellation_callback is not None and cancellation_callback():
        raise SkillArchiveCancelled("أُلغيت مهمة التنسيق أثناء تجهيز المهارة")


@dataclass(frozen=True, slots=True)
class InstalledSkill:
    name: str
    slug: str
    description: str
    sha256: str
    archive_path: Path
    extracted_path: Path
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _ValidatedSkillArchive:
    name: str
    description: str
    metadata: dict[str, Any]
    files: dict[str, zipfile.ZipInfo]


def _safe_member(name: str) -> PurePosixPath:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or normalized.startswith("/") or path.is_absolute():
        raise SkillArchiveError("الأرشيف يحتوي مسارًا مطلقًا غير مسموح")
    if any(
        part in {"", ".", ".."}
        or ":" in part
        or any(ord(character) < 32 for character in part)
        for part in path.parts
    ):
        raise SkillArchiveError("الأرشيف يحتوي مسارًا غير آمن")
    return path


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(mode)


def _is_unsafe_archive_type(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    if mode == 0 or stat.S_IFMT(mode) == 0:
        return False
    if info.is_dir():
        return not stat.S_ISDIR(mode)
    return not stat.S_ISREG(mode)


def _parse_skill_markdown(content: str) -> tuple[str, str, dict[str, Any]]:
    match = FRONTMATTER_RE.match(content.replace("\r\n", "\n"))
    if not match:
        raise SkillArchiveError("يجب أن يبدأ SKILL.md ببيانات YAML front matter")
    try:
        metadata = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise SkillArchiveError("تعذر قراءة YAML داخل SKILL.md") from exc
    if not isinstance(metadata, dict):
        raise SkillArchiveError("بيانات SKILL.md يجب أن تكون كائن YAML")
    name = str(metadata.get("name") or "").strip()
    description = str(metadata.get("description") or "").strip()
    if not SKILL_NAME_RE.fullmatch(name) or len(name) > 64:
        raise SkillArchiveError(
            "اسم المهارة يجب أن يكون 1–64 حرفًا من أحرف إنجليزية صغيرة وأرقام وشرطة مفردة"
        )
    if not 1 <= len(description) <= 1024:
        raise SkillArchiveError("وصف المهارة مطلوب ويجب ألا يتجاوز 1024 حرفًا")

    optional_scalar_fields = ("license", "compatibility")
    for field in optional_scalar_fields:
        value = metadata.get(field)
        if value is not None and not isinstance(value, str):
            raise SkillArchiveError(f"الحقل {field} في SKILL.md يجب أن يكون نصًا")

    extra_metadata = metadata.get("metadata")
    if extra_metadata is not None:
        if not isinstance(extra_metadata, dict):
            raise SkillArchiveError("الحقل metadata في SKILL.md يجب أن يكون كائنًا")
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in extra_metadata.items()):
            raise SkillArchiveError("جميع قيم metadata في SKILL.md يجب أن تكون نصوصًا")

    return name, description, metadata


def _path_exists(path: Path) -> bool:
    return os.path.lexists(path)


def _is_link_like(path: Path, path_stat: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(path_stat, "st_file_attributes", 0)
    return path.is_symlink() or stat.S_ISLNK(path_stat.st_mode) or bool(
        reparse_flag and attributes & reparse_flag
    )


def _verify_archive(path: Path, expected_sha256: str, max_bytes: int) -> None:
    try:
        archive_stat = path.lstat()
    except OSError as exc:
        raise SkillArchiveError("تعذر فحص أرشيف المهارة المحفوظ") from exc
    if (
        _is_link_like(path, archive_stat)
        or not stat.S_ISREG(archive_stat.st_mode)
        or archive_stat.st_nlink > 1
        or archive_stat.st_size <= 0
        or archive_stat.st_size > max_bytes
    ):
        raise SkillArchiveError("أرشيف المهارة المحفوظ غير آمن")
    digest = hashlib.sha256()
    total = 0
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                total += len(chunk)
                if total > max_bytes:
                    raise SkillArchiveError(
                        "حجم أرشيف المهارة المحفوظ أكبر من الحد المسموح"
                    )
                digest.update(chunk)
    except OSError as exc:
        raise SkillArchiveError("تعذر قراءة أرشيف المهارة المحفوظ") from exc
    if total != archive_stat.st_size or digest.hexdigest() != expected_sha256:
        raise SkillArchiveError("أرشيف المهارة المحفوظ لا يطابق بصمته")


def _stream_sha256(
    stream: Any,
    cancellation_callback: Callable[[], bool] | None = None,
) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        _check_cancellation(cancellation_callback)
        digest.update(chunk)
    return digest.hexdigest()


def _require_contained_components(
    root: Path,
    candidate: Path,
    *,
    leaf_kind: str,
    label: str,
) -> Path:
    if not candidate.is_absolute():
        raise SkillArchiveError(f"{label} ليس مسارًا مطلقًا")
    try:
        root_stat = root.lstat()
        root_resolved = root.resolve(strict=True)
        relative = candidate.relative_to(root)
    except (OSError, ValueError) as exc:
        raise SkillArchiveError(f"{label} خارج جذر المهارات المسموح") from exc
    if (
        _is_link_like(root, root_stat)
        or not stat.S_ISDIR(root_stat.st_mode)
        or root_resolved != root
    ):
        raise SkillArchiveError("جذر تخزين المهارات غير آمن")

    current = root
    for index, part in enumerate(relative.parts):
        if part in {"", ".", ".."}:
            raise SkillArchiveError(f"{label} يحتوي مكوّنًا غير صالح")
        current = current / part
        try:
            current_stat = current.lstat()
        except FileNotFoundError:
            break
        except OSError as exc:
            raise SkillArchiveError(f"تعذر فحص {label}") from exc
        if _is_link_like(current, current_stat):
            raise SkillArchiveError(f"{label} يحتوي رابطًا أو نقطة إعادة تحليل")
        is_leaf = index == len(relative.parts) - 1
        if is_leaf and leaf_kind == "file":
            if not stat.S_ISREG(current_stat.st_mode) or current_stat.st_nlink != 1:
                raise SkillArchiveError(f"{label} ليس ملفًا عاديًا آمنًا")
        elif not stat.S_ISDIR(current_stat.st_mode):
            raise SkillArchiveError(f"{label} يحتوي مكوّنًا خاصًا أو غير مجلد")
        try:
            resolved = current.resolve(strict=True)
            resolved.relative_to(root_resolved)
        except (OSError, ValueError) as exc:
            raise SkillArchiveError(f"{label} يخرج من جذر المهارات") from exc
        if resolved != current:
            raise SkillArchiveError(f"{label} يحتوي مكوّنًا غير محلول بأمان")
    return candidate


def _validate_archive_contents(
    archive: zipfile.ZipFile,
    config: FormattingConfig,
    cancellation_callback: Callable[[], bool] | None = None,
) -> _ValidatedSkillArchive:
    total_size = 0
    member_count = 0
    file_count = 0
    seen_paths: set[str] = set()
    skill_entries: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
    safe_entries: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
    for info in archive.infolist():
        _check_cancellation(cancellation_callback)
        member_count += 1
        if member_count > config.skill_max_files:
            raise SkillArchiveError("عدد عناصر المهارة أكبر من الحد المسموح")
        path = _safe_member(info.filename)
        normalized_key = path.as_posix().casefold()
        if normalized_key in seen_paths:
            raise SkillArchiveError("الأرشيف يحتوي مسارات ملفات مكررة")
        seen_paths.add(normalized_key)
        if _is_symlink(info) or _is_unsafe_archive_type(info):
            raise SkillArchiveError("الأرشيف يحتوي رابطًا أو عنصرًا خاصًا غير مسموح")
        if info.flag_bits & 0x1:
            raise SkillArchiveError("ملفات المهارة المشفرة غير مدعومة")
        if not info.is_dir():
            file_count += 1
            total_size += max(0, info.file_size)
            if total_size > config.skill_max_unpacked_bytes:
                raise SkillArchiveError("حجم المهارة بعد فك الضغط أكبر من الحد المسموح")
            if path.name == "SKILL.md":
                skill_entries.append((info, path))
        safe_entries.append((info, path))

    if file_count == 0:
        raise SkillArchiveError("ملف ZIP لا يحتوي ملفات")

    if len(skill_entries) != 1:
        raise SkillArchiveError("يجب أن يحتوي ZIP على ملف SKILL.md واحد فقط")

    skill_info, skill_path = skill_entries[0]
    try:
        skill_chunks: list[bytes] = []
        skill_size = 0
        with archive.open(skill_info) as skill_stream:
            for chunk in iter(lambda: skill_stream.read(1024 * 1024), b""):
                _check_cancellation(cancellation_callback)
                skill_size += len(chunk)
                if (
                    skill_size > skill_info.file_size
                    or skill_size > config.skill_max_unpacked_bytes
                ):
                    raise SkillArchiveError(
                        "تجاوز SKILL.md حجمه المعلن أثناء القراءة"
                    )
                skill_chunks.append(chunk)
        if skill_size != skill_info.file_size:
            raise SkillArchiveError("حجم SKILL.md لا يطابق الحجم المعلن")
        content = b"".join(skill_chunks).decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SkillArchiveError("يجب حفظ SKILL.md بترميز UTF-8") from exc
    except (RuntimeError, OSError, zipfile.BadZipFile) as exc:
        raise SkillArchiveError("تعذر قراءة SKILL.md من الأرشيف بأمان") from exc
    name, description, metadata = _parse_skill_markdown(content)
    if skill_path.parent != PurePosixPath(".") and skill_path.parent.name != name:
        raise SkillArchiveError(
            "اسم مجلد المهارة داخل ZIP يجب أن يطابق name في SKILL.md"
        )

    skill_parent = skill_path.parent
    selected_files: dict[str, zipfile.ZipInfo] = {}
    for info, member in safe_entries:
        if info.is_dir():
            continue
        try:
            relative = member.relative_to(skill_parent)
        except ValueError:
            continue
        selected_files[relative.as_posix()] = info
    return _ValidatedSkillArchive(
        name=name,
        description=description,
        metadata=metadata,
        files=selected_files,
    )


def _read_verified_archive(
    path: Path,
    expected_sha256: str,
    max_bytes: int,
    cancellation_callback: Callable[[], bool] | None = None,
) -> bytes:
    try:
        before = path.lstat()
    except OSError as exc:
        raise SkillArchiveError("تعذر فحص أرشيف المهارة المحفوظ") from exc
    if (
        _is_link_like(path, before)
        or not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or before.st_size <= 0
        or before.st_size > max_bytes
    ):
        raise SkillArchiveError("أرشيف المهارة المحفوظ غير آمن")
    digest = hashlib.sha256()
    chunks: list[bytes] = []
    total = 0
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                _check_cancellation(cancellation_callback)
                total += len(chunk)
                if total > max_bytes:
                    raise SkillArchiveError("حجم أرشيف المهارة أكبر من الحد المسموح")
                digest.update(chunk)
                chunks.append(chunk)
        after = path.lstat()
    except OSError as exc:
        raise SkillArchiveError("تعذر قراءة أرشيف المهارة المحفوظ") from exc
    if (
        _is_link_like(path, after)
        or not stat.S_ISREG(after.st_mode)
        or after.st_nlink != 1
        or after.st_dev != before.st_dev
        or after.st_ino != before.st_ino
        or after.st_size != before.st_size
        or total != before.st_size
        or digest.hexdigest() != expected_sha256
    ):
        raise SkillArchiveError("أرشيف المهارة المحفوظ لا يطابق Snapshot المهمة")
    return b"".join(chunks)


def _verify_installed_version(
    version_root: Path,
    name: str,
    archive: zipfile.ZipFile,
    expected_files: dict[str, zipfile.ZipInfo],
    cancellation_callback: Callable[[], bool] | None = None,
) -> Path:
    extracted_path = version_root / name
    try:
        root_stat = version_root.lstat()
        extracted_stat = extracted_path.lstat()
    except OSError as exc:
        raise SkillArchiveError("إصدار المهارة المحفوظ سابقًا غير مكتمل") from exc
    if (
        _is_link_like(version_root, root_stat)
        or _is_link_like(extracted_path, extracted_stat)
        or not stat.S_ISDIR(root_stat.st_mode)
        or not stat.S_ISDIR(extracted_stat.st_mode)
    ):
        raise SkillArchiveError("إصدار المهارة المحفوظ سابقًا غير آمن")

    actual_files: dict[str, Path] = {}
    actual_directories: set[str] = set()
    directories = [version_root]
    maximum_entries = len(expected_files) + sum(
        len(PurePosixPath(relative).parents) - 1 for relative in expected_files
    ) + 1
    actual_entry_count = 0
    while directories:
        _check_cancellation(cancellation_callback)
        directory = directories.pop()
        try:
            with os.scandir(directory) as iterator:
                for entry in iterator:
                    _check_cancellation(cancellation_callback)
                    actual_entry_count += 1
                    if actual_entry_count > maximum_entries:
                        raise SkillArchiveError(
                            "إصدار المهارة المحفوظ يحتوي عناصر زائدة"
                        )
                    path = Path(entry.path)
                    relative = path.relative_to(version_root)
                    try:
                        entry_stat = path.lstat()
                    except OSError as exc:
                        raise SkillArchiveError(
                            "تعذر فحص إصدار المهارة المحفوظ"
                        ) from exc
                    if _is_link_like(path, entry_stat):
                        raise SkillArchiveError(
                            "إصدار المهارة المحفوظ يحتوي عنصرًا غير آمن"
                        )
                    if stat.S_ISDIR(entry_stat.st_mode):
                        actual_directories.add(relative.as_posix())
                        directories.append(path)
                    elif stat.S_ISREG(entry_stat.st_mode) and entry_stat.st_nlink <= 1:
                        actual_files[relative.as_posix()] = path
                    else:
                        raise SkillArchiveError(
                            "إصدار المهارة المحفوظ يحتوي عنصرًا غير آمن"
                        )
        except OSError as exc:
            raise SkillArchiveError("تعذر فحص إصدار المهارة المحفوظ") from exc

    expected_version_files = {
        f"{name}/{relative}": info for relative, info in expected_files.items()
    }
    expected_directories = {name}
    for relative in expected_version_files:
        parent = PurePosixPath(relative).parent
        while parent != PurePosixPath("."):
            expected_directories.add(parent.as_posix())
            parent = parent.parent
    if (
        actual_files.keys() != expected_version_files.keys()
        or actual_directories != expected_directories
    ):
        raise SkillArchiveError("إصدار المهارة المحفوظ سابقًا غير مكتمل")
    for relative, info in expected_version_files.items():
        _check_cancellation(cancellation_callback)
        path = actual_files[relative]
        try:
            if path.stat().st_size != info.file_size:
                raise SkillArchiveError("إصدار المهارة المحفوظ لا يطابق الأرشيف")
            with archive.open(info) as expected, path.open("rb") as actual:
                if _stream_sha256(
                    expected, cancellation_callback
                ) != _stream_sha256(actual, cancellation_callback):
                    raise SkillArchiveError("إصدار المهارة المحفوظ لا يطابق الأرشيف")
        except OSError as exc:
            raise SkillArchiveError("تعذر قراءة إصدار المهارة المحفوظ") from exc
    return extracted_path


def _publish_archive(
    blob: bytes,
    archive_path: Path,
    sha256: str,
    config: FormattingConfig,
) -> None:
    lock_key = str(archive_path.absolute())
    with _ARCHIVE_LOCKS_GUARD:
        archive_lock = _ARCHIVE_LOCKS.setdefault(lock_key, threading.RLock())
    with archive_lock:
        if archive_path != config.skill_archives_root / f"{sha256}.zip":
            raise SkillArchiveError("مسار نشر أرشيف المهارة غير صالح")
        _require_contained_components(
            config.skill_archives_root,
            archive_path,
            leaf_kind="file",
            label="أرشيف المهارة",
        )
        if _path_exists(archive_path):
            try:
                _verify_archive(
                    archive_path, sha256, config.skill_max_archive_bytes
                )
                return
            except SkillArchiveError:
                pass

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{sha256}.", suffix=".tmp", dir=archive_path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(blob)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, archive_path)
            _verify_archive(archive_path, sha256, config.skill_max_archive_bytes)
        finally:
            temporary.unlink(missing_ok=True)


def install_skill_archive(blob: bytes, config: FormattingConfig) -> InstalledSkill:
    config.ensure_persistent_directories()
    if not blob:
        raise SkillArchiveError("ملف المهارة فارغ")
    if len(blob) > config.skill_max_archive_bytes:
        raise SkillArchiveError("حجم ملف المهارة أكبر من الحد المسموح")

    sha256 = hashlib.sha256(blob).hexdigest()
    archive_path = config.skill_archives_root / f"{sha256}.zip"
    version_root = config.skill_versions_root / sha256

    try:
        archive = zipfile.ZipFile(io.BytesIO(blob))
    except (zipfile.BadZipFile, OSError) as exc:
        raise SkillArchiveError("الملف ليس ZIP صالحًا") from exc

    with archive:
        validated = _validate_archive_contents(archive, config)
        name = validated.name
        description = validated.description
        metadata = validated.metadata
        expected_files = validated.files

        _publish_archive(blob, archive_path, sha256, config)

        lock_key = str(archive_path.absolute())
        with _ARCHIVE_LOCKS_GUARD:
            archive_lock = _ARCHIVE_LOCKS.setdefault(lock_key, threading.RLock())
        with archive_lock:
            cache_valid = False
            if _path_exists(version_root):
                try:
                    extracted_path = _verify_installed_version(
                        version_root, name, archive, expected_files
                    )
                    cache_valid = True
                except SkillArchiveError:
                    cache_valid = False
            if not cache_valid:
                backup_root = config.skill_versions_root / f".{sha256}.previous"
                if _path_exists(backup_root):
                    raise SkillArchiveError(
                        "تعذر إصلاح نسخة المهارة المستخرجة لوجود نسخة احتياطية عالقة"
                    )
                temp_root = Path(
                    tempfile.mkdtemp(
                        prefix=f".{sha256}.install-", dir=config.skill_versions_root
                    )
                )
                try:
                    extracted_path = temp_root / name
                    extracted_path.mkdir(parents=True, exist_ok=False)
                    for relative_name, info in expected_files.items():
                        relative = PurePosixPath(relative_name)
                        destination = extracted_path / Path(*relative.parts)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        written = 0
                        with archive.open(info) as source, destination.open("wb") as target:
                            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                                written += len(chunk)
                                if written > info.file_size:
                                    raise SkillArchiveError(
                                        "تجاوز ملف المهارة حجمه المعلن أثناء الاستخراج"
                                    )
                                target.write(chunk)
                        if written != info.file_size:
                            raise SkillArchiveError(
                                "حجم ملف المهارة المستخرج لا يطابق الأرشيف"
                            )
                    if not (extracted_path / "SKILL.md").is_file():
                        raise SkillArchiveError("تعذر استخراج SKILL.md")
                    _verify_installed_version(temp_root, name, archive, expected_files)
                    had_previous = _path_exists(version_root)
                    if had_previous:
                        os.replace(version_root, backup_root)
                    try:
                        os.replace(temp_root, version_root)
                    except Exception:
                        if had_previous and _path_exists(backup_root):
                            os.replace(backup_root, version_root)
                        raise
                    extracted_path = _verify_installed_version(
                        version_root, name, archive, expected_files
                    )
                    if _path_exists(backup_root):
                        backup_stat = backup_root.lstat()
                        if _is_link_like(backup_root, backup_stat):
                            backup_root.unlink()
                        elif stat.S_ISDIR(backup_stat.st_mode):
                            shutil.rmtree(backup_root)
                        else:
                            backup_root.unlink()
                except Exception:
                    shutil.rmtree(temp_root, ignore_errors=True)
                    raise
                finally:
                    shutil.rmtree(temp_root, ignore_errors=True)

    metadata_copy = json.loads(json.dumps(metadata, ensure_ascii=False, default=str))
    return InstalledSkill(
        name=name,
        slug=name,
        description=description,
        sha256=sha256,
        archive_path=archive_path,
        extracted_path=extracted_path,
        metadata=metadata_copy,
    )


def materialize_verified_skill(
    config: FormattingConfig,
    *,
    archive_path: Path,
    expected_sha256: str,
    expected_name: str,
    expected_slug: str,
    destination: Path,
    cancellation_callback: Callable[[], bool] | None = None,
) -> Path:
    config.ensure_persistent_directories()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise SkillArchiveError("بصمة Snapshot المهارة غير صالحة")
    if (
        expected_name != expected_slug
        or not SKILL_NAME_RE.fullmatch(expected_name)
        or len(expected_name) > 64
    ):
        raise SkillArchiveError("اسم وslug Snapshot المهارة غير متطابقين")

    expected_archive = config.skill_archives_root / f"{expected_sha256}.zip"
    if archive_path != expected_archive:
        raise SkillArchiveError("مسار سجل أرشيف المهارة لا يطابق الإصدار المعنون بالبصمة")
    _require_contained_components(
        config.skill_archives_root,
        archive_path,
        leaf_kind="file",
        label="أرشيف المهارة",
    )
    blob = _read_verified_archive(
        archive_path,
        expected_sha256,
        config.skill_max_archive_bytes,
        cancellation_callback,
    )
    try:
        archive = zipfile.ZipFile(io.BytesIO(blob))
    except (zipfile.BadZipFile, OSError) as exc:
        raise SkillArchiveError("أرشيف Snapshot المهارة ليس ZIP صالحًا") from exc

    with archive:
        validated = _validate_archive_contents(
            archive, config, cancellation_callback
        )
        if validated.name != expected_name:
            raise SkillArchiveError("اسم المهارة داخل الأرشيف لا يطابق Snapshot المهمة")

        _require_contained_components(
            config.execution_root,
            destination,
            leaf_kind="directory",
            label="وجهة مهارة التنفيذ",
        )
        if _path_exists(destination):
            raise SkillArchiveError("وجهة مهارة التنفيذ موجودة مسبقًا")
        try:
            destination.mkdir(exist_ok=False)
        except OSError as exc:
            raise SkillArchiveError("تعذر إنشاء وجهة مهارة التنفيذ") from exc
        _require_contained_components(
            config.execution_root,
            destination,
            leaf_kind="directory",
            label="وجهة مهارة التنفيذ",
        )

        try:
            for relative_name, info in sorted(validated.files.items()):
                _check_cancellation(cancellation_callback)
                relative = PurePosixPath(relative_name)
                target = destination / Path(*relative.parts)
                parent = destination
                for part in relative.parts[:-1]:
                    parent = parent / part
                    _require_contained_components(
                        config.execution_root,
                        parent,
                        leaf_kind="directory",
                        label="مجلد داخل مهارة التنفيذ",
                    )
                    parent.mkdir(exist_ok=True)
                    _require_contained_components(
                        config.execution_root,
                        parent,
                        leaf_kind="directory",
                        label="مجلد داخل مهارة التنفيذ",
                    )
                _require_contained_components(
                    config.execution_root,
                    target,
                    leaf_kind="file",
                    label="ملف داخل مهارة التنفيذ",
                )
                flags = (
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_BINARY", 0)
                )
                descriptor = os.open(target, flags, 0o600)
                written = 0
                try:
                    with archive.open(info) as source, os.fdopen(
                        descriptor, "wb"
                    ) as output:
                        descriptor = -1
                        for chunk in iter(lambda: source.read(1024 * 1024), b""):
                            _check_cancellation(cancellation_callback)
                            written += len(chunk)
                            if written > info.file_size:
                                raise SkillArchiveError(
                                    "تجاوز ملف المهارة حجمه المعلن أثناء الاستخراج"
                                )
                            output.write(chunk)
                finally:
                    if descriptor >= 0:
                        os.close(descriptor)
                target_stat = target.lstat()
                if (
                    _is_link_like(target, target_stat)
                    or not stat.S_ISREG(target_stat.st_mode)
                    or target_stat.st_nlink != 1
                    or written != info.file_size
                    or target_stat.st_size != info.file_size
                ):
                    raise SkillArchiveError("فشل التحقق من ملف مهارة التنفيذ")
        except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
            raise SkillArchiveError("تعذر استخراج Snapshot المهارة بأمان") from exc

    if not (destination / "SKILL.md").is_file():
        raise SkillArchiveError("لم تُستخرج نسخة SKILL.md المعتمدة")
    return destination
