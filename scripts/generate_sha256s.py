#!/usr/bin/env python3
"""Generate or verify the repository's deterministic SHA-256 manifest."""
from __future__ import annotations

import argparse
import hashlib
import os
import stat
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "SHA256SUMS.txt"

EXCLUDED_DIRECTORIES = {
    ".git",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "coverage",
    "dist",
    "node_modules",
    "venv",
}
EXCLUDED_FILES = {
    "SHA256SUMS.txt",
    ".coverage",
    "auth.json",
}
COOKIE_FILE_SUFFIXES = {"", ".db", ".json", ".sqlite", ".sqlite3", ".txt"}


def is_excluded_directory(name: str) -> bool:
    return name in EXCLUDED_DIRECTORIES or name.startswith(
        ".formatting-integration-backup-"
    )


def is_excluded_file(name: str) -> bool:
    lower_name = name.lower()
    if name in EXCLUDED_FILES or lower_name.startswith(".coverage."):
        return True
    if lower_name.startswith(".env") and not lower_name.endswith(".example"):
        return True
    return "cookie" in lower_name and Path(lower_name).suffix in COOKIE_FILE_SUFFIXES


def repository_files() -> list[tuple[str, Path]]:
    files: list[tuple[str, Path]] = []
    for current, directory_names, file_names in os.walk(ROOT, followlinks=False):
        current_path = Path(current)
        directory_names[:] = [
            name
            for name in directory_names
            if not is_excluded_directory(name)
            and not (current_path / name).is_symlink()
        ]
        for name in file_names:
            path = current_path / name
            if is_excluded_file(name) or path.is_symlink():
                continue
            try:
                mode = path.stat().st_mode
            except OSError as exc:
                raise RuntimeError(f"Cannot inspect {path}: {exc}") from exc
            if not stat.S_ISREG(mode):
                continue
            relative = "./" + path.relative_to(ROOT).as_posix()
            files.append((relative, path))
    return sorted(files, key=lambda item: item[0])


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_bytes() -> tuple[bytes, int]:
    files = repository_files()
    lines = [f"{sha256(path)}  {relative}\n" for relative, path in files]
    return "".join(lines).encode("utf-8"), len(files)


def write_atomically(content: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".SHA256SUMS.", suffix=".tmp", dir=ROOT
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as destination:
            destination.write(content)
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary, MANIFEST)
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify that SHA256SUMS.txt exactly matches the repository",
    )
    args = parser.parse_args()

    expected, file_count = manifest_bytes()
    if args.check:
        try:
            actual = MANIFEST.read_bytes()
        except FileNotFoundError:
            print("SHA256SUMS.txt is missing.")
            return 1
        if actual != expected:
            print("SHA256SUMS.txt does not match the repository.")
            return 1
        print(f"Verified {file_count} files.")
        return 0

    write_atomically(expected)
    print(f"Wrote SHA256SUMS.txt with {file_count} files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
