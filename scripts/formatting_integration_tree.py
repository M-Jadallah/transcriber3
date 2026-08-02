"""Shared fail-closed release-tree rules for formatting integration tools."""
from __future__ import annotations

import os
import re
import stat
from pathlib import Path

COMPOSE_NAME = "docker-compose.yml"
LEGACY_OVERLAY = "docker-compose.formatting.yml"
PROJECT_MARKERS = (
    COMPOSE_NAME,
    "backend/Dockerfile",
    "frontend/Dockerfile",
)
REPARSE_POINT_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class UnsafeTreeObjectError(RuntimeError):
    """Raised when a path boundary contains a link, reparse point, or special file."""


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _object_kind(path: Path, label: str) -> str:
    try:
        details = path.lstat()
    except FileNotFoundError:
        return "missing"
    except OSError as exc:
        raise UnsafeTreeObjectError(f"Cannot lstat {label}: {path}: {exc}") from exc

    if getattr(details, "st_file_attributes", 0) & REPARSE_POINT_ATTRIBUTE:
        raise UnsafeTreeObjectError(f"Refusing reparse point in {label}: {path}")
    if stat.S_ISLNK(details.st_mode):
        raise UnsafeTreeObjectError(f"Refusing symlink or broken link in {label}: {path}")
    if stat.S_ISREG(details.st_mode):
        if details.st_nlink != 1:
            raise UnsafeTreeObjectError(
                f"Refusing hard-linked regular file in {label}: {path}"
            )
        return "file"
    if stat.S_ISDIR(details.st_mode):
        return "directory"
    raise UnsafeTreeObjectError(f"Refusing special filesystem object in {label}: {path}")


def validate_path_boundary(
    root: Path,
    path: Path,
    *,
    expected: frozenset[str] = frozenset({"file", "directory"}),
    allow_missing: bool = False,
    label: str = "path",
) -> tuple[Path, str]:
    """lstat every host/project ancestor and require resolved containment."""
    root = _absolute(root)
    path = _absolute(path)
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise UnsafeTreeObjectError(
            f"Refusing {label} outside its validated boundary {root}: {path}"
        ) from exc

    for ancestor in reversed((root, *root.parents)):
        if _object_kind(ancestor, f"{label} host ancestor") != "directory":
            raise UnsafeTreeObjectError(
                f"Non-directory host ancestor in {label}: {ancestor}"
            )

    current = root
    parts = relative.parts
    for index, part in enumerate(parts):
        current = current / part
        kind = _object_kind(current, label)
        is_leaf = index == len(parts) - 1
        if not is_leaf and kind not in {"directory", "missing"}:
            raise UnsafeTreeObjectError(
                f"Non-directory ancestor in {label}: {current}"
            )
        if not is_leaf and kind == "missing":
            for remainder in parts[index + 1 :]:
                current = current / remainder
                if _object_kind(current, label) != "missing":
                    raise UnsafeTreeObjectError(
                        f"Unexpected object below missing ancestor in {label}: {current}"
                    )
            kind = "missing"
            break

    if not parts:
        kind = "directory"
    if kind == "missing":
        if not allow_missing:
            raise UnsafeTreeObjectError(f"Required {label} is missing: {path}")
    elif kind not in expected:
        raise UnsafeTreeObjectError(
            f"Unsupported {label} object; expected {sorted(expected)}, found {kind}: {path}"
        )

    resolved_root = root.resolve(strict=True)
    resolved_path = path.resolve(strict=False)
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise UnsafeTreeObjectError(
            f"Resolved {label} escapes validated boundary {resolved_root}: {resolved_path}"
        ) from exc
    return path, kind


def validate_regular_tree(root: Path, *, label: str = "tree") -> list[Path]:
    """Reject links/reparse/special objects recursively and return regular files."""
    root, _ = validate_path_boundary(
        root,
        root,
        expected=frozenset({"directory"}),
        label=f"{label} root",
    )
    files: list[Path] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        validate_path_boundary(
            root,
            directory,
            expected=frozenset({"directory"}),
            label=label,
        )
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            raise UnsafeTreeObjectError(f"Cannot scan {label}: {directory}: {exc}") from exc
        for entry in entries:
            path, kind = validate_path_boundary(
                root,
                Path(entry.path),
                expected=frozenset({"file", "directory"}),
                label=label,
            )
            if kind == "directory":
                pending.append(path)
            else:
                files.append(path)
    return sorted(files, key=lambda item: item.relative_to(root).as_posix())

