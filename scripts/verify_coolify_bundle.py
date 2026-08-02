from __future__ import annotations

import re
import stat
import sys
from pathlib import Path
from typing import Any

import yaml
from yaml.nodes import MappingNode

if __package__:
    from scripts.formatting_integration_tree import (
        COMPOSE_NAME,
        UnsafeTreeObjectError,
        discover_project_root,
        prohibited_tree_reason,
        validate_regular_tree,
    )
else:  # Direct execution from scripts/ or copied tools/formatting-integration/.
    from formatting_integration_tree import (
        COMPOSE_NAME,
        UnsafeTreeObjectError,
        discover_project_root,
        prohibited_tree_reason,
        validate_regular_tree,
    )

SCRIPT_PATH = Path(__file__).resolve()
ROOT = discover_project_root(SCRIPT_PATH)
BACKEND_DOCKERFILE = "backend/Dockerfile"
FRONTEND_DOCKERFILE = "frontend/Dockerfile"
FRONTEND_NGINX_CONF = "frontend/nginx.conf"
MIGRATION_NAME = "20260801_0100_add_formatting_subsystem.py"
MIGRATION_PLACEHOLDER = "REPLACE_WITH_CURRENT_HEAD"
EXPECTED_SERVICE_COUNT = 16
CANONICAL_TOP_LEVEL_KEYS = {
    "x-logging",
    "x-data-environment",
    "x-transcription-environment",
    "x-backend-common",
    "x-transcription-volumes",
    "x-worker-healthcheck",
    "services",
    "volumes",
    "networks",
}

