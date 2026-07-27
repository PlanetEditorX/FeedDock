from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import AppSetting
from .outbound import external_client, external_get


_CACHE_KEY = "update_manifest_cache_json"
_CACHE_CHECKED_KEY = "update_manifest_checked_at"
_CACHE_URL_KEY = "update_manifest_source_url"
_CACHE_ETAG_KEY = "update_manifest_etag"
_CACHE_MODIFIED_KEY = "update_manifest_last_modified"
_API_CHECKED_KEY = "update_api_last_checked_at"


@dataclass(slots=True)
class UpdateStatus:
    current_version: str
    latest_version: str = ""
    update_available: bool = False
    release_url: str = ""
    published_at: str = ""
    repository: str = ""
    updater_configured: bool = False
    deployed_image: str = ""
    message: str = ""
    source: str = "local"
    checked_at: str = ""
    manifest_url: str = ""
    can_apply_update: bool = False

    def as_dict(self) -> dict[str, str | bool]:
        return {
            "current_version": self.current_version,
            "latest_version": self.latest_version,
            "update_available": self.update_available,
            "release_url": self.release_url,
            "published_at": self.published_at,
            "repository": self.repository,
            "updater_configured": self.updater_configured,
            "deployed_image": self.deployed_image,
            "message": self.message,
            "source": self.source,
            "checked_at": self.checked_at,
            "manifest_url": self.manifest_url,
            "can_apply_update": self.can_apply_update,
        }


def _version_tuple(value: str) -> tuple[int, ...]:
    normalized = value.strip().lower().lstrip("v")
    match = re.match(r"^(\d+(?:\.\d+){0,3})", normalized)
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer_version(latest: str, current: str) -> bool:
    latest_parts = _version_tuple(latest)
    current_parts = _version_tuple(current)
    if not latest_parts or not current_parts:
        return latest.strip() != current.strip()
    width = max(len(latest_parts), len(current_parts))
    return latest_parts + (0,) * (width - len(latest_parts)) > current_parts + (0,) * (
        width - len(current_parts)
    )


def _format_rate_limit_reset(value: str) -> str:
    try:
        reset_at = datetime.fromtimestamp(int(value), tz=timezone.utc).astimezone()
        return reset_at.strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return "稍后"


def _parse_datetime(value: str) -> datetime | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    try:
        parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _setting_rows(db: Session | None, keys: tuple[str, ...]) -> dict[str, str]:
    if db is None:
        return {}
    return {
        row.key: row.value
        for row in db.scalars(select(AppSetting).where(AppSetting.key.in_(keys)))
    }


def _save_settings(db: Session | None, values: dict[str, str]) -> None:
    if db is None:
        return
    existing = {
        row.key: row
        for row in db.scalars(select(AppSetting).where(AppSetting.key.in_(values)))
    }
    for key, value in values.items():
        row = existing.get(key)
        if row is None:
            db.add(AppSetting(key=key, value=value))
        else:
            row.value = value
    db.commit()


