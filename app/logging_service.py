from __future__ import annotations

import json
import logging
import logging.handlers
import re
import sys
import traceback
from pathlib import Path
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .config import settings
from .database import SessionLocal
from .models import AppSetting, SystemLog

_LOG_LEVEL_KEY = "log_level"
_ALLOWED_LEVELS = {"INFO", "DEBUG"}
_SECRET_RE = re.compile(
    r"(?i)(password|passwd|token|api[_-]?key|secret|authorization|cookie)"
    r"(\s*[=:]\s*)([^\s,;]+)"
)


def _redact(value: str) -> str:
    return _SECRET_RE.sub(r"\1\2***", value or "")


def _file_logger() -> logging.Logger:
    """Return the application logger used by both the file and Docker stdout."""

    logger = logging.getLogger("feeddock")
    if getattr(logger, "_feeddock_configured", False):
        return logger

    log_dir = Path(settings.data_dir) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "feeddock.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Make the same diagnostic entries visible through `docker logs feeddock`.
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger._feeddock_configured = True  # type: ignore[attr-defined]
    return logger


def get_log_level(db: Session) -> str:
    row = db.get(AppSetting, _LOG_LEVEL_KEY)
    default = (settings.log_level or "INFO").strip().upper()
    default = default if default in _ALLOWED_LEVELS else "INFO"
    value = (row.value if row else default).strip().upper()
    return value if value in _ALLOWED_LEVELS else default


def initialize_log_level(db: Session) -> str:
    """Persist the Compose default only when the user has never chosen a level."""

    row = db.get(AppSetting, _LOG_LEVEL_KEY)
    if row:
        return get_log_level(db)
    level = (settings.log_level or "INFO").strip().upper()
    if level not in _ALLOWED_LEVELS:
        level = "INFO"
    db.add(AppSetting(key=_LOG_LEVEL_KEY, value=level))
    db.commit()
    return level


def set_log_level(db: Session, level: str) -> str:
    normalized = (level or "INFO").strip().upper()
    if normalized not in _ALLOWED_LEVELS:
        raise ValueError("日志级别只能是 INFO 或 DEBUG")
    row = db.get(AppSetting, _LOG_LEVEL_KEY)
    if row:
        row.value = normalized
    else:
        db.add(AppSetting(key=_LOG_LEVEL_KEY, value=normalized))
    db.commit()
    return normalized


def debug_enabled(db: Session) -> bool:
    return get_log_level(db) == "DEBUG"


def log_event(
    db: Session,
    level: str,
    message: str,
    details: str = "",
    *,
    request_id: str = "",
    source: str = "app",
) -> None:
    """Add one log row to an existing session and always mirror it to disk/stdout.

    Callers that are inside a business transaction should normally use
    :func:`record_event`, which stores logs in a separate session and therefore
    cannot make subscription/RSS writes fail.
    """

    normalized = (level or "INFO").strip().upper()
    if normalized == "DEBUG" and not debug_enabled(db):
        return
    safe_message = _redact(str(message))[:4000]
    safe_details = _redact(str(details))[:30000]
    db.add(
        SystemLog(
            level=normalized[:16],
            message=safe_message,
            details=safe_details,
            request_id=(request_id or "")[:64],
            source=(source or "app")[:64],
        )
    )
    _file_logger().log(
        getattr(logging, normalized, logging.INFO),
        "%s [%s] %s%s",
        source,
        request_id or "-",
        safe_message,
        f" | {safe_details}" if safe_details else "",
    )


def exception_details(exc: BaseException, *, context: dict[str, Any] | None = None) -> str:
    payload = {
        "exception_type": type(exc).__name__,
        "exception_message": str(exc),
        "context": context or {},
        "traceback": traceback.format_exc(),
    }
    return _redact(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def log_exception(
    db: Session,
    message: str,
    exc: BaseException,
    *,
    request_id: str = "",
    source: str = "app",
    context: dict[str, Any] | None = None,
) -> None:
    try:
        log_event(
            db,
            "ERROR",
            message,
            exception_details(exc, context=context),
            request_id=request_id,
            source=source,
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        _file_logger().exception("无法写入数据库日志：%s", message)


def record_event(
    level: str,
    message: str,
    details: str = "",
    *,
    request_id: str = "",
    source: str = "app",
) -> None:
    """Persist an event independently from the caller's business transaction."""

    try:
        with SessionLocal() as db:
            log_event(
                db,
                level,
                message,
                details,
                request_id=request_id,
                source=source,
            )
            db.commit()
    except Exception:
        # Logging must never cause a user operation to fail. The file fallback
        # retains the message even when SQLite is unavailable or being migrated.
        _file_logger().exception(
            "数据库日志写入失败；原始事件：%s [%s] %s | %s",
            source,
            request_id or "-",
            _redact(str(message)),
            _redact(str(details)),
        )


def record_exception(
    message: str,
    exc: BaseException,
    *,
    request_id: str = "",
    source: str = "app",
    context: dict[str, Any] | None = None,
) -> None:
    """Persist a full traceback without touching the caller's transaction."""

    details = exception_details(exc, context=context)
    record_event(
        "ERROR",
        message,
        details,
        request_id=request_id,
        source=source,
    )


def log_file_path() -> Path:
    return Path(settings.data_dir) / "logs" / "feeddock.log"