REQUIRED_MAGIC = {
    "SERVICE_PASSWORD_64_POSTGRES",
    "SERVICE_PASSWORD_64_ADMIN",
    "SERVICE_HEX_128_SESSION",
    "SERVICE_PASSWORD_64_OPENCODE",
    "SERVICE_PASSWORD_64_REDIS",
}
REQUIRED_SERVICES = {
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
REQUIRED_NETWORKS = {
    "edge",
    "gateway",
    "data",
    "formatting-control",
    "formatting-egress",
    "transcription-egress",
}
REQUIRED_VOLUMES = {
    "postgres-data",
    "redis-data",
    "audio-data",
    "exports-data",
    "youtube-config",
    "formatting-data",
    "formatting-jobs-data",
    "formatting-execution-exchange",
    "opencode-data",
}
INIT_ROOT_SERVICES = {"storage-init", "formatting-storage-init"}
NO_NEW_PRIVILEGES_SERVICES = REQUIRED_SERVICES - {"postgres"}
CAP_DROP_ALL_SERVICES = REQUIRED_SERVICES - INIT_ROOT_SERVICES - {"postgres"}
GATEWAY_CAPABILITIES = {
    "CHOWN",
    "DAC_OVERRIDE",
    "NET_BIND_SERVICE",
    "SETGID",
    "SETUID",
}
FORBIDDEN_RUNTIME_OVERRIDE_KEYS = {
    "blkio_config",
    "cgroup",
    "cgroup_parent",
    "credential_spec",
    "configs",
    "deploy",
    "device_cgroup_rules",
    "devices",
    "develop",
    "entrypoint",
    "env_file",
    "extends",
    "external_links",
    "extra_hosts",
    "gpus",
    "group_add",
    "ipc",
    "isolation",
    "links",
    "pid",
    "post_start",
    "pre_stop",
    "privileged",
    "profiles",
    "runtime",
    "scale",
    "secrets",
    "sysctls",
    "use_api_socket",
    "userns_mode",
    "uts",
    "volumes_from",
}
EXPECTED_NETWORK_MEMBERSHIPS = {
    "storage-init": set(),
    "formatting-storage-init": set(),
    "postgres": {"data"},
    "redis": {"data"},
    "migrate": {"data"},
    "api": {"gateway", "data", "formatting-control"},
    "worker-1": {"data", "transcription-egress"},
    "worker-2": {"data", "transcription-egress"},
    "worker-3": {"data", "transcription-egress"},
    "worker-4": {"data", "transcription-egress"},
    "worker-5": {"data", "transcription-egress"},
    "scheduler": {"data"},
    "opencode-runtime": {"formatting-control", "formatting-egress"},
    "formatting-worker": {"data", "formatting-control"},
    "formatting-dispatcher": {"data"},
    "gateway": {"edge", "gateway"},
}
EXPECTED_SERVICE_MOUNTS = {
    "storage-init": {
        ("audio-data", "/data/audio"),
        ("exports-data", "/data/exports"),
        ("youtube-config", "/data/youtube"),
    },
    "formatting-storage-init": {
        ("formatting-data", "/data/formatting"),
        ("formatting-jobs-data", "/data/formatting/jobs"),
        ("formatting-execution-exchange", "/data/formatting-execution"),
        ("opencode-data", "/data/opencode/data"),
    },
    "postgres": {("postgres-data", "/var/lib/postgresql/data")},
    "redis": {("redis-data", "/data")},
    "migrate": set(),
    "api": {
        ("audio-data", "/data/audio"),
        ("exports-data", "/data/exports"),
        ("youtube-config", "/data/youtube"),
        ("formatting-data", "/data/formatting"),
        ("formatting-jobs-data", "/data/formatting/jobs"),
    },
    "worker-1": {
        ("audio-data", "/data/audio"),
        ("exports-data", "/data/exports"),
        ("youtube-config", "/data/youtube"),
    },
    "worker-2": {
        ("audio-data", "/data/audio"),
        ("exports-data", "/data/exports"),
        ("youtube-config", "/data/youtube"),
    },
    "worker-3": {
        ("audio-data", "/data/audio"),
        ("exports-data", "/data/exports"),
        ("youtube-config", "/data/youtube"),
    },
    "worker-4": {
        ("audio-data", "/data/audio"),
        ("exports-data", "/data/exports"),
        ("youtube-config", "/data/youtube"),
    },
    "worker-5": {
        ("audio-data", "/data/audio"),
        ("exports-data", "/data/exports"),
        ("youtube-config", "/data/youtube"),
    },
    "scheduler": {
        ("audio-data", "/data/audio"),
        ("exports-data", "/data/exports"),
        ("youtube-config", "/data/youtube"),
    },
    "opencode-runtime": {
        ("opencode-data", "/data/opencode/data"),
        ("formatting-execution-exchange", "/data/formatting-execution"),
    },
    "formatting-worker": {
        ("formatting-data", "/data/formatting"),
        ("formatting-jobs-data", "/data/formatting/jobs"),
        ("formatting-execution-exchange", "/data/formatting-execution"),
    },
    "formatting-dispatcher": {
        ("formatting-execution-exchange", "/data/formatting-execution"),
    },
    "gateway": set(),
}
ONE_SHOT_SERVICES = {"storage-init", "formatting-storage-init", "migrate"}
LONG_RUNNING_SERVICES = REQUIRED_SERVICES - ONE_SHOT_SERVICES
EXPECTED_SECRET_RECIPIENTS = {
    "SERVICE_PASSWORD_64_POSTGRES": {
        "postgres",
        "migrate",
        "api",
        "worker-1",
        "worker-2",
        "worker-3",
        "worker-4",
        "worker-5",
        "scheduler",
        "formatting-worker",
        "formatting-dispatcher",
    },
    "SERVICE_PASSWORD_64_REDIS": {
        "redis",
        "api",
        "worker-1",
        "worker-2",
        "worker-3",
        "worker-4",
        "worker-5",
        "scheduler",
        "formatting-worker",
        "formatting-dispatcher",
    },
    "SERVICE_PASSWORD_64_ADMIN": {"api"},
    "SERVICE_HEX_128_SESSION": {"api"},
    "SERVICE_PASSWORD_64_OPENCODE": {
        "api",
        "opencode-runtime",
        "formatting-worker",
    },
}
EXPECTED_SECRET_PLACEMENTS = {
    "SERVICE_PASSWORD_64_POSTGRES": {
        ("postgres", "POSTGRES_PASSWORD"): "${SERVICE_PASSWORD_64_POSTGRES}",
        **{
            (service, "DATABASE_URL"): (
                "postgresql+psycopg://${POSTGRES_USER:-youtube_transcriber}:"
                "${SERVICE_PASSWORD_64_POSTGRES}@postgres:5432/"
                "${POSTGRES_DB:-youtube_transcriber}"
            )
            for service in EXPECTED_SECRET_RECIPIENTS["SERVICE_PASSWORD_64_POSTGRES"]
            - {"postgres"}
        },
    },
    "SERVICE_PASSWORD_64_REDIS": {
        ("redis", "REDIS_PASSWORD"): "${SERVICE_PASSWORD_64_REDIS}",
        **{
            (service, "REDIS_URL"): "redis://:${SERVICE_PASSWORD_64_REDIS}@redis:6379/0"
            for service in EXPECTED_SECRET_RECIPIENTS["SERVICE_PASSWORD_64_REDIS"]
            - {"redis"}
        },
    },
    "SERVICE_PASSWORD_64_ADMIN": {
        ("api", "ADMIN_PASSWORD"): "${SERVICE_PASSWORD_64_ADMIN}",
    },
    "SERVICE_HEX_128_SESSION": {
        ("api", "SESSION_SECRET"): "${SERVICE_HEX_128_SESSION}",
    },
    "SERVICE_PASSWORD_64_OPENCODE": {
        (service, "OPENCODE_SERVER_PASSWORD"): "${SERVICE_PASSWORD_64_OPENCODE}"
        for service in EXPECTED_SECRET_RECIPIENTS["SERVICE_PASSWORD_64_OPENCODE"]
    },
}
EXPECTED_DEPENDENCIES = {
    "storage-init": {},
    "formatting-storage-init": {},
    "postgres": {},
    "redis": {},
    "migrate": {"postgres": "service_healthy"},
    "api": {
        "storage-init": "service_completed_successfully",
        "formatting-storage-init": "service_completed_successfully",
        "migrate": "service_completed_successfully",
        "postgres": "service_healthy",
        "redis": "service_healthy",
    },
    **{
        f"worker-{worker_number}": {
            "storage-init": "service_completed_successfully",
            "migrate": "service_completed_successfully",
            "postgres": "service_healthy",
            "redis": "service_healthy",
        }
        for worker_number in range(1, 6)
    },
    "scheduler": {
        "storage-init": "service_completed_successfully",
        "migrate": "service_completed_successfully",
        "postgres": "service_healthy",
        "redis": "service_healthy",
    },
    "opencode-runtime": {
        "formatting-storage-init": "service_completed_successfully",
    },
    "formatting-worker": {
        "formatting-storage-init": "service_completed_successfully",
        "migrate": "service_completed_successfully",
        "postgres": "service_healthy",
        "redis": "service_healthy",
        "opencode-runtime": "service_healthy",
    },
    "formatting-dispatcher": {
        "formatting-storage-init": "service_completed_successfully",
        "migrate": "service_completed_successfully",
        "postgres": "service_healthy",
        "redis": "service_healthy",
    },
    "gateway": {"api": "service_healthy"},
}
EXPECTED_FORMATTING_LIMITS = {
    "FORMATTING_INPUT_MAX_BYTES": "${FORMATTING_INPUT_MAX_BYTES:-20971520}",
    "FORMATTING_STORAGE_MAX_BYTES": "${FORMATTING_STORAGE_MAX_BYTES:-21474836480}",
}
COMPOSE_DIRECT_MODULES = {
    "migrate": ("app.db_wait", "backend/app/db_wait.py"),
    "api": ("app.main:app", "backend/app/main.py"),
    "worker-1": ("app.celery_app", "backend/app/celery_app.py"),
    "worker-2": ("app.celery_app", "backend/app/celery_app.py"),
    "worker-3": ("app.celery_app", "backend/app/celery_app.py"),
    "worker-4": ("app.celery_app", "backend/app/celery_app.py"),
    "worker-5": ("app.celery_app", "backend/app/celery_app.py"),
    "scheduler": ("app.scheduler", "backend/app/scheduler.py"),
    "opencode-runtime": (
        "app.formatting.opencode_control",
        "backend/app/formatting/opencode_control.py",
    ),
    "formatting-worker": (
        "app.formatting.celery_bootstrap:celery_app",
        "backend/app/formatting/celery_bootstrap.py",
    ),
    "formatting-dispatcher": (
        "app.formatting.outbox_dispatcher",
        "backend/app/formatting/outbox_dispatcher.py",
    ),
}
EXPECTED_BUILD_DOCKERFILES = {
    "migrate": "backend/Dockerfile",
    "api": "backend/Dockerfile",
    "worker-1": "backend/Dockerfile",
    "worker-2": "backend/Dockerfile",
    "worker-3": "backend/Dockerfile",
    "worker-4": "backend/Dockerfile",
    "worker-5": "backend/Dockerfile",
    "scheduler": "backend/Dockerfile",
    "formatting-dispatcher": "backend/Dockerfile",
    "opencode-runtime": "backend/Dockerfile.formatting",
    "formatting-worker": "backend/Dockerfile.formatting",
    "gateway": "frontend/Dockerfile",
}
EXPECTED_BUILD_ARGS = {
    "opencode-runtime": {"OPENCODE_VERSION": "${OPENCODE_VERSION:-1.18.8}"},
    "formatting-worker": {"OPENCODE_VERSION": "${OPENCODE_VERSION:-1.18.8}"},
}
EXPECTED_IMAGE_SERVICES = {
    "storage-init": "alpine:3.22",
    "formatting-storage-init": "alpine:3.22",
    "postgres": "postgres:17-alpine",
    "redis": "redis:8-alpine",
}

# These are original application/build inputs, not merely formatting additions.
# Requiring them prevents an integration-only artifact from passing release checks.
REQUIRED_SOURCE_FILES = {
    "backend/Dockerfile",
    "backend/Dockerfile.formatting",
    "backend/requirements.txt",
    "backend/requirements-formatting.txt",
    "backend/alembic.ini",
    "backend/alembic/env.py",
    "backend/alembic/script.py.mako",
    "backend/app/main.py",
    "backend/app/celery_app.py",
    "backend/app/db_wait.py",
    "backend/app/scheduler.py",
    "backend/app/core/db.py",
    "backend/app/core/models.py",
    "backend/app/core/security.py",
    "backend/app/services/export_service.py",
    "backend/app/services/log_service.py",
    "backend/app/api/formatting.py",
    "backend/app/formatting/__init__.py",
    "backend/app/formatting/celery_bootstrap.py",
    "backend/app/formatting/config.py",
    "backend/app/formatting/opencode_client.py",
    "backend/app/formatting/opencode_control.py",
    "backend/app/formatting/repository.py",
    "backend/app/formatting/runtime.py",
    "backend/app/formatting/skills.py",
    "backend/app/formatting/tasks.py",
    "backend/app/formatting/outbox_dispatcher.py",
    "frontend/Dockerfile",
    "frontend/index.html",
    "frontend/package.json",
    "frontend/src/App.tsx",
    "frontend/src/api.ts",
    "frontend/src/hooks/useFetch.ts",
    "frontend/src/pages/Jobs.tsx",
    "frontend/src/pages/Skills.tsx",
    "tools/formatting-integration/apply_formatting_integration.py",
    "tools/formatting-integration/build_full_source_from_original.py",
    "tools/formatting-integration/formatting_integration_tree.py",
    "tools/formatting-integration/verify_coolify_bundle.py",
}
FRONTEND_LOCKFILES = (
    "frontend/pnpm-lock.yaml",
    "frontend/yarn.lock",
    "frontend/package-lock.json",
)
GENERATED_TREE_NAMES = {
    ".coverage",
    ".eggs",
    ".eslintcache",
    ".hypothesis",
    ".idea",
    ".next",
    ".nuxt",
    ".nyc_output",
    ".parcel-cache",
    ".stylelintcache",
    ".svelte-kit",
    ".turbo",
    ".venv",
    ".vite",
    ".vscode",
    "build",
    "coverage.xml",
    "desktop.ini",
    "dist",
    "htmlcov",
    "out",
    "target",
    "temp",
    "thumbs.db",
    "tmp",
    "venv",
}
GENERATED_TREE_SUFFIXES = (".log", ".swo", ".temp", ".tmp")


def _generated_tree_reason(relative: Path) -> str | None:
    lowered_parts = tuple(part.casefold() for part in relative.parts)
    if any(part in GENERATED_TREE_NAMES for part in lowered_parts):
        return "generated cache, build output, package metadata, or editor state"
    if any(part.endswith(".egg-info") for part in lowered_parts):
        return "generated Python package metadata"
    if relative.name.casefold().endswith(GENERATED_TREE_SUFFIXES):
        return "generated cache, temporary, log, or editor file"
    return None


def _revision_value(text: str, key: str) -> str | None:
    assignments = re.findall(
        rf"^\s*{re.escape(key)}\s*(?::[^=]+)?=",
        text,
        re.MULTILINE,
    )
    if len(assignments) != 1:
        return None
    match = re.search(
        rf"^\s*{re.escape(key)}\s*(?::[^=]+)?=\s*"
        rf"(['\"])([^'\"]+)\1\s*(?:#.*)?$",
        text,
        re.MULTILINE,
    )
    return match.group(2) if match else None


def _revision_collection(text: str, key: str) -> set[str]:
    assignments = re.findall(
        rf"^\s*{re.escape(key)}\s*(?::[^=]+)?=",
        text,
        re.MULTILINE,
    )
    if len(assignments) != 1:
        raise ValueError(f"{key} must have exactly one assignment")
    value = _revision_value(text, key)
    if value:
        return {value}
    if re.search(
        rf"^\s*{re.escape(key)}\s*(?::[^=]+)?=\s*None\s*(?:#.*)?$",
        text,
        re.MULTILINE,
    ):
        return set()
    collection_match = re.search(
        rf"^\s*{re.escape(key)}\s*(?::[^=]+)?=\s*"
        r"(?:\[(.*?)\]|\((.*?)\))\s*(?:#.*)?$",
        text,
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


def _down_revisions(text: str) -> set[str]:
    return _revision_collection(text, "down_revision")


def _dependencies(text: str) -> set[str]:
    if not re.search(
        r"^\s*depends_on\s*(?::[^=]+)?=",
        text,
        re.MULTILINE,
    ):
        return set()
    return _revision_collection(text, "depends_on")


def _migration_cycle(parents: dict[str, set[str]]) -> str | None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(revision: str) -> str | None:
        if revision in visiting:
            return revision
        if revision in visited:
            return None
        visiting.add(revision)
        for parent in parents[revision]:
            cycle = visit(parent)
            if cycle:
                return cycle
        visiting.remove(revision)
        visited.add(revision)
        return None

    for revision in parents:
        cycle = visit(revision)
        if cycle:
            return cycle
    return None


def _migration_depends_on(
    revision: str,
    ancestor: str,
    parents: dict[str, set[str]],
) -> bool:
    return ancestor in parents[revision] or any(
        _migration_depends_on(parent, ancestor, parents)
        for parent in parents[revision]
    )


def _validate_migrations(root: Path) -> list[str]:
    errors: list[str] = []
    versions = root / "backend/alembic/versions"
    migration = versions / MIGRATION_NAME
    if not migration.is_file():
        return [f"Missing formatting migration: backend/alembic/versions/{MIGRATION_NAME}"]

    migration_text = migration.read_text(encoding="utf-8", errors="replace")
    if _revision_value(migration_text, "revision") != "20260801_0100":
        errors.append("Formatting migration has an invalid reserved revision ID")
    if MIGRATION_PLACEHOLDER in migration_text:
        errors.append("Formatting migration still contains the Alembic head placeholder")
    if _revision_value(migration_text, "down_revision") is None:
        errors.append("Formatting migration has no resolved down_revision")
    migration_markers = {
        'sa.Column("execution_generation"': "execution_generation column",
        '"execution_generation >= 0"': "nonnegative execution_generation constraint",
        '"ix_formatting_jobs_recovery"': "formatting job recovery index",
        '"ix_formatting_jobs_queued_reconcile"': "queued reconciliation index",
    }
    for marker, label in migration_markers.items():
        if marker not in migration_text:
            errors.append(f"Formatting migration is missing its {label}")

    revision_files: dict[str, list[str]] = {}
    down_parents: dict[str, set[str]] = {}
    graph_parents: dict[str, set[str]] = {}
    for path in sorted(versions.glob("*.py")):
        if path.name == "__init__.py":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        revision = _revision_value(text, "revision")
        if not revision:
            errors.append(f"Unparsable Alembic migration revision: {path.name}")
            continue
        revision_files.setdefault(revision, []).append(path.name)
        try:
            down_parents[revision] = _down_revisions(text)
        except ValueError:
            errors.append(f"Unparsable Alembic down_revision: {path.name}")
            down_parents[revision] = set()
        try:
            dependencies = _dependencies(text)
        except ValueError:
            errors.append(f"Unparsable Alembic depends_on: {path.name}")
            dependencies = set()
        graph_parents[revision] = down_parents[revision] | dependencies

    for revision, files in sorted(revision_files.items()):
        if len(files) > 1:
            errors.append(f"Duplicate Alembic revision: {revision} ({', '.join(files)})")

    revisions = set(graph_parents)
    referenced = set().union(*graph_parents.values()) if graph_parents else set()
    dangling = sorted(referenced - revisions)
    if dangling:
        errors.append(f"Dangling Alembic down_revision/depends_on references: {dangling}")
    if not dangling:
        cycle = _migration_cycle(graph_parents)
        if cycle:
            errors.append(f"Alembic revision cycle detected at: {cycle}")

    if not dangling and not _migration_cycle(graph_parents):
        descendants = sorted(
            revision
            for revision in graph_parents
            if revision != "20260801_0100"
            and _migration_depends_on(revision, "20260801_0100", graph_parents)
        )
        if descendants:
            errors.append(
                "Later Alembic revisions depend on the formatting revision: "
                + ", ".join(descendants)
            )

    down_referenced = (
        set().union(*down_parents.values()) if down_parents else set()
    )
    heads = sorted(revisions - down_referenced)
    if heads != ["20260801_0100"]:
        errors.append(f"Expected one Alembic head (20260801_0100), found: {heads or 'none'}")
    if len(revisions) < 2:
        errors.append("Original Alembic history is missing; only the formatting migration is present")
    return errors


def _validate_builds(root: Path, services: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for service_name, expected_dockerfile in EXPECTED_BUILD_DOCKERFILES.items():
        service = services.get(service_name)
        if not isinstance(service, dict):
            errors.append(f"Locally built service {service_name} must be a mapping")
            continue
        if "image" in service:
            errors.append(f"Locally built service {service_name} must not define image")
        build = service.get("build")
        if not isinstance(build, dict):
            errors.append(
                f"Locally built service {service_name} must use the canonical build mapping"
            )
            continue
        expected_args = EXPECTED_BUILD_ARGS.get(service_name)
        expected_keys = {"context", "dockerfile"}
        if expected_args is not None:
            expected_keys.add("args")
        if set(build) != expected_keys:
            errors.append(
                f"Service {service_name} build keys must be exactly: "
                + ", ".join(sorted(expected_keys))
            )
        if build.get("context") != ".":
            errors.append(f"Service {service_name} build context must be exactly .")
        if build.get("dockerfile") != expected_dockerfile:
            errors.append(f"Service {service_name} must build with {expected_dockerfile}")
        if expected_args is not None and build.get("args") != expected_args:
            errors.append(f"Service {service_name} build args must match the canonical matrix")

    for service_name, expected_image in EXPECTED_IMAGE_SERVICES.items():
        service = services.get(service_name)
        if not isinstance(service, dict):
            errors.append(f"Image-only service {service_name} must be a mapping")
            continue
        if "build" in service:
            errors.append(f"Image-only service {service_name} must not define build")
        if service.get("image") != expected_image:
            errors.append(
                f"Image-only service {service_name} image must be exactly {expected_image}"
            )

    matrix_services = set(EXPECTED_BUILD_DOCKERFILES) | set(EXPECTED_IMAGE_SERVICES)
    for service_name, service in services.items():
        if not isinstance(service, dict) or service_name in matrix_services:
            continue
        if "build" in service or "image" in service:
            errors.append(f"Service {service_name} has an unexpected build/image definition")
    return errors


def _volume_pairs(service: Any) -> set[tuple[str, str]]:
    if not isinstance(service, dict):
        return set()
    pairs: set[tuple[str, str]] = set()
    for mount in service.get("volumes", []):
        if isinstance(mount, str):
            parts = mount.split(":", 2)
            if len(parts) >= 2:
                pairs.add((parts[0], parts[1]))
        elif isinstance(mount, dict):
            source = mount.get("source")
            target = mount.get("target")
            if isinstance(source, str) and isinstance(target, str):
                pairs.add((source, target))
    return pairs


def _tmpfs_covers(service: Any, path: str) -> bool:
    if not isinstance(service, dict):
        return False
    for mount in service.get("tmpfs", []):
        if isinstance(mount, str):
            target = mount.split(":", 1)[0].rstrip("/")
        elif isinstance(mount, dict):
            target = str(mount.get("target", "")).rstrip("/")
        else:
            continue
        if target and (path == target or path.startswith(target + "/")):
            return True
    return False


def _tmpfs_targets(service: Any) -> set[str]:
    if not isinstance(service, dict):
        return set()
    targets: set[str] = set()
    for mount in service.get("tmpfs", []):
        if isinstance(mount, str):
            target = mount.split(":", 1)[0]
        elif isinstance(mount, dict):
            target = mount.get("target")
        else:
            continue
        if isinstance(target, str):
            targets.add(target.rstrip("/"))
    return targets


def _environment(service: Any) -> dict[str, Any]:
    if not isinstance(service, dict):
        return {}
    environment = service.get("environment", {})
    return environment if isinstance(environment, dict) else {}


def _command_text(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(str(part) for part in value)
    return str(value)


def _has_exact_networks(service: Any, expected: set[str]) -> bool:
    if not isinstance(service, dict):
        return False
    networks = service.get("networks")
    if not expected:
        return networks is None
    if isinstance(networks, list):
        return (
            len(networks) == len(expected)
            and all(isinstance(name, str) for name in networks)
            and set(networks) == expected
        )
    if isinstance(networks, dict):
        return set(networks) == expected and all(
            configuration is None or isinstance(configuration, dict)
            for configuration in networks.values()
        )
    return False


def _has_exact_mounts(
    service: Any,
    expected: set[tuple[str, str]],
) -> bool:
    if not isinstance(service, dict):
        return False
    mounts = service.get("volumes", [])
    return (
        isinstance(mounts, list)
        and len(mounts) == len(expected)
        and all(
            (isinstance(mount, str) and mount.count(":") == 1)
            or (
                isinstance(mount, dict)
                and mount.get("type") == "volume"
                and set(mount) == {"type", "source", "target"}
            )
            for mount in mounts
        )
        and _volume_pairs(service) == expected
    )


def _is_root_user(value: Any) -> bool:
    if isinstance(value, int):
        return value == 0
    if not isinstance(value, str):
        return False
    account = value.strip().split(":", 1)[0].strip().casefold()
    return account in {"0", "root"}


def _has_host_or_bind_mount(service: dict[str, Any]) -> bool:
    mounts = service.get("volumes", [])
    if not isinstance(mounts, list):
        return True
    for mount in mounts:
        if isinstance(mount, str):
            parts = mount.split(":")
            if len(parts) < 2 or parts[0] not in REQUIRED_VOLUMES:
                return True
        elif isinstance(mount, dict):
            if (
                mount.get("type") != "volume"
                or mount.get("source") not in REQUIRED_VOLUMES
            ):
                return True
        else:
            return True
    return False


def _validate_runtime_overrides(services: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for service_name, service in services.items():
        if not isinstance(service, dict):
            continue

        forbidden = sorted(FORBIDDEN_RUNTIME_OVERRIDE_KEYS & set(service))
        if forbidden:
            errors.append(
                f"{service_name} must not declare forbidden runtime override keys: "
                + ", ".join(forbidden)
            )

        if service_name in INIT_ROOT_SERVICES:
            if service.get("user") != "0:0":
                errors.append(f"{service_name} must use exactly the expected root user 0:0")
            if service.get("network_mode") != "none":
                errors.append(f"{service_name} must use exactly network_mode: none")
        else:
            if "network_mode" in service:
                errors.append(f"{service_name} must not override network_mode")
            if "user" in service and _is_root_user(service.get("user")):
                errors.append(f"{service_name} must not specify a root user")

        capabilities = service.get("cap_add")
        if service_name == "gateway":
            if (
                not isinstance(capabilities, list)
                or len(capabilities) != len(GATEWAY_CAPABILITIES)
                or set(capabilities) != GATEWAY_CAPABILITIES
            ):
                errors.append("gateway cap_add must match the canonical Nginx capability set")
        elif "cap_add" in service:
            errors.append(f"{service_name} must not declare cap_add")

        expected_security_opt = (
            ["no-new-privileges:true"]
            if service_name in NO_NEW_PRIVILEGES_SERVICES
            else None
        )
        if expected_security_opt is not None:
            if service.get("security_opt") != expected_security_opt:
                errors.append(
                    f"{service_name} must enable only no-new-privileges security_opt"
                )
        elif "security_opt" in service:
            errors.append(f"{service_name} must not override security_opt")

        expected_cap_drop = ["ALL"] if service_name in CAP_DROP_ALL_SERVICES else None
        if expected_cap_drop is not None:
            if service.get("cap_drop") != expected_cap_drop:
                errors.append(f"{service_name} must drop all capabilities")
        elif "cap_drop" in service:
            errors.append(f"{service_name} has unexpected cap_drop configuration")

        if service_name == "gateway":
            if service.get("read_only") is not True:
                errors.append("gateway root filesystem must be read-only")
        elif "read_only" in service:
            errors.append(f"{service_name} has unexpected read_only configuration")

        if _has_host_or_bind_mount(service):
            errors.append(f"{service_name} must not use host paths or bind mounts")
    return errors


def _validate_named_volumes(volumes: Any) -> list[str]:
    if not isinstance(volumes, dict) or set(volumes) != REQUIRED_VOLUMES:
        return [
            "Compose volumes must be exactly: "
            + ", ".join(sorted(REQUIRED_VOLUMES))
        ]
    invalid = sorted(
        name
        for name, definition in volumes.items()
        if definition is not None
        and (not isinstance(definition, dict) or bool(definition))
    )
    if invalid:
        return [
            "Named volume definitions must be empty/null mappings only: "
            + ", ".join(invalid)
        ]
    return []


def _validate_compose_document(text: str, data: Any) -> list[str]:
    errors: list[str] = []
    if isinstance(data, dict):
        actual_keys = set(data)
        if actual_keys != CANONICAL_TOP_LEVEL_KEYS:
            missing = sorted(CANONICAL_TOP_LEVEL_KEYS - actual_keys)
            unexpected = sorted(
                actual_keys - CANONICAL_TOP_LEVEL_KEYS,
                key=lambda value: str(value),
            )
            details = []
            if missing:
                details.append("missing: " + ", ".join(missing))
            if unexpected:
                details.append("unexpected: " + ", ".join(map(str, unexpected)))
            errors.append(
                "Compose top-level keys must match the canonical contract ("
                + "; ".join(details)
                + ")"
            )

    try:
        document = yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError:
        return errors
    if isinstance(document, MappingNode) and any(
        key_node.tag == "tag:yaml.org,2002:merge"
        for key_node, _value_node in document.value
    ):
        errors.append("Canonical Compose must not use a top-level YAML merge key")
    return errors


def _interpolation_default(value: Any, variable: str) -> str | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(rf"\$\{{{re.escape(variable)}:-([^}}]+)}}", value)
    return match.group(1) if match else None


def _validate_gateway_network(
    services: dict[str, Any],
    networks: dict[str, Any],
) -> list[str]:
    """Validate the gateway <-> api trust topology.

    Design (after the Coolify IPAM fix):
    -------------------------------------
    The gateway service has NO static ``ipv4_address`` and the ``gateway``
    network has NO IPAM subnet configured. Coolify creates the network with a
    UUID-prefixed name (e.g. ``<resource_uuid>_gateway``) and Docker's IPAM
    auto-assigns the subnet; any static IP pinned in the compose file is
    rejected at runtime with:

        ``no configured subnet contains IP address <X>``

    Trust isolation is provided by:

    1. ``gateway`` network is ``internal: true`` — no external traffic reaches
       the ``api`` service through it.
    2. Only ``gateway`` and ``api`` are attached to the ``gateway`` network.
    3. ``api`` accepts forwarded headers from any peer on that network
       (``FORWARDED_ALLOW_IPS="*"``) — this is the standard uvicorn pattern
       when sitting behind a trusted reverse proxy on an isolated network.
    """
    errors: list[str] = []
    gateway_network = networks.get("gateway")
    if not isinstance(gateway_network, dict):
        return ["gateway network configuration must be a mapping"]

    # The gateway network MUST be internal-only — this is the trust boundary.
    if gateway_network.get("internal") is not True:
        errors.append("gateway network must be internal:true (trust isolation boundary)")

    # The gateway network MUST NOT declare a static IPAM subnet: Coolify
    # creates its own UUID-prefixed network and ignores the configured subnet,
    # which previously caused "no configured subnet contains IP address <X>".
    if "ipam" in gateway_network:
        errors.append(
            "gateway network must not declare IPAM config (Coolify auto-assigns subnet)"
        )

    gateway = services.get("gateway", {})
    memberships = gateway.get("networks", {}) if isinstance(gateway, dict) else {}

    # The gateway service MUST NOT pin a static ipv4_address — Coolify's
    # auto-assigned subnet will reject it.
    gateway_attachment = (
        memberships.get("gateway") if isinstance(memberships, dict) else None
    )
    if isinstance(gateway_attachment, dict) and "ipv4_address" in gateway_attachment:
        errors.append(
            "gateway service must not pin ipv4_address (Coolify ignores the IPAM subnet)"
        )
    if isinstance(memberships, dict) and memberships.get("edge") is not None:
        errors.append("gateway edge attachment must not have static network configuration")

    # No service other than gateway may have a static ipv4_address either.
    for service_name, service in services.items():
        if service_name == "gateway" or not isinstance(service, dict):
            continue
        attachments = service.get("networks")
        if isinstance(attachments, dict) and any(
            isinstance(configuration, dict) and "ipv4_address" in configuration
            for configuration in attachments.values()
        ):
            errors.append(f"no service may declare a static network address ({service_name})")

    api = services.get("api", {})
    api_environment = _environment(api)

    # FORWARDED_ALLOW_IPS must be exactly "*" (trusted-proxy on isolated
    # internal network). Any tighter value would require knowing the gateway's
    # IP, which Coolify does not expose to compose.
    trusted_value = api_environment.get("FORWARDED_ALLOW_IPS")
    if trusted_value != "*":
        errors.append(
            "api FORWARDED_ALLOW_IPS must be exactly '*' "
            "(trusted reverse proxy on isolated internal network)"
        )
    trusted_roles = {
        service_name
        for service_name, service in services.items()
        if "FORWARDED_ALLOW_IPS" in _environment(service)
    }
    if trusted_roles != {"api"}:
        errors.append("FORWARDED_ALLOW_IPS must be configured only for api")

    # The api command MUST still pass --forwarded-allow-ips via the env var,
    # so the same "*" value flows into uvicorn at runtime.
    api_command = _command_text(api.get("command", "") if isinstance(api, dict) else "")
    expected_forwarded = "--forwarded-allow-ips=$${FORWARDED_ALLOW_IPS}"
    if (
        expected_forwarded not in api_command
        or api_command.count("--forwarded-allow-ips=") != 1
    ):
        errors.append("api must pass --forwarded-allow-ips from FORWARDED_ALLOW_IPS env var")

    return errors


def _validate_gateway_hardening(services: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    gateway = services.get("gateway", {})
    if not isinstance(gateway, dict):
        return ["gateway hardening configuration must be a mapping"]
    if gateway.get("security_opt") != ["no-new-privileges:true"]:
        errors.append("gateway must enable only no-new-privileges security_opt")
    if gateway.get("cap_drop") != ["ALL"]:
        errors.append("gateway must drop all capabilities before adding Nginx requirements")
    capabilities = gateway.get("cap_add")
    if (
        not isinstance(capabilities, list)
        or len(capabilities) != len(GATEWAY_CAPABILITIES)
        or set(capabilities) != GATEWAY_CAPABILITIES
    ):
        errors.append("gateway capabilities must be exactly the stock Nginx runtime set")
    if gateway.get("read_only") is not True:
        errors.append("gateway root filesystem must be read-only")
    if _tmpfs_targets(gateway) != {"/tmp", "/var/cache/nginx", "/var/run"}:
        errors.append("gateway tmpfs mounts must be exactly Nginx cache and runtime paths")
    forbidden_keys = {
        "devices",
        "device_cgroup_rules",
        "extra_hosts",
        "group_add",
        "ipc",
        "network_mode",
        "pid",
        "privileged",
    }
    present_forbidden = sorted(forbidden_keys & set(gateway))
    if present_forbidden:
        errors.append(
            "gateway must not declare privilege/host escape options: "
            + ", ".join(present_forbidden)
        )
    return errors


def _validate_proxy_contract(root: Path) -> list[str]:
    errors: list[str] = []
    backend_path = root / BACKEND_DOCKERFILE
    frontend_dockerfile_path = root / FRONTEND_DOCKERFILE
    nginx_path = root / FRONTEND_NGINX_CONF
    if not backend_path.is_file() or not frontend_dockerfile_path.is_file():
        return errors
    if not nginx_path.is_file():
        errors.append("frontend Nginx config (frontend/nginx.conf) is missing")
        return errors

    backend = backend_path.read_text(encoding="utf-8", errors="replace")
    backend_commands = [
        line.strip() for line in backend.splitlines() if line.lstrip().startswith("CMD ")
    ]
    if len(backend_commands) != 1:
        errors.append("backend Dockerfile must have exactly one default CMD")
    else:
        command = backend_commands[0]
        if "--forwarded-allow-ips" in command or '"--proxy-headers"' in command:
            errors.append("backend Dockerfile default CMD must not configure forwarded trust")
        if '"--no-proxy-headers"' not in command:
            errors.append("backend Dockerfile default CMD must disable proxy headers")

    nginx = nginx_path.read_text(encoding="utf-8", errors="replace")
    # Strip nginx comments so that explanatory comments mentioning directive
    # names (e.g. "# the literal form `proxy_pass http://api:8000;`") do not
    # inflate string counts or break regex location-block matching.
    nginx = re.sub(r"#[^\n]*", "", nginx)
    required_directives = {
        "proxy_set_header Host $host;",
        "proxy_set_header X-Real-IP $remote_addr;",
        "proxy_set_header X-Forwarded-For $remote_addr;",
        "proxy_set_header X-Forwarded-Host $host;",
        "proxy_set_header X-Forwarded-Proto $forwarded_proto;",
        "proxy_set_header X-Forwarded-Port $forwarded_port;",
        'proxy_set_header Forwarded "";',
        "server_tokens off;",
    }
    for directive in sorted(required_directives):
        if nginx.count(directive) != 1:
            errors.append(f"frontend Nginx contract requires exactly one: {directive}")
    if "$proxy_add_x_forwarded_for" in nginx or "$http_x_forwarded_for" in nginx:
        errors.append("frontend Nginx must not append or reuse incoming X-Forwarded-For")
    api_locations = re.findall(r"location\s+\^~\s+/api/\s*\{(.*?)\n\s*\}", nginx, re.DOTALL)
    if len(api_locations) != 1:
        errors.append("frontend Nginx must define exactly one prefix-locked /api/ location")
    else:
        api_block = api_locations[0]
        # Two acceptable forms:
        #   1. Literal:   proxy_pass http://api:8000;
        #   2. Deferred:  set $api_upstream "api:8000"; proxy_pass http://$api_upstream;
        # Form (2) is required for `nginx -t` to pass at image build time, because
        # the "api" service hostname is only resolvable inside the Compose network
        # at runtime. When form (2) is used, a `resolver` directive must also be
        # present so nginx can resolve the variable at request time.
        literal_pass = api_block.count("proxy_pass http://api:8000;")
        variable_pass = (
            'set $api_upstream "api:8000";' in api_block
            and re.search(r"proxy_pass\s+http://\$api_upstream\s*;", api_block) is not None
        )
        if literal_pass + variable_pass != 1:
            errors.append(
                "frontend Nginx /api/ must proxy exactly to api:8000 (literal form "
                "`proxy_pass http://api:8000;` or deferred form via $api_upstream "
                "variable for build-time DNS resolution)"
            )
        if variable_pass and "resolver 127.0.0.11" not in nginx:
            errors.append(
                "frontend Nginx must declare `resolver 127.0.0.11` when using the "
                "$api_upstream deferred-resolution form"
            )
    if nginx.count("proxy_pass") != 1:
        errors.append("frontend Nginx must not define proxy_pass outside the /api/ contract")
    if re.search(r"location\s+(?:=\s*)?/api(?:\s|\{)", nginx):
        errors.append("frontend Nginx must not define an ambiguous bare /api location")
    # Match the hidden-path deny block with flexible whitespace/indentation,
    # since the block is nested inside `server {` and its absolute indentation
    # depth depends on the surrounding context.
    hidden_path_pattern = re.compile(
        r"location\s+~\s*/\\\.\(\?!well-known/\)\s*\{\s*deny\s+all;\s*\}",
        re.DOTALL,
    )
    if not hidden_path_pattern.search(nginx):
        errors.append("frontend Nginx must deny hidden paths except /.well-known/")
    constrained_scheme_map = re.compile(
        r"map\s+\$http_x_forwarded_proto\s+\$forwarded_proto\s*\{\s*"
        r"default\s+\$scheme;\s*http\s+http;\s*https\s+https;\s*\}",
        re.DOTALL,
    )
    if not constrained_scheme_map.search(nginx):
        errors.append("frontend Nginx scheme map must allow only exact http/https values")
    constrained_port_map = re.compile(
        r"map\s+\$forwarded_proto\s+\$forwarded_port\s*\{\s*"
        r"default\s+80;\s*https\s+443;\s*\}",
        re.DOTALL,
    )
    if not constrained_port_map.search(nginx):
        errors.append("frontend Nginx forwarded port must derive only from sanitized scheme")
    return errors


def _validate_dependencies(services: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for service_name, expected in EXPECTED_DEPENDENCIES.items():
        service = services.get(service_name, {})
        actual = service.get("depends_on") if isinstance(service, dict) else None
        if not expected:
            if actual not in (None, {}):
                errors.append(f"{service_name} must not declare dependencies")
            continue
        if not isinstance(actual, dict) or set(actual) != set(expected):
            errors.append(
                f"{service_name} dependencies must be exactly: "
                + ", ".join(expected)
            )
            continue
        for dependency, condition in expected.items():
            definition = actual.get(dependency)
            if not isinstance(definition, dict) or definition != {"condition": condition}:
                errors.append(
                    f"{service_name} must wait for {dependency} with {condition}"
                )
    return errors


def _validate_formatting_limits(services: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    expected_roles = {"api", "formatting-worker"}
    for variable, expected_value in EXPECTED_FORMATTING_LIMITS.items():
        actual_roles = {
            service_name
            for service_name, service in services.items()
            if variable in _environment(service)
        }
        if actual_roles != expected_roles:
            errors.append(
                f"{variable} recipients must be exactly: "
                + ", ".join(sorted(expected_roles))
            )
        for service_name in expected_roles:
            if _environment(services.get(service_name)).get(variable) != expected_value:
                errors.append(f"{service_name} must receive the canonical {variable}")
    return errors


def _validate_redis_authentication(services: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    redis = services.get("redis", {})
    environment = _environment(redis)
    if environment.get("REDIS_PASSWORD") != "${SERVICE_PASSWORD_64_REDIS}":
        errors.append("Redis must receive its generated password through REDIS_PASSWORD")

    command = _command_text(redis.get("command", "") if isinstance(redis, dict) else "")
    if not all(
        marker in command
        for marker in (
            "requirepass %s",
            '"$$REDIS_PASSWORD"',
            "redis-server /tmp/redis.conf",
        )
    ):
        errors.append("Redis command must build and load a password-protected config")

    healthcheck = redis.get("healthcheck", {}) if isinstance(redis, dict) else {}
    health_text = _command_text(
        healthcheck.get("test", "") if isinstance(healthcheck, dict) else ""
    )
    if not all(
        marker in health_text
        for marker in (
            'REDISCLI_AUTH="$$REDIS_PASSWORD"',
            "redis-cli ping",
            "grep -q PONG",
        )
    ):
        errors.append("Redis health check must authenticate with REDIS_PASSWORD")

    expected_url = "redis://:${SERVICE_PASSWORD_64_REDIS}@redis:6379/0"
    redis_clients = {
        "api",
        "worker-1",
        "worker-2",
        "worker-3",
        "worker-4",
        "worker-5",
        "scheduler",
        "formatting-worker",
        "formatting-dispatcher",
    }
    for service_name in sorted(redis_clients):
        if _environment(services.get(service_name)).get("REDIS_URL") != expected_url:
            errors.append(
                f"{service_name} must use the shared authenticated REDIS_URL"
            )
    for service_name, service in services.items():
        configured_url = _environment(service).get("REDIS_URL")
        if configured_url is not None and configured_url != expected_url:
            errors.append(f"{service_name} has an unauthenticated or divergent REDIS_URL")
    return errors


def _validate_secret_distribution(services: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    expected_key_roles: dict[str, set[str]] = {}
    for secret, expected_placements in EXPECTED_SECRET_PLACEMENTS.items():
        actual_placements: dict[tuple[str, str], Any] = {}
        leaked_roles: set[str] = set()
        for service_name, service in services.items():
            environment = _environment(service)
            for key, value in environment.items():
                if secret in str(value):
                    actual_placements[(service_name, key)] = value
            if isinstance(service, dict):
                outside_environment = {
                    key: value for key, value in service.items() if key != "environment"
                }
                if secret in str(outside_environment):
                    leaked_roles.add(service_name)

        if actual_placements != expected_placements:
            errors.append(
                f"{secret} environment key placements must match the exact role matrix"
            )
        if leaked_roles:
            errors.append(
                f"{secret} must not leak outside service environment mappings: "
                + ", ".join(sorted(leaked_roles))
            )

        actual_recipients = {service for service, _key in actual_placements}
        if actual_recipients != EXPECTED_SECRET_RECIPIENTS[secret]:
            errors.append(f"{secret} recipients must match the exact role matrix")
        for service_name, key in expected_placements:
            expected_key_roles.setdefault(key, set()).add(service_name)

    for key, expected_roles in expected_key_roles.items():
        actual_roles = {
            service_name
            for service_name, service in services.items()
            if key in _environment(service)
        }
        if actual_roles != expected_roles:
            errors.append(
                f"Sensitive environment key {key} recipients must be exactly: "
                + ", ".join(sorted(expected_roles))
            )

    for worker_number in range(1, 6):
        service_name = f"worker-{worker_number}"
        variable = f"DEEPGRAM_API_KEY_WORKER_{worker_number}"
        expected_value = f"${{{variable}:?Set worker {worker_number} Deepgram key}}"
        if _environment(services.get(service_name)).get("DEEPGRAM_API_KEY") != expected_value:
            errors.append(f"{service_name} must receive only its dedicated Deepgram key")
        actual_recipients = {
            name for name, service in services.items() if variable in str(service)
        }
        if actual_recipients != {service_name}:
            errors.append(f"{variable} must be distributed only to {service_name}")
    deepgram_key_roles = {
        service_name
        for service_name, service in services.items()
        if "DEEPGRAM_API_KEY" in _environment(service)
    }
    expected_deepgram_roles = {f"worker-{worker_number}" for worker_number in range(1, 6)}
    if deepgram_key_roles != expected_deepgram_roles:
        errors.append("DEEPGRAM_API_KEY environment key recipients must be exactly worker-1..5")

    api_environment = _environment(services.get("api"))
    required_production_values = {
        "APP_URL": "${APP_URL:?Set APP_URL in Coolify}",
        "TRUSTED_HOSTS": "${TRUSTED_HOSTS:?Set the public domain and health-check host}",
        "COOKIE_SECURE": "true",
    }
    for key, expected_value in required_production_values.items():
        if api_environment.get(key) != expected_value:
            errors.append(f"api production environment must set {key} to its secure contract")
    return errors


def _validate_topology(services: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for service_name in sorted(REQUIRED_SERVICES):
        service = services.get(service_name)
        if not isinstance(service, dict):
            continue
        if "ports" in service:
            errors.append(f"{service_name} must not publish host ports")

        expected_networks = EXPECTED_NETWORK_MEMBERSHIPS[service_name]
        if not _has_exact_networks(service, expected_networks):
            errors.append(
                f"{service_name} network membership must be exactly: "
                + (", ".join(sorted(expected_networks)) or "none")
            )
        raw_networks = service.get("networks")
        if expected_networks and not isinstance(raw_networks, (list, dict)):
            errors.append(f"{service_name} networks must be a list or mapping")
        if not expected_networks and "networks" in service:
            errors.append(f"{service_name} must not declare networks")
        if service_name in {"storage-init", "formatting-storage-init"}:
            if service.get("network_mode") != "none":
                errors.append(f"{service_name} must use network_mode: none")
        elif "network_mode" in service:
            errors.append(f"{service_name} must use declared Compose networks")

        if not _has_exact_mounts(service, EXPECTED_SERVICE_MOUNTS[service_name]):
            errors.append(f"{service_name} named-volume mounts do not match the exact matrix")

        expose = service.get("expose")
        if service_name == "gateway":
            if not isinstance(expose, list) or [str(port) for port in expose] != ["80"]:
                errors.append("gateway must expose only container port 80")
        elif "expose" in service:
            errors.append(f"{service_name} must not declare exposed ports")
    return errors


def _validate_healthchecks(services: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for service_name in sorted(ONE_SHOT_SERVICES):
        service = services.get(service_name, {})
        if not isinstance(service, dict):
            continue
        if service.get("restart") != "no":
            errors.append(f"One-shot service {service_name} must use restart: no")
        if service.get("exclude_from_hc") is not True:
            errors.append(f"One-shot service {service_name} must be excluded from health accounting")
        if "healthcheck" in service:
            errors.append(f"One-shot service {service_name} must not have a health check")

    for service_name in sorted(LONG_RUNNING_SERVICES):
        service = services.get(service_name, {})
        if not isinstance(service, dict):
            continue
        if service.get("restart") != "unless-stopped":
            errors.append(f"Long-running service {service_name} must restart unless-stopped")
        if "exclude_from_hc" in service:
            errors.append(f"Long-running service {service_name} must not be excluded from health accounting")
        healthcheck = service.get("healthcheck")
        if not isinstance(healthcheck, dict):
            errors.append(f"Long-running service {service_name} is missing a health check")
            continue
        if healthcheck.get("disable") is True:
            errors.append(f"Long-running service {service_name} must not disable its health check")
        test = healthcheck.get("test")
        if (
            not isinstance(test, list)
            or len(test) < 2
            or test[0] not in {"CMD", "CMD-SHELL"}
            or not all(str(part).strip() for part in test[1:])
        ):
            errors.append(f"{service_name} health check test has an invalid shape")
        for field in ("interval", "timeout", "start_period"):
            if not isinstance(healthcheck.get(field), str) or not healthcheck[field].strip():
                errors.append(f"{service_name} health check is missing {field}")
        if not isinstance(healthcheck.get("retries"), int) or healthcheck["retries"] < 1:
            errors.append(f"{service_name} health check retries must be a positive integer")

    scheduler = services.get("scheduler", {})
    scheduler_healthcheck = (
        scheduler.get("healthcheck", {}) if isinstance(scheduler, dict) else {}
    )
    scheduler_health = _command_text(
        scheduler_healthcheck.get("test", "")
        if isinstance(scheduler_healthcheck, dict)
        else ""
    )
    if not all(
        marker in scheduler_health
        for marker in (
            "/proc/1/task/1/children",
            "len(children) != 1",
            "/proc/{children[0]}",
            ".is_dir()",
            "/proc/{children[0]}/cmdline",
            "app.scheduler",
        )
    ) or "/proc/1/cmdline" in scheduler_health or "http" in scheduler_health:
        errors.append("scheduler health check must inspect exactly Tini's scheduler child")

    semantic_health_markers = {
        "postgres": ("pg_isready", "$$POSTGRES_USER", "$$POSTGRES_DB"),
        "api": (
            'host="$${TRUSTED_HOSTS%%,*}"',
            '-H "Host: $$host"',
            "http://127.0.0.1:8000/api/health",
        ),
        "gateway": ("wget", "http://127.0.0.1/healthz"),
        "opencode-runtime": (
            '--user "$${OPENCODE_SERVER_USERNAME}:$${OPENCODE_SERVER_PASSWORD}"',
            "http://127.0.0.1:4096/global/health",
            "http://127.0.0.1:4097/health",
        ),
        "formatting-worker": (
            "app.formatting.celery_bootstrap:celery_app inspect ping",
            'formatting-worker@$$(hostname)',
            "grep -q pong",
        ),
    }
    for worker_number in range(1, 6):
        semantic_health_markers[f"worker-{worker_number}"] = (
            "app.celery_app inspect ping",
            '-d "$${WORKER_NAME}@$$(hostname)"',
            "grep -q pong",
        )
    for service_name, markers in semantic_health_markers.items():
        service = services.get(service_name, {})
        healthcheck = service.get("healthcheck", {}) if isinstance(service, dict) else {}
        health_text = _command_text(
            healthcheck.get("test", "") if isinstance(healthcheck, dict) else ""
        )
        if not all(marker in health_text for marker in markers):
            errors.append(f"{service_name} health check does not verify its service semantics")

    dispatcher = services.get("formatting-dispatcher", {})
    dispatcher_environment = _environment(dispatcher)
    if dispatcher_environment.get("FORMATTING_DISPATCHER_HEARTBEAT_PATH") != (
        "${FORMATTING_DISPATCHER_HEARTBEAT_PATH:-/tmp/formatting-dispatcher-heartbeat}"
    ):
        errors.append("formatting-dispatcher heartbeat path must have its safe /tmp default")
    if not _tmpfs_covers(dispatcher, "/tmp/formatting-dispatcher-heartbeat"):
        errors.append("formatting-dispatcher heartbeat path must be tmpfs-backed")
    if dispatcher_environment.get("FORMATTING_DISPATCHER_HEARTBEAT_MAX_AGE_SECONDS") != (
        "${FORMATTING_DISPATCHER_HEARTBEAT_MAX_AGE_SECONDS:-180}"
    ):
        errors.append("formatting-dispatcher heartbeat maximum age must have its finite default")
    dispatcher_health = _command_text(
        dispatcher.get("healthcheck", {}).get("test", "")
        if isinstance(dispatcher, dict)
        else ""
    )
    if not all(
        marker in dispatcher_health
        for marker in (
            "FORMATTING_DISPATCHER_HEARTBEAT_PATH",
            "FORMATTING_DISPATCHER_HEARTBEAT_MAX_AGE_SECONDS",
            "time.time()",
            "read_text",
            "0 <= age <=",
        )
    ) or "/proc/" in dispatcher_health or "cmdline" in dispatcher_health:
        errors.append("formatting-dispatcher health check must verify heartbeat freshness")
    return errors


def _validate_compose_modules(root: Path, services: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for service_name, (module_marker, source_path) in COMPOSE_DIRECT_MODULES.items():
        service = services.get(service_name, {})
        command = _command_text(service.get("command", "") if isinstance(service, dict) else "")
        if module_marker not in command:
            errors.append(f"{service_name} command must invoke {module_marker}")
        if not (root / source_path).is_file():
            errors.append(f"Compose-direct module source is missing: {source_path}")
    return errors


def _validate_formatting_storage(services: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    exchange_pair = (
        "formatting-execution-exchange",
        "/data/formatting-execution",
    )
    opencode_data_pair = ("opencode-data", "/data/opencode/data")
    jobs_pair = ("formatting-jobs-data", "/data/formatting/jobs")

    opencode = services.get("opencode-runtime", {})
    if not _has_exact_mounts(opencode, {opencode_data_pair, exchange_pair}):
        errors.append(
            "opencode-runtime must mount only opencode-data and the execution exchange"
        )

    worker = services.get("formatting-worker", {})
    worker_pairs = {("formatting-data", "/data/formatting"), jobs_pair, exchange_pair}
    if not _has_exact_mounts(worker, worker_pairs):
        errors.append(
            "formatting-worker must mount only formatting data, persistent formatting jobs, and the execution exchange"
        )
    worker_environment = _environment(worker)
    if worker_environment.get("FORMATTING_ROOT") != "/data/formatting":
        errors.append("formatting-worker formatting root must be hardcoded")
    if worker_environment.get("FORMATTING_EXECUTION_ROOT") != "/data/formatting-execution":
        errors.append("formatting-worker execution root must be the hardcoded exchange path")
    for quota_variable in (
        "FORMATTING_EXECUTION_WORKSPACE_MAX_ENTRIES",
        "FORMATTING_EXECUTION_WORKSPACE_MAX_BYTES",
    ):
        if quota_variable not in worker_environment:
            errors.append(f"formatting-worker is missing {quota_variable}")

    dispatcher = services.get("formatting-dispatcher", {})
    if not _has_exact_mounts(dispatcher, {exchange_pair}):
        errors.append(
            "formatting-dispatcher janitor must mount only the execution exchange"
        )
    dispatcher_environment = _environment(dispatcher)
    if dispatcher_environment.get("FORMATTING_EXECUTION_ROOT") != (
        "/data/formatting-execution"
    ):
        errors.append("formatting-dispatcher execution root must be hardcoded")
    if any(key.startswith("OPENCODE_") for key in dispatcher_environment):
        errors.append("formatting-dispatcher must not receive OpenCode configuration or auth")

    storage_init = services.get("formatting-storage-init", {})
    storage_pairs = _volume_pairs(storage_init)
    if exchange_pair not in storage_pairs:
        errors.append("formatting-storage-init must mount the hardcoded execution exchange")
    storage_command_value = storage_init.get("command", "") if isinstance(storage_init, dict) else ""
    storage_command = _command_text(storage_command_value)
    sentinel_path = "/data/formatting-execution/.formatting-execution-root"
    if not all(
        marker in storage_command
        for marker in (
            f"rm -f {sentinel_path}",
            f"printf 'transcriptr-formatting-execution-v1\\n' > {sentinel_path}",
            f"test -f {sentinel_path}",
            f"test ! -L {sentinel_path}",
            f"chmod 0644 {sentinel_path}",
        )
    ):
        errors.append(
            "formatting-storage-init must recreate the fixed execution sentinel at the hardcoded path"
        )

    for service_name, service in (
        ("opencode-runtime", opencode),
        ("formatting-worker", worker),
    ):
        environment = _environment(service)
        expected_tmpfs = [
            ("XDG_CONFIG_HOME", "/tmp/opencode-config"),
            ("XDG_CACHE_HOME", "/tmp/opencode-cache"),
        ]
        if service_name == "formatting-worker":
            expected_tmpfs.append(("XDG_DATA_HOME", "/tmp/opencode-data"))
        for variable, expected_path in expected_tmpfs:
            actual_path = environment.get(variable)
            if actual_path != expected_path or not _tmpfs_covers(service, expected_path):
                errors.append(
                    f"{service_name} {variable} must use its configured tmpfs path"
                )
    opencode_environment = _environment(opencode)
    if opencode_environment.get("XDG_DATA_HOME") != "/data/opencode/data":
        errors.append("opencode-runtime persistent data must be authentication-only opencode-data")
    return errors


def verify(root: Path = ROOT) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    compose = root / COMPOSE_NAME
    if not compose.is_file():
        return [f"Missing canonical Compose file: {COMPOSE_NAME}"]

    missing_files = sorted(path for path in REQUIRED_SOURCE_FILES if not (root / path).is_file())
    if missing_files:
        errors.append("Missing source/build files: " + ", ".join(missing_files))
    if not any((root / path).is_file() for path in FRONTEND_LOCKFILES):
        errors.append(
            "Missing frontend lockfile; require at least one of: "
            + ", ".join(FRONTEND_LOCKFILES)
        )
    errors.extend(_validate_proxy_contract(root))

    text = compose.read_text(encoding="utf-8", errors="replace")
    if "docker-compose.formatting.yml" in text.casefold():
        errors.append("Canonical docker-compose.yml still references the legacy formatting overlay")
    missing_magic = sorted(name for name in REQUIRED_MAGIC if name not in text)
    if missing_magic:
        errors.append("Missing Coolify magic variables: " + ", ".join(missing_magic))

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        errors.append(f"Canonical docker-compose.yml is invalid YAML: {exc}")
        data = None
    errors.extend(_validate_compose_document(text, data))
    if not isinstance(data, dict) or not isinstance(data.get("services"), dict):
        if data is not None:
            errors.append("Canonical docker-compose.yml has no services mapping")
    else:
        services: dict[str, Any] = data["services"]
        service_names = set(services)
        if service_names != REQUIRED_SERVICES:
            errors.append(
                "Compose services must be exactly: "
                + ", ".join(sorted(REQUIRED_SERVICES))
            )
        errors.extend(_validate_runtime_overrides(services))
        errors.extend(_validate_topology(services))
        errors.extend(_validate_gateway_hardening(services))

        networks = data.get("networks")
        if not isinstance(networks, dict):
            errors.append("Canonical Compose file has no networks mapping")
        else:
            if set(networks) != REQUIRED_NETWORKS:
                errors.append(
                    "Compose networks must be exactly: "
                    + ", ".join(sorted(REQUIRED_NETWORKS))
                )
            data_network = networks.get("data")
            control = networks.get("formatting-control")
            gateway_network = networks.get("gateway")
            if not isinstance(data_network, dict) or data_network.get("internal") is not True:
                errors.append("data network must be internal")
            if not isinstance(control, dict) or control.get("internal") is not True:
                errors.append("formatting-control network must be internal")
            if (
                not isinstance(gateway_network, dict)
                or gateway_network.get("internal") is not True
            ):
                errors.append("gateway network must be internal")
            for network_name in ("edge", "formatting-egress", "transcription-egress"):
                network = networks.get(network_name)
                if not isinstance(network, dict) or network.get("internal") is not False:
                    errors.append(f"{network_name} network must explicitly be non-internal")
            errors.extend(_validate_gateway_network(services, networks))

        errors.extend(_validate_named_volumes(data.get("volumes")))

        dispatcher = services.get("formatting-dispatcher", {})
        if isinstance(dispatcher, dict):
            dispatcher_environment = dispatcher.get("environment", {})
            if not isinstance(dispatcher_environment, dict):
                errors.append("formatting-dispatcher environment must be a mapping")
                dispatcher_environment = {}
            environment_text = str(dispatcher_environment)
            if "OPENCODE_" in environment_text:
                errors.append("formatting-dispatcher must not receive OpenCode credentials")
            for variable in (
                "FORMATTING_QUEUED_RECONCILE_AGE_SECONDS",
                "FORMATTING_OUTBOX_MAX_DISPATCH_PER_CYCLE",
            ):
                if variable not in dispatcher_environment:
                    errors.append(
                        f"formatting-dispatcher environment is missing {variable}"
                    )
            command_text = str(dispatcher.get("command", ""))
            if "app.db_wait" not in command_text:
                errors.append("formatting-dispatcher Compose command must wait for the database")
            if "app.formatting.outbox_dispatcher" not in command_text:
                errors.append("formatting-dispatcher command is missing its dispatcher module")
        errors.extend(_validate_healthchecks(services))
        errors.extend(_validate_dependencies(services))
        errors.extend(_validate_redis_authentication(services))
        errors.extend(_validate_secret_distribution(services))
        errors.extend(_validate_formatting_limits(services))
        errors.extend(_validate_compose_modules(root, services))

        api = services.get("api", {})
        api_dependencies = api.get("depends_on", {}) if isinstance(api, dict) else {}
        if "opencode-runtime" in api_dependencies:
            errors.append("The core API must not depend on optional OpenCode health")
        errors.extend(_validate_formatting_storage(services))
        errors.extend(_validate_builds(root, services))

    errors.extend(_validate_migrations(root))
    tree_violations: list[str] = []
    try:
        validate_regular_tree(root, label="release tree")
    except UnsafeTreeObjectError as exc:
        tree_violations.append(str(exc))
        tree_paths: list[Path] = []
    else:
        tree_paths = sorted(root.rglob("*"))
    for path in tree_paths:
        relative = path.relative_to(root)
        if path.is_symlink():
            tree_violations.append(f"{relative.as_posix()} (symbolic link)")
            continue
        try:
            mode = path.stat(follow_symlinks=False).st_mode
        except OSError as exc:
            tree_violations.append(
                f"{relative.as_posix()} (filesystem metadata unreadable: {exc})"
            )
            continue
        if not stat.S_ISREG(mode) and not stat.S_ISDIR(mode):
            tree_violations.append(f"{relative.as_posix()} (special filesystem object)")
            continue
        reason = prohibited_tree_reason(relative) or _generated_tree_reason(relative)
        if reason is not None:
            tree_violations.append(f"{relative.as_posix()} ({reason})")
    if tree_violations:
        errors.append(
            "Release tree contains prohibited secret/local-state/cache/backup/special files: "
            + ", ".join(tree_violations)
        )
    return errors


def main() -> int:
    target = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) == 2 else ROOT
    if len(sys.argv) > 2:
        print("Usage: verify_coolify_bundle.py [merged-project]", file=sys.stderr)
        return 2
    errors = verify(target)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(
        "Structural deployment preflight passed. This does not prove transitive source "
        "completeness or runtime validity; Docker Compose config and all image builds "
        "remain mandatory external gates."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