EXCLUDED_NAMES = {
    ".git",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    ".cache",
    "cache",
    ".npm",
    ".yarn",
    ".pnpm-store",
    ".credentials",
    "credentials",
    ".ssh",
    ".kube",
    ".aws",
    ".azure",
    ".terraform",
    ".pulumi",
    ".state",
    ".local-state",
    "local-state",
    ".netrc",
    "_netrc",
    ".npmrc",
    ".pypirc",
    "application_default_credentials.json",
    "docker-config.json",
    "secrets.json",
    "token.json",
    "id_rsa",
    "id_ed25519",
    ".git-credentials",
    "kubeconfig",
    "terraform.tfstate",
    ".ds_store",
    "backup",
    "backups",
    ".backup",
}
LOCAL_SECRET_FILE = re.compile(
    r"(?:[a-z0-9-]+[-_.])*(?:auth(?:entication)?|oauth|credentials?|service[-_.]?account|"
    r"access[-_.]?tokens?|refresh[-_.]?tokens?)"
    r"(?:[-_.][a-z0-9-]+)*\.(?:json|ya?ml|toml|ini|txt|db|sqlite3?)\Z",
    re.IGNORECASE,
)
COOKIE_FILE = re.compile(
    r"(?:.*cookies?(?:[-_][a-z0-9-]+)*|"
    r".*cookies?(?:[-_.][a-z0-9-]+)*\.(?:json|txt|db|sqlite3?))\Z",
    re.IGNORECASE,
)
PRIVATE_KEY_OR_CERT_SUFFIXES = {
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".p7b",
    ".p7c",
    ".jks",
    ".keystore",
    ".crt",
    ".cer",
    ".der",
    ".csr",
    ".ppk",
}
LOCAL_STATE_SUFFIXES = {
    ".db",
    ".db-shm",
    ".db-wal",
    ".sqlite",
    ".sqlite3",
    ".mdb",
    ".rdb",
    ".aof",
    ".state",
    ".pid",
    ".sock",
}
SUSPICIOUS_SECRET_STEM = re.compile(
    r"(?:.*[-_.])?(?:client[-_.]?secret|private[-_.]?key|password|passwd|secret|"
    r"token|credentials?)(?:[-_.].*)?\Z",
    re.IGNORECASE,
)
SUSPICIOUS_SECRET_SUFFIXES = {
    ".bin",
    ".conf",
    ".config",
    ".dat",
    ".ini",
    ".json",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}


def discover_project_root(script_path: Path) -> Path:
    """Find exactly one canonical project root among the script's ancestors."""
    candidates = [
        candidate
        for candidate in script_path.resolve().parents
        if all((candidate / marker).is_file() for marker in PROJECT_MARKERS)
    ]
    if not candidates:
        raise RuntimeError(
            "Cannot locate project root: expected docker-compose.yml plus "
            "backend/Dockerfile and frontend/Dockerfile in one ancestor"
        )
    if len(candidates) != 1:
        raise RuntimeError(
            "Ambiguous project root: multiple ancestors contain canonical Compose "
            "and backend/frontend markers: "
            + ", ".join(str(candidate) for candidate in candidates)
        )
    return candidates[0]


def legacy_overlay_paths(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.name.casefold() == LEGACY_OVERLAY
    )


def suspicious_secret_like(relative: Path) -> bool:
    name = relative.name.casefold()
    path = Path(name)
    return (
        path.suffix in SUSPICIOUS_SECRET_SUFFIXES
        and bool(SUSPICIOUS_SECRET_STEM.fullmatch(path.stem))
    )


def prohibited_tree_reason(relative: Path) -> str | None:
    lowered_parts = tuple(part.casefold() for part in relative.parts)
    name = relative.name.casefold()
    if name == LEGACY_OVERLAY:
        return "legacy formatting Compose overlay"
    if any(part.startswith(".formatting-integration-backup-") for part in lowered_parts):
        return "formatting integration recovery backup"
    if name.startswith(".env") and not re.fullmatch(
        r"\.env(?:\.[a-z0-9][a-z0-9._-]*)?\.(?:example|sample|template)",
        name,
    ):
        return "non-template environment file"
    if name == "kubeconfig" or name.startswith("kubeconfig."):
        return "Kubernetes credentials"
    if len(lowered_parts) >= 2 and lowered_parts[-2:] == (".docker", "config.json"):
        return "Docker credentials"
    if "gcloud" in lowered_parts and ".config" in lowered_parts:
        return "Google Cloud local credentials/state"
    if any(part in EXCLUDED_NAMES for part in lowered_parts):
        return "credential, cache, backup, dependency, or local-state path"
    if LOCAL_SECRET_FILE.fullmatch(name) or COOKIE_FILE.fullmatch(name):
        return "authentication, credential, token, or cookie file"
    if Path(name).suffix.casefold() in PRIVATE_KEY_OR_CERT_SUFFIXES:
        return "key or certificate file"
    if any(name.endswith(suffix) for suffix in LOCAL_STATE_SUFFIXES):
        return "local database, socket, process, or state file"
    if name.endswith(
        (
            ".pyc",
            ".pyo",
            ".bak",
            ".backup",
            ".old",
            ".orig",
            ".save",
            ".swp",
            "~",
        )
    ):
        return "cache, editor, or backup file"
    if suspicious_secret_like(relative):
        return "suspicious secret-like file"
    return None
