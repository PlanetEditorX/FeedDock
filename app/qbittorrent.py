from __future__ import annotations

from typing import Any

import httpx

from .config import settings
from .db import get_setting, set_setting

DEFAULTS = {
    "url": "",
    "username": "",
    "password": "",
    "category": "rss",
    "download_path": "/downloads/rss",
}


def env_config() -> dict[str, str]:
    import os

    return {
        "url": os.getenv("QBIT_URL", "").rstrip("/"),
        "username": os.getenv("QBIT_USERNAME", ""),
        "password": os.getenv("QBIT_PASSWORD", ""),
        "category": os.getenv("QBIT_CATEGORY", "rss"),
        "download_path": os.getenv("DOWNLOAD_PATH", "/downloads/rss"),
    }


def current_config(include_password: bool = False) -> dict[str, Any]:
    base = env_config()
    saved = get_setting("qbittorrent", {}) or {}
    base.update({key: value for key, value in saved.items() if value is not None})
    base["configured_from"] = "web" if saved else "environment"
    base["has_password"] = bool(base.get("password"))
    if not include_password:
        base.pop("password", None)
    return base


def save_config(payload: dict[str, Any]) -> dict[str, Any]:
    old = current_config(include_password=True)
    password = str(payload.get("password") or "")
    new = {
        "url": str(payload.get("url") or "").strip().rstrip("/"),
        "username": str(payload.get("username") or "").strip(),
        "password": password if password else old.get("password", ""),
        "category": str(payload.get("category") or "rss").strip(),
        "download_path": str(payload.get("download_path") or "/downloads/rss").strip(),
    }
    set_setting("qbittorrent", new)
    return current_config()


def restore_config() -> dict[str, Any]:
    set_setting("qbittorrent", {})
    return current_config()


async def test_connection(config: dict[str, Any] | None = None) -> dict[str, str]:
    cfg = config or current_config(include_password=True)
    if not cfg.get("url"):
        raise ValueError("QBIT_URL 尚未配置")
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds, follow_redirects=True) as client:
        response = await client.post(
            cfg["url"] + "/api/v2/auth/login",
            data={"username": cfg.get("username", ""), "password": cfg.get("password", "")},
            headers={"Referer": cfg["url"] + "/", "Origin": cfg["url"]},
        )
        response.raise_for_status()
        if response.text.strip().lower() != "ok.":
            raise RuntimeError("qBittorrent 登录失败")
        version_response = await client.get(cfg["url"] + "/api/v2/app/version")
        version_response.raise_for_status()
        return {"version": version_response.text.strip(), "url": cfg["url"]}


async def add_download(url: str, save_path: str = "", category: str = "") -> None:
    cfg = current_config(include_password=True)
    await test_connection(cfg)
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds, follow_redirects=True) as client:
        login = await client.post(
            cfg["url"] + "/api/v2/auth/login",
            data={"username": cfg.get("username", ""), "password": cfg.get("password", "")},
            headers={"Referer": cfg["url"] + "/", "Origin": cfg["url"]},
        )
        login.raise_for_status()
        response = await client.post(
            cfg["url"] + "/api/v2/torrents/add",
            data={
                "urls": url,
                "savepath": save_path or cfg.get("download_path", ""),
                "category": category or cfg.get("category", "rss"),
            },
            headers={"Referer": cfg["url"] + "/", "Origin": cfg["url"]},
        )
        response.raise_for_status()
        if response.text.strip().lower() not in {"ok.", ""}:
            raise RuntimeError(response.text.strip())
