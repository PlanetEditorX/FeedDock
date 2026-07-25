from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from .config import settings


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


class UpdateService:
    def __init__(
        self,
        *,
        repository: str | None = None,
        api_url: str | None = None,
        watchtower_url: str | None = None,
        watchtower_token: str | None = None,
        github_token: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self.repository = settings.update_repository if repository is None else repository.strip().strip("/")
        self.api_url = settings.update_api_url if api_url is None else api_url.rstrip("/")
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
            message="未检查更新；仅在点击“检查更新”时访问 GitHub",
        )

    def check(self) -> UpdateStatus:
        result = self.local_status()
        if not self.repository or "/" not in self.repository:
            result.message = "未配置 UPDATE_REPOSITORY，无法检查 GitHub Release"
            return result

        url = f"{self.api_url}/repos/{self.repository}/releases/latest"
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": f"FeedDock/{settings.app_version}",
            "X-GitHub-Api-Version": "2026-03-10",
        }
        if self.github_token:
            headers["Authorization"] = f"Bearer {self.github_token}"

        try:
            response = httpx.get(url, headers=headers, timeout=self.timeout, follow_redirects=True)
            if response.status_code == 404:
                result.message = "仓库尚未发布 GitHub Release，或仓库不可访问"
                return result
            if response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0":
                reset_at = _format_rate_limit_reset(response.headers.get("x-ratelimit-reset", ""))
                result.message = f"GitHub API 请求已达上限，请在 {reset_at} 后再次手动检查"
                return result
            response.raise_for_status()
            payload = response.json()
            result.latest_version = str(payload.get("tag_name", "")).lstrip("v")
            result.release_url = str(payload.get("html_url", ""))
            result.published_at = str(payload.get("published_at", ""))
            result.update_available = is_newer_version(result.latest_version, result.current_version)
            result.message = "发现新版本" if result.update_available else "当前已是最新版本"
            return result
        except (httpx.HTTPError, ValueError) as exc:
            result.message = f"检查更新失败：{exc}"
            return result

    def trigger_update(self) -> tuple[bool, str]:
        if not self.updater_configured:
            return False, "未配置 Watchtower 更新服务"
        try:
            response = httpx.post(
                f"{self.watchtower_url}/v1/update",
                headers={"Authorization": f"Bearer {self.watchtower_token}"},
                timeout=max(self.timeout, 30),
                follow_redirects=True,
            )
            if response.status_code not in {200, 204}:
                body = response.text.strip()[:300]
                return False, f"更新服务返回 HTTP {response.status_code}{f'：{body}' if body else ''}"
            return True, "已触发镜像更新检查；若存在新镜像，容器将自动重建并短暂重启"
        except httpx.HTTPError as exc:
            return False, f"调用更新服务失败：{exc}"
