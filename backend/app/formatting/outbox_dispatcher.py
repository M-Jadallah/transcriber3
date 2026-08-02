from __future__ import annotations

import json
import logging
import os
import re
import signal
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.core.db import SessionLocal
from app.formatting.celery_bootstrap import celery_app
from app.formatting.repository import (
    active_running_execution_keys,
    cancel_invalid_outbox,
    claim_outbox,
    mark_outbox_published,
    reconcile_queued_jobs,
    recover_expired_jobs,
    release_outbox,
)
from app.formatting.runtime import cleanup_orphan_execution_workspaces

logger = logging.getLogger(__name__)

_FORMAT_JOB_TASK = "app.formatting.run_job"
_FORMAT_QUEUE = "formatting"
_SAFE_ID = re.compile(r"\A[A-Za-z0-9](?:[A-Za-z0-9_-]{0,34}[A-Za-z0-9])?\Z")
_UUID = re.compile(
    r"\A[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)

_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"(?i)(refresh[_ -]?token\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"(?i)(password\s*[:=]\s*)[^\s,;]+"),
)


def _safe_error(exc: Exception) -> str:
    value = str(exc).strip()[:4000] or exc.__class__.__name__
    for pattern in _SECRET_PATTERNS:
        value = pattern.sub(
            lambda match: (match.group(1) if match.lastindex else "") + "[REDACTED]",
            value,
        )
    return value


def _event_envelope(event: Any) -> tuple[str, str, str]:
    if type(event) is not dict:
        raise ValueError("Claimed outbox event must be an object")
    outbox_id = event.get("id")
    if type(outbox_id) is not str or not _SAFE_ID.fullmatch(outbox_id):
        raise ValueError("Claimed outbox event ID is invalid")
    claim_token = event.get("claim_token")
    if type(claim_token) is not str or not _UUID.fullmatch(claim_token):
        raise ValueError("Claimed outbox fencing token is invalid")
    task_name = event.get("task_name")
    if type(task_name) is not str or task_name != _FORMAT_JOB_TASK:
        raise ValueError("Claimed outbox task is invalid")

    value = event.get("payload")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Outbox payload is not valid JSON") from exc
    if type(value) is not dict:
        raise ValueError("Outbox payload must be an object")
    if set(value) != {"args", "kwargs", "queue"}:
        raise ValueError("Outbox payload fields are invalid")

    args = value["args"]
    if (
        type(args) is not list
        or len(args) != 1
        or type(args[0]) is not str
        or not _SAFE_ID.fullmatch(args[0])
    ):
        raise ValueError("Outbox formatting job ID is invalid")
    formatting_job_id = event.get("formatting_job_id")
    if type(formatting_job_id) is not str or args[0] != formatting_job_id:
        raise ValueError("Outbox formatting job ID does not match its event")
    if type(value["kwargs"]) is not dict or value["kwargs"]:
        raise ValueError("Outbox keyword arguments must be empty")
    if type(value["queue"]) is not str or value["queue"] != _FORMAT_QUEUE:
        raise ValueError("Outbox queue is invalid")
    return outbox_id, formatting_job_id, claim_token


def dispatch_once(
    *,
    session_factory: Callable[[], Any] = SessionLocal,
    publisher: Any = celery_app,
    stale_seconds: int = 120,
    backoff_base_seconds: int = 2,
    backoff_cap_seconds: int = 300,
) -> bool:
    with session_factory() as db:
        event = claim_outbox(db, stale_seconds=stale_seconds)
    if event is None:
        return False

    try:
        outbox_id, formatting_job_id, claim_token = _event_envelope(event)
    except Exception as exc:
        error = _safe_error(exc)
        claimed_id = event.get("id") if isinstance(event, dict) else None
        claimed_token = event.get("claim_token") if isinstance(event, dict) else None
        if (
            isinstance(claimed_id, str)
            and isinstance(claimed_token, str)
            and _UUID.fullmatch(claimed_token)
        ):
            with session_factory() as db:
                cancel_invalid_outbox(db, claimed_id, claimed_token, error=error)
        logger.error("Rejected invalid formatting outbox event: %s", error)
        return True

    try:
        publisher.send_task(
            _FORMAT_JOB_TASK,
            args=[formatting_job_id],
            kwargs={},
            queue=_FORMAT_QUEUE,
            task_id=outbox_id,
        )
    except Exception as exc:
        error = _safe_error(exc)
        attempts = max(1, int(event.get("attempts") or 1))
        backoff = min(
            max(1, backoff_cap_seconds),
            max(1, backoff_base_seconds) * (2 ** min(attempts - 1, 20)),
        )
        with session_factory() as db:
            release_outbox(
                db,
                outbox_id,
                claim_token,
                error=error,
                backoff_seconds=backoff,
            )
        logger.warning("Formatting outbox publish failed: %s", error)
        return True

    # If this commit fails, the processing lock is deliberately left in place.
    # A later stale-lock claim republishes with the same deterministic task ID.
    with session_factory() as db:
        marked = mark_outbox_published(db, outbox_id, claim_token)
    if not marked:
        logger.warning(
            "Formatting outbox %s was published but its job no longer accepts "
            "the delivery task ID",
            outbox_id,
        )
    return True


