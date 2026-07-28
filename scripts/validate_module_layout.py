#!/usr/bin/env python3
"""Fail fast when application modules are overwritten by notification modules."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    path = ROOT / relative
    if not path.is_file():
        raise SystemExit(f"缺少必要文件：{relative}")
    return path.read_text(encoding="utf-8")


def _assert_contains(source: str, needle: str, relative: str) -> None:
    if needle not in source:
        raise SystemExit(f"模块结构异常：{relative} 缺少 {needle!r}")


def _assert_not_contains(source: str, needle: str, relative: str) -> None:
    if needle in source:
        raise SystemExit(f"模块结构异常：{relative} 不应包含 {needle!r}")


def main() -> int:
    app_init = _read("app/__init__.py")
    app_config = _read("app/config.py")
    notification_init = _read("app/notification/__init__.py")
    notification_config = _read("app/notification/config.py")

    # Parse all four files so truncated or malformed uploads fail before unit-test discovery.
    for relative, source in (
        ("app/__init__.py", app_init),
        ("app/config.py", app_config),
        ("app/notification/__init__.py", notification_init),
        ("app/notification/config.py", notification_config),
    ):
        try:
            ast.parse(source, filename=relative)
        except SyntaxError as exc:
            raise SystemExit(f"模块语法异常：{relative}: {exc}") from exc

    _assert_contains(app_init, "FeedDock application package", "app/__init__.py")
    _assert_not_contains(app_init, "from .channels", "app/__init__.py")
    _assert_not_contains(app_init, "normalize_bark_push_url", "app/__init__.py")

    _assert_contains(app_config, "from .build_info import load_build_info", "app/config.py")
    _assert_contains(app_config, "def load_settings()", "app/config.py")
    _assert_contains(app_config, '_optional_path("MEDIA_LOCAL_ROOT", "/media")', "app/config.py")
    _assert_not_contains(app_config, "Persistent notification settings", "app/config.py")
    _assert_not_contains(app_config, "from ..models import AppSetting", "app/config.py")

    _assert_contains(notification_init, "from .channels import normalize_bark_push_url", "app/notification/__init__.py")
    _assert_contains(notification_init, "from .config import", "app/notification/__init__.py")

    _assert_contains(notification_config, "Persistent notification settings", "app/notification/config.py")
    _assert_contains(notification_config, "from ..models import AppSetting", "app/notification/config.py")
    _assert_contains(notification_config, "def load_notification_config", "app/notification/config.py")
    _assert_not_contains(notification_config, "from .build_info import load_build_info", "app/notification/config.py")

    print("模块目录结构检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