def _normalize_manifest(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise ValueError("版本清单必须是 JSON 对象")
    version = str(payload.get("version") or payload.get("latest_version") or "").strip().lstrip("v")
    if not _version_tuple(version):
        raise ValueError("版本清单缺少有效 version")
    release_url = str(payload.get("release_url") or payload.get("url") or "").strip()
    published_at = str(payload.get("published_at") or payload.get("updated_at") or "").strip()
    image = str(payload.get("image") or payload.get("deployed_image") or "").strip()
    return {
        "version": version,
        "release_url": release_url,
        "published_at": published_at,
        "image": image,
    }


class UpdateService:
    def __init__(
        self,
        *,
        repository: str | None = None,
        api_url: str | None = None,
        manifest_urls: tuple[str, ...] | list[str] | None = None,
        watchtower_url: str | None = None,
        watchtower_token: str | None = None,
        github_token: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self.repository = settings.update_repository if repository is None else repository.strip().strip("/")
        self.api_url = settings.update_api_url if api_url is None else api_url.rstrip("/")
        self.manifest_urls = tuple(settings.update_manifest_urls if manifest_urls is None else manifest_urls)
        self.watchtower_url = settings.watchtower_url if watchtower_url is None else watchtower_url.rstrip("/")
        self.watchtower_token = settings.watchtower_token if watchtower_token is None else watchtower_token
        self.github_token = settings.update_github_token if github_token is None else github_token.strip()
        self.timeout = timeout or settings.request_timeout_seconds

    @property
    def updater_configured(self) -> bool:
        return bool(self.watchtower_url and self.watchtower_token)

    def local_status(self) -> UpdateStatus:
        return UpdateStatus(
            current_version=settings.app_version,
            repository=self.repository,
            updater_configured=self.updater_configured,
            deployed_image=settings.deployed_image,
            can_apply_update=self.updater_configured,
            message="未检查更新；优先读取静态版本清单，不消耗 GitHub REST API 限额",
        )

    def _status_from_manifest(
        self,
        manifest: dict[str, str],
        *,
        source: str,
        checked_at: str,
        manifest_url: str,
        message_suffix: str = "",
    ) -> UpdateStatus:
        result = self.local_status()
        result.latest_version = manifest["version"]
        result.release_url = manifest.get("release_url", "")
        result.published_at = manifest.get("published_at", "")
        result.update_available = is_newer_version(result.latest_version, result.current_version)
        result.source = source
        result.checked_at = checked_at
        result.manifest_url = manifest_url
        result.message = "发现新版本" if result.update_available else "当前已是最新版本"
        if message_suffix:
            result.message += f"；{message_suffix}"
        return result

    def _cached_manifest(self, db: Session | None) -> tuple[dict[str, str] | None, dict[str, str]]:
        rows = _setting_rows(
            db,
            (
                _CACHE_KEY,
                _CACHE_CHECKED_KEY,
                _CACHE_URL_KEY,
                _CACHE_ETAG_KEY,
                _CACHE_MODIFIED_KEY,
                _API_CHECKED_KEY,
            ),
        )
        try:
            manifest = _normalize_manifest(json.loads(rows.get(_CACHE_KEY, ""))) if rows.get(_CACHE_KEY) else None
        except (ValueError, json.JSONDecodeError):
            manifest = None
        return manifest, rows

    def _manifest_check(self, db: Session | None, *, force: bool) -> UpdateStatus | None:
        cached, rows = self._cached_manifest(db)
        checked_at = _parse_datetime(rows.get(_CACHE_CHECKED_KEY, ""))
        if cached is not None and checked_at is not None and not force:
            age = datetime.now(timezone.utc) - checked_at
            if age < timedelta(hours=settings.update_check_cache_hours):
                return self._status_from_manifest(
                    cached,
                    source="manifest-cache",
                    checked_at=checked_at.isoformat(),
                    manifest_url=rows.get(_CACHE_URL_KEY, ""),
                    message_suffix=f"使用 {settings.update_check_cache_hours} 小时版本缓存",
                )

        errors: list[str] = []
        for url in self.manifest_urls:
            headers = {
                "Accept": "application/json",
                "User-Agent": f"FeedDock/{settings.app_version}",
                "Cache-Control": "no-cache",
            }
            if rows.get(_CACHE_URL_KEY) == url:
                if rows.get(_CACHE_ETAG_KEY):
                    headers["If-None-Match"] = rows[_CACHE_ETAG_KEY]
                if rows.get(_CACHE_MODIFIED_KEY):
                    headers["If-Modified-Since"] = rows[_CACHE_MODIFIED_KEY]
            try:
                response = external_get(url, headers=headers, timeout=self.timeout)
                now = datetime.now(timezone.utc).isoformat()
                if response.status_code == 304 and cached is not None:
                    _save_settings(db, {_CACHE_CHECKED_KEY: now})
                    return self._status_from_manifest(
                        cached,
                        source="manifest-304",
                        checked_at=now,
                        manifest_url=url,
                        message_suffix="远程版本清单未变化",
                    )
                response.raise_for_status()
                manifest = _normalize_manifest(response.json())
                _save_settings(
                    db,
                    {
                        _CACHE_KEY: json.dumps(manifest, ensure_ascii=False, sort_keys=True),
                        _CACHE_CHECKED_KEY: now,
                        _CACHE_URL_KEY: url,
                        _CACHE_ETAG_KEY: str(response.headers.get("etag") or ""),
                        _CACHE_MODIFIED_KEY: str(response.headers.get("last-modified") or ""),
                    },
                )
                return self._status_from_manifest(
                    manifest,
                    source="manifest",
                    checked_at=now,
                    manifest_url=url,
                )
            except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"{url}: {type(exc).__name__}")

        if cached is not None:
            return self._status_from_manifest(
                cached,
                source="manifest-stale-cache",
                checked_at=rows.get(_CACHE_CHECKED_KEY, ""),
                manifest_url=rows.get(_CACHE_URL_KEY, ""),
                message_suffix="版本清单暂时不可用，显示上次缓存",
            )
        return None

    def _github_api_check(self, db: Session | None) -> UpdateStatus:
        result = self.local_status()
        if not self.repository or "/" not in self.repository:
            result.message = "未配置 UPDATE_REPOSITORY，无法检查更新"
            return result

        _, rows = self._cached_manifest(db)
        api_checked = _parse_datetime(rows.get(_API_CHECKED_KEY, ""))
        if api_checked is not None and datetime.now(timezone.utc) - api_checked < timedelta(hours=24):
            result.message = "静态版本清单不可用；GitHub API 备用检查每天最多执行一次"
            return result

        url = f"{self.api_url}/repos/{self.repository}/releases/latest"
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": f"FeedDock/{settings.app_version}",
            "X-GitHub-Api-Version": "2026-03-10",
        }
        if self.github_token:
            headers["Authorization"] = f"Bearer {self.github_token}"

        now = datetime.now(timezone.utc).isoformat()
        _save_settings(db, {_API_CHECKED_KEY: now})
        try:
            response = external_get(url, headers=headers, timeout=self.timeout)
            if response.status_code == 404:
                result.message = "仓库尚未发布 GitHub Release，或仓库不可访问"
                return result
            if response.status_code in {403, 429}:
                if response.headers.get("x-ratelimit-remaining") == "0":
                    reset_at = _format_rate_limit_reset(response.headers.get("x-ratelimit-reset", ""))
                    result.message = f"GitHub API 请求已达上限，请在 {reset_at} 后再次手动检查"
                else:
                    retry_after = response.headers.get("retry-after", "")
                    result.message = f"GitHub API 暂时限流{f'，请在 {retry_after} 秒后重试' if retry_after else ''}"
                return result
            response.raise_for_status()
            payload = response.json()
            manifest = _normalize_manifest(
                {
                    "version": payload.get("tag_name", ""),
                    "release_url": payload.get("html_url", ""),
                    "published_at": payload.get("published_at", ""),
                    "image": settings.deployed_image,
                }
            )
            result = self._status_from_manifest(
                manifest,
                source="github-api-fallback",
                checked_at=now,
                manifest_url=url,
                message_suffix="静态版本清单不可用，已使用 GitHub API 备用检查",
            )
            return result
        except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
            result.message = f"检查更新失败：{exc}"
            return result

    def check(self, db: Session | None = None, *, force: bool = False) -> UpdateStatus:
        manifest_result = self._manifest_check(db, force=force)
        if manifest_result is not None:
            return manifest_result
        return self._github_api_check(db)

    def trigger_update(self) -> tuple[bool, str]:
        if not self.updater_configured:
            return (
                False,
                "在线更新需要 Watchtower HTTP API；请按部署说明配置 WATCHTOWER_URL 和 WATCHTOWER_TOKEN",
            )
        try:
            with external_client(
                f"{self.watchtower_url}/v1/update",
                timeout=max(self.timeout, 30),
            ) as client:
                response = client.post(
                    f"{self.watchtower_url}/v1/update",
                    headers={"Authorization": f"Bearer {self.watchtower_token}"},
                )
            if response.status_code not in {200, 204}:
                body = response.text.strip()[:300]
                return False, f"更新服务返回 HTTP {response.status_code}{f'：{body}' if body else ''}"
            return True, "已触发在线镜像更新；若存在新镜像，容器会自动重建并短暂重启"
        except httpx.HTTPError as exc:
            return False, f"调用更新服务失败：{exc}"