def cleanup_exchange_once(
    execution_root: Path,
    *,
    session_factory: Callable[[], Any] = SessionLocal,
    recent_lease_seconds: int = 300,
    grace_seconds: int = 86400,
    max_entries: int = 10000,
) -> int:
    with session_factory() as db:
        active_keys = active_running_execution_keys(
            db,
            recent_lease_seconds=recent_lease_seconds,
        )
    return cleanup_orphan_execution_workspaces(
        execution_root,
        active_keys,
        grace_seconds=grace_seconds,
        max_entries=max_entries,
    )


def _positive_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _poll_interval() -> float:
    try:
        value = float(os.getenv("FORMATTING_OUTBOX_POLL_SECONDS", "1"))
    except ValueError:
        value = 1.0
    return max(0.25, min(value, 60.0))


def _heartbeat_path() -> Path:
    path = Path(
        os.getenv(
            "FORMATTING_DISPATCHER_HEARTBEAT_PATH",
            "/tmp/formatting-dispatcher-heartbeat",
        )
    )
    if not path.is_absolute() or path == Path("/tmp"):
        raise ValueError("Dispatcher heartbeat path must be a file under /tmp")
    try:
        path.parent.resolve(strict=True).relative_to(Path("/tmp").resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise ValueError("Dispatcher heartbeat path must be a file under /tmp") from exc
    return path


def _write_heartbeat(path: Path) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as heartbeat:
            heartbeat.write(f"{time.time():.6f}\n")
            heartbeat.flush()
            os.fsync(heartbeat.fileno())
        os.replace(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def main() -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    stop = threading.Event()

    def request_stop(_signum: int, _frame: Any) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    stale_seconds = _positive_int("FORMATTING_OUTBOX_STALE_SECONDS", 120, 30)
    backoff_base = _positive_int("FORMATTING_OUTBOX_BACKOFF_BASE_SECONDS", 2)
    backoff_cap = _positive_int("FORMATTING_OUTBOX_BACKOFF_CAP_SECONDS", 300)
    recovery_batch = _positive_int("FORMATTING_RECOVERY_BATCH_SIZE", 25)
    reconcile_age = _positive_int(
        "FORMATTING_QUEUED_RECONCILE_AGE_SECONDS", 300, 30
    )
    reconcile_batch = _positive_int("FORMATTING_RECONCILE_BATCH_SIZE", 25)
    max_dispatch = _positive_int("FORMATTING_OUTBOX_MAX_DISPATCH_PER_CYCLE", 100)
    janitor_interval = _positive_int(
        "FORMATTING_EXCHANGE_JANITOR_INTERVAL_SECONDS", 300, 30
    )
    janitor_grace = _positive_int(
        "FORMATTING_EXCHANGE_JANITOR_GRACE_SECONDS", 86400, 300
    )
    janitor_recent_lease = _positive_int(
        "FORMATTING_EXCHANGE_JANITOR_RECENT_LEASE_SECONDS", 300
    )
    janitor_max_entries = _positive_int(
        "FORMATTING_EXCHANGE_JANITOR_MAX_ENTRIES", 10000, 100
    )
    execution_root = Path(
        os.getenv("FORMATTING_EXECUTION_ROOT", "/data/formatting-execution")
    )
    poll_seconds = _poll_interval()
    heartbeat_path = _heartbeat_path()
    next_janitor = 0.0

    while not stop.is_set():
        try:
            monotonic_now = time.monotonic()
            if monotonic_now >= next_janitor:
                next_janitor = monotonic_now + janitor_interval
                try:
                    removed = cleanup_exchange_once(
                        execution_root,
                        recent_lease_seconds=janitor_recent_lease,
                        grace_seconds=janitor_grace,
                        max_entries=janitor_max_entries,
                    )
                    if removed:
                        logger.warning(
                            "Removed %d stale orphan formatting execution workspace(s)",
                            removed,
                        )
                except Exception:
                    logger.warning(
                        "Formatting execution exchange janitor failed; unsafe or "
                        "unverified workspaces were retained",
                        exc_info=True,
                    )
            with SessionLocal() as db:
                recovered = recover_expired_jobs(db, limit=recovery_batch)
            if recovered:
                logger.warning("Recovered %d expired formatting execution(s)", recovered)
            with SessionLocal() as db:
                reconciled = reconcile_queued_jobs(
                    db,
                    min_age_seconds=reconcile_age,
                    limit=reconcile_batch,
                )
            if reconciled:
                logger.warning(
                    "Reconciled %d queued formatting delivery event(s)", reconciled
                )
            for _ in range(max_dispatch):
                if stop.is_set() or not dispatch_once(
                    stale_seconds=stale_seconds,
                    backoff_base_seconds=backoff_base,
                    backoff_cap_seconds=backoff_cap,
                ):
                    break
            _write_heartbeat(heartbeat_path)
        except Exception:
            logger.error("Formatting outbox iteration failed")
        stop.wait(poll_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
