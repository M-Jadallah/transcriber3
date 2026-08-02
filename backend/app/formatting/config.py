from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


EXECUTION_ROOT_SENTINEL = ".formatting-execution-root"
EXECUTION_ROOT_SENTINEL_CONTENT = b"transcriptr-formatting-execution-v1\n"


def _is_root_path(path: Path) -> bool:
    return path == Path(path.anchor)


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _is_link_like(path: Path, path_stat: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(path_stat, "st_file_attributes", 0)
    return path.is_symlink() or stat.S_ISLNK(path_stat.st_mode) or bool(
        reparse_flag and attributes & reparse_flag
    )


@dataclass(frozen=True, slots=True)
class FormattingConfig:
    root: Path
    execution_root: Path
    exports_root: Path
    opencode_url: str
    opencode_control_url: str
    opencode_username: str
    opencode_password: str
    default_model: str
    default_reasoning: str
    task_timeout_seconds: int
    skill_max_archive_bytes: int
    skill_max_files: int
    skill_max_unpacked_bytes: int
    output_max_files: int
    output_max_total_bytes: int
    output_max_single_file_bytes: int
    input_max_bytes: int = 20 * 1024 * 1024
    execution_workspace_max_entries: int = 5000
    execution_workspace_max_bytes: int = 768 * 1024 * 1024
    docx_max_members: int = 2000
    docx_max_uncompressed_bytes: int = 200 * 1024 * 1024
    execution_log_max_bytes: int = 20 * 1024 * 1024
    storage_max_bytes: int = 20 * 1024 * 1024 * 1024

    def __post_init__(self) -> None:
        for field_name in ("root", "execution_root", "exports_root"):
            path = Path(getattr(self, field_name))
            if not path.is_absolute():
                raise ValueError(f"{field_name} must be an absolute path")
            resolved = path.resolve()
            if path != resolved:
                raise ValueError(f"{field_name} must be a resolved path")
            if _is_root_path(resolved):
                raise ValueError(f"{field_name} must not be a filesystem root")
            object.__setattr__(self, field_name, resolved)

        configured_roots = (
            ("root", self.root),
            ("execution_root", self.execution_root),
            ("exports_root", self.exports_root),
        )
        for index, (left_name, left) in enumerate(configured_roots):
            for right_name, right in configured_roots[index + 1 :]:
                if _is_within(left, right) or _is_within(right, left):
                    raise ValueError(
                        f"{left_name} and {right_name} must be fully disjoint"
                    )

    @property
    def skills_root(self) -> Path:
        return self.root / "skills"

    @property
    def skill_archives_root(self) -> Path:
        return self.skills_root / "archives"

    @property
    def skill_versions_root(self) -> Path:
        return self.skills_root / "versions"

    @property
    def jobs_root(self) -> Path:
        return self.root / "jobs"

    def ensure_persistent_directories(self) -> None:
        directories = (
            (self.root, "formatting root", True),
            (self.skills_root, "skills root", False),
            (self.skill_archives_root, "skill archives root", False),
            (self.skill_versions_root, "skill versions root", False),
            (self.jobs_root, "formatting jobs root", False),
        )
        for path, label, create_parents in directories:
            self._require_safe_existing_parents(path, label)
            try:
                path.mkdir(parents=create_parents, exist_ok=True)
            except OSError as exc:
                raise ValueError(f"{label} is unavailable") from exc
            self._require_directory(path, label)

    @staticmethod
    def _require_safe_existing_parents(path: Path, label: str) -> None:
        current = Path(path.anchor)
        for part in path.parts[1:]:
            current = current / part
            try:
                current_stat = current.lstat()
            except FileNotFoundError:
                break
            except OSError as exc:
                raise ValueError(f"{label} has an unavailable parent") from exc
            if _is_link_like(current, current_stat):
                raise ValueError(f"{label} has a link-like parent")
            if not stat.S_ISDIR(current_stat.st_mode):
                raise ValueError(f"{label} has a non-directory parent")

    @staticmethod
    def _require_directory(path: Path, label: str) -> None:
        try:
            path_stat = path.lstat()
        except OSError as exc:
            raise ValueError(f"{label} is unavailable") from exc
        if _is_link_like(path, path_stat) or not stat.S_ISDIR(path_stat.st_mode):
            raise ValueError(f"{label} is not a safe directory")
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise ValueError(f"{label} cannot be resolved") from exc
        if resolved != path:
            raise ValueError(f"{label} is not a resolved directory")

    def require_execution_sentinel(self) -> None:
        self._require_directory(self.execution_root, "execution root")
        sentinel = self.execution_root / EXECUTION_ROOT_SENTINEL
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(sentinel, flags)
        except OSError as exc:
            raise ValueError("execution root sentinel is missing or unsafe") from exc
        try:
            sentinel_stat = os.fstat(descriptor)
            path_stat = sentinel.lstat()
            content = os.read(descriptor, len(EXECUTION_ROOT_SENTINEL_CONTENT) + 1)
        finally:
            os.close(descriptor)
        if (
            _is_link_like(sentinel, path_stat)
            or not stat.S_ISREG(sentinel_stat.st_mode)
            or sentinel_stat.st_nlink != 1
            or sentinel_stat.st_dev != path_stat.st_dev
            or sentinel_stat.st_ino != path_stat.st_ino
            or content != EXECUTION_ROOT_SENTINEL_CONTENT
        ):
            raise ValueError("execution root sentinel is missing or unsafe")


@lru_cache(maxsize=1)
def get_formatting_config() -> FormattingConfig:
    config = FormattingConfig(
        root=Path(os.getenv("FORMATTING_ROOT", "/data/formatting")).resolve(),
        execution_root=Path(
            os.getenv("FORMATTING_EXECUTION_ROOT", "/data/formatting-execution")
        ).resolve(),
        exports_root=Path(os.getenv("EXPORTS_ROOT", "/data/exports")).resolve(),
        opencode_url=os.getenv("OPENCODE_INTERNAL_URL", "http://opencode-runtime:4096").rstrip("/"),
        opencode_control_url=os.getenv("OPENCODE_CONTROL_URL", "http://opencode-runtime:4097").rstrip("/"),
        opencode_username=os.getenv("OPENCODE_SERVER_USERNAME", "opencode"),
        opencode_password=os.getenv("OPENCODE_SERVER_PASSWORD", ""),
        default_model=os.getenv("FORMATTING_DEFAULT_MODEL", "openai/gpt-5.6-sol"),
        default_reasoning=os.getenv("FORMATTING_DEFAULT_REASONING", "high"),
        task_timeout_seconds=max(60, int(os.getenv("FORMATTING_TIMEOUT_SECONDS", "7200"))),
        skill_max_archive_bytes=max(1_048_576, int(os.getenv("FORMATTING_SKILL_MAX_ARCHIVE_BYTES", os.getenv("SKILL_MAX_ARCHIVE_BYTES", str(100 * 1024 * 1024))))),
        skill_max_files=max(10, int(os.getenv("FORMATTING_SKILL_MAX_FILES", os.getenv("SKILL_MAX_FILES", "2000")))),
        skill_max_unpacked_bytes=max(1_048_576, int(os.getenv("FORMATTING_SKILL_MAX_UNPACKED_BYTES", os.getenv("SKILL_MAX_UNPACKED_BYTES", str(300 * 1024 * 1024))))),
        output_max_files=max(1, int(os.getenv("FORMATTING_OUTPUT_MAX_FILES", "100"))),
        output_max_total_bytes=max(1_048_576, int(os.getenv("FORMATTING_OUTPUT_MAX_TOTAL_BYTES", str(200 * 1024 * 1024)))),
        output_max_single_file_bytes=max(1_048_576, int(os.getenv("FORMATTING_OUTPUT_MAX_SINGLE_FILE_BYTES", str(100 * 1024 * 1024)))),
        input_max_bytes=max(1_048_576, int(os.getenv("FORMATTING_INPUT_MAX_BYTES", str(20 * 1024 * 1024)))),
        execution_workspace_max_entries=max(10, int(os.getenv("FORMATTING_EXECUTION_WORKSPACE_MAX_ENTRIES", "5000"))),
        execution_workspace_max_bytes=max(1_048_576, int(os.getenv("FORMATTING_EXECUTION_WORKSPACE_MAX_BYTES", str(768 * 1024 * 1024)))),
        docx_max_members=max(10, int(os.getenv("FORMATTING_DOCX_MAX_MEMBERS", "2000"))),
        docx_max_uncompressed_bytes=max(1_048_576, int(os.getenv("FORMATTING_DOCX_MAX_UNCOMPRESSED_BYTES", str(200 * 1024 * 1024)))),
        execution_log_max_bytes=max(1, int(os.getenv("FORMATTING_EXECUTION_LOG_MAX_BYTES", str(20 * 1024 * 1024)))),
        storage_max_bytes=max(1, int(os.getenv("FORMATTING_STORAGE_MAX_BYTES", str(20 * 1024 * 1024 * 1024)))),
    )
    config.ensure_persistent_directories()
    return config
