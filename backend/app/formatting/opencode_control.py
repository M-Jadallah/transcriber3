from __future__ import annotations

import base64
import os
import secrets
import signal
import time
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException

app = FastAPI(title="OpenCode Internal Control", docs_url=None, redoc_url=None, openapi_url=None)


def _authorized(authorization: str | None) -> bool:
    username = os.getenv("OPENCODE_SERVER_USERNAME", "opencode")
    password = os.getenv("OPENCODE_SERVER_PASSWORD", "")
    if not password or not authorization or not authorization.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(authorization[6:], validate=True).decode("utf-8")
        supplied_username, supplied_password = decoded.split(":", 1)
    except (ValueError, UnicodeDecodeError):
        return False
    return secrets.compare_digest(supplied_username, username) and secrets.compare_digest(
        supplied_password, password
    )


def _require_auth(authorization: str | None) -> None:
    if not _authorized(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")


def _auth_candidates() -> list[Path]:
    xdg_data = Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    candidates = [
        xdg_data / "opencode" / "auth.json",
        Path.home() / ".local" / "share" / "opencode" / "auth.json",
    ]
    unique: list[Path] = []
    for candidate in candidates:
        resolved = candidate.expanduser()
        if resolved not in unique:
            unique.append(resolved)
    return unique


def _restart_opencode_parent() -> None:
    # The compose command starts this control process in the background and then
    # execs `opencode serve` as PID 1. Terminating our parent therefore causes
    # Docker's restart policy to start a clean server with the removed auth file.
    time.sleep(0.75)
    parent = os.getppid()
    if parent > 1:
        os.kill(parent, signal.SIGTERM)


@app.get("/health")
def health(authorization: str | None = Header(default=None)) -> dict[str, bool]:
    _require_auth(authorization)
    return {"ok": True}


@app.post("/logout")
def logout(
    background_tasks: BackgroundTasks,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    _require_auth(authorization)
    removed: list[str] = []
    for path in _auth_candidates():
        try:
            if path.is_file():
                path.unlink()
                removed.append(str(path))
        except OSError as exc:
            raise HTTPException(status_code=500, detail="تعذر حذف بيانات مصادقة OpenCode") from exc

    background_tasks.add_task(_restart_opencode_parent)
    return {"success": True, "removed": bool(removed), "restarting": True}


def main() -> None:
    import uvicorn

    uvicorn.run(
        "app.formatting.opencode_control:app",
        host="0.0.0.0",
        port=int(os.getenv("OPENCODE_CONTROL_PORT", "4097")),
        log_level=os.getenv("OPENCODE_CONTROL_LOG_LEVEL", "warning"),
        access_log=False,
    )


if __name__ == "__main__":
    main()
