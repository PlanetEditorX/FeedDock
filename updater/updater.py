#!/usr/bin/env python3
from __future__ import annotations

import hmac
import json
import os
import secrets
import subprocess
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BIND = os.getenv("UPDATER_BIND", "0.0.0.0").strip() or "0.0.0.0"
PORT = int(os.getenv("UPDATER_PORT", "8090"))
TOKEN_FILE = Path(os.getenv("UPDATER_TOKEN_FILE", "/state/token"))
COMPOSE_FILE = Path(os.getenv("UPDATER_COMPOSE_FILE", "/workspace/docker-compose.yml"))
PROJECT_DIR = Path(os.getenv("UPDATER_PROJECT_DIR", "/workspace"))
ENV_FILE = Path(os.getenv("UPDATER_ENV_FILE", "/workspace/.env"))
SERVICE = os.getenv("UPDATER_SERVICE", "feeddock").strip() or "feeddock"
CONTAINER = os.getenv("UPDATER_CONTAINER", "feeddock").strip() or "feeddock"
FALLBACK_PROJECT = os.getenv("UPDATER_PROJECT_NAME", "feeddock").strip() or "feeddock"

_STATE_LOCK = threading.Lock()
_STATE = {
    "running": False,
    "started_at": "",
    "finished_at": "",
    "ok": None,
    "message": "idle",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_token() -> str:
    configured = os.getenv("UPDATER_TOKEN", "").strip()
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    if configured:
        token = configured
    elif TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    else:
        token = secrets.token_hex(32)
    TOKEN_FILE.write_text(token + "\n", encoding="utf-8")
    os.chmod(TOKEN_FILE, 0o644)
    return token


TOKEN = _ensure_token()


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _project_name() -> str:
    try:
        result = _run(
            "docker",
            "inspect",
            CONTAINER,
            "--format",
            '{{ index .Config.Labels "com.docker.compose.project" }}',
        )
        value = result.stdout.strip()
        if value and value != "<no value>":
            return value
    except (subprocess.CalledProcessError, OSError):
        pass
    return FALLBACK_PROJECT


def _compose_base() -> list[str]:
    args = [
        "docker",
        "compose",
        "-p",
        _project_name(),
        "--project-directory",
        str(PROJECT_DIR),
        "-f",
        str(COMPOSE_FILE),
    ]
    if ENV_FILE.is_file():
        args.extend(["--env-file", str(ENV_FILE)])
    return args


def _set_state(**values) -> None:
    with _STATE_LOCK:
        _STATE.update(values)


def _snapshot() -> dict:
    with _STATE_LOCK:
        return dict(_STATE)


def _perform_update() -> None:
    _set_state(running=True, started_at=_now(), finished_at="", ok=None, message="pulling image")
    try:
        base = _compose_base()
        pull = _run(*base, "pull", SERVICE)
        _set_state(message="recreating FeedDock")
        up = _run(*base, "up", "-d", "--no-deps", SERVICE)
        output = "\n".join(part.strip() for part in (pull.stdout, up.stdout) if part.strip())[-4000:]
        _set_state(
            running=False,
            finished_at=_now(),
            ok=True,
            message=output or "FeedDock update completed",
        )
    except subprocess.CalledProcessError as exc:
        _set_state(
            running=False,
            finished_at=_now(),
            ok=False,
            message=(exc.stdout or str(exc))[-4000:],
        )
    except Exception as exc:  # pragma: no cover - final safety net for the sidecar
        _set_state(running=False, finished_at=_now(), ok=False, message=str(exc))


class Handler(BaseHTTPRequestHandler):
    server_version = "FeedDockUpdater/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[{_now()}] {self.address_string()} {fmt % args}", flush=True)

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        header = self.headers.get("Authorization", "")
        prefix = "Bearer "
        supplied = header[len(prefix):].strip() if header.startswith(prefix) else ""
        return bool(supplied) and hmac.compare_digest(supplied, TOKEN)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/healthz":
            self._json(200, {"ok": True, "service": "feeddock-updater"})
            return
        if self.path == "/v1/status":
            if not self._authorized():
                self._json(401, {"ok": False, "message": "unauthorized"})
                return
            self._json(200, {"ok": True, **_snapshot()})
            return
        self._json(404, {"ok": False, "message": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/update":
            self._json(404, {"ok": False, "message": "not found"})
            return
        if not self._authorized():
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        with _STATE_LOCK:
            if _STATE["running"]:
                self._json(409, {"ok": False, "message": "update already running"})
                return
            _STATE.update(
                running=True,
                started_at=_now(),
                finished_at="",
                ok=None,
                message="queued",
            )
        thread = threading.Thread(target=_perform_update, name="feeddock-update", daemon=True)
        thread.start()
        self._json(202, {"ok": True, "message": "FeedDock update started"})


def main() -> None:
    if not COMPOSE_FILE.is_file():
        raise SystemExit(f"compose file not found: {COMPOSE_FILE}")
    print(
        f"FeedDock updater listening on {BIND}:{PORT}; compose={COMPOSE_FILE}; service={SERVICE}",
        flush=True,
    )
    ThreadingHTTPServer((BIND, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
