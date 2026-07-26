from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re
import sys
import traceback
from typing import Any, Mapping

from sqlalchemy.exc import SQLAlchemyError

from .config import settings
from .database import SessionLocal
from .models import SystemLog


_ALLOWED_LEVELS = {"INFO", "DEBUG"}
_SENSITIVE_KEY = re.compile(r"password|passwd|token|api[_-]?key|secret|authorization|cookie", re.I)
_LOGGER_NAME = "feeddock"
_logger = logging.getLogger(_LOGGER_NAME)
_runtime_level = "INFO"
_configured = False


def normalize_log_level(value: str | None) -> str:
    level = str(value or "INFO").strip().upper()
    return level if level in _ALLOWED_LEVELS else "INFO"


def configure_logging(level: str | None = None) -> logging.Logger:
    global _configured
    selected = normalize_log_level(level or getattr(settings, "log_level", "INFO"))
    if not _configured:
        _logger.propagate = False
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(formatter)
        _logger.addHandler(console)

        try:
            log_dir = Path(settings.data_dir) / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                log_dir / "feeddock.log",
                maxBytes=5 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            _logger.addHandler(file_handler)
        except OSError:
            # Docker stdout remains available even when the mounted log path is unavailable.
            console.handle(
                logging.LogRecord(
                    _LOGGER_NAME,
                    logging.WARNING,
                    __file__,
                    0,
                    "无法创建文件日志，将仅输出到 Docker 日志",
                    (),
                    None,
                )
            )
        _configured = True

    set_runtime_log_level(selected)
    return _logger


def set_runtime_log_level(level: str | None) -> str:
    global _runtime_level
    _runtime_level = normalize_log_level(level)
    numeric = getattr(logging, _runtime_level)
    _logger.setLevel(numeric)
    for handler in _logger.handlers:
        handler.setLevel(numeric)
    return _runtime_level


def runtime_log_level() -> str:
    return _runtime_level


def debug_enabled() -> bool:
    return _runtime_level == "DEBUG"


def _redact(value: Any, *, key: str = "") -> Any:
    if key and _SENSITIVE_KEY.search(key):
        return "***"
    if isinstance(value, Mapping):
        return {str(k): _redact(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_redact(item) for item in value]
    text = str(value) if not isinstance(value, (str, int, float, bool, type(None))) else value
    if isinstance(text, str):
        # Redact credentials embedded in common proxy/basic-auth URLs.
        text = re.sub(r"(https?://)([^/@:\s]+):([^/@\s]+)@", r"\1***:***@", text)
    return text


def safe_json(value: Any) -> str:
    try:
        return json.dumps(_redact(value), ensure_ascii=False, indent=2, default=str)
    except (TypeError, ValueError):
        return repr(_redact(value))


def format_exception_details(
    exc: BaseException,
    *,
    request_id: str = "",
    method: str = "",
    path: str = "",
    stage: str = "",
    context: Mapping[str, Any] | None = None,
) -> str:
    header = {
        "request_id": request_id,
        "method": method,
        "path": path,
        "stage": stage or "unknown",
        "exception_type": type(exc).__name__,
        "exception_message": str(exc),
        "context": dict(context or {}),
    }
    trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    return f"{safe_json(header)}\n\nTraceback:\n{trace}"[:50000]


def persist_system_log(level: str, message: str, details: str = "") -> None:
    selected = str(level or "INFO").upper()
    try:
        with SessionLocal() as db:
            db.add(
                SystemLog(
                    level=selected[:16],
                    message=str(message)[:2000],
                    details=str(details)[:50000],
                )
            )
            db.commit()
    except (SQLAlchemyError, OSError, RuntimeError) as log_exc:
        _logger.error("系统日志写入数据库失败：%s", log_exc, exc_info=True)


def log_event(level: str, message: str, details: str = "", *, persist: bool = True) -> None:
    selected = str(level or "INFO").upper()
    numeric = getattr(logging, selected, logging.INFO)
    combined = message if not details else f"{message}\n{details}"
    _logger.log(numeric, combined)
    if persist:
        persist_system_log(selected, message, details)


def log_exception(
    message: str,
    exc: BaseException,
    *,
    request_id: str = "",
    method: str = "",
    path: str = "",
    stage: str = "",
    context: Mapping[str, Any] | None = None,
) -> str:
    details = format_exception_details(
        exc,
        request_id=request_id,
        method=method,
        path=path,
        stage=stage,
        context=context,
    )
    _logger.error("%s\n%s", message, details)
    persist_system_log("ERROR", message, details)
    return details


configure_logging()
