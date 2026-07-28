from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .image_registry import RegistryImageClient, RegistryImageMetadata
from .models import AppSetting
from .outbound import external_client


_CACHE_KEY = "update_registry_cache_json"
_CACHE_CHECKED_KEY = "update_registry_checked_at"


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
    current_revision: str = ""
    latest_revision: str = ""
    latest_digest: str = ""
    platform_digest: str = ""
    image_platform: str = ""

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
            "current_revision": self.current_revision,
            "latest_revision": self.latest_revision,
            "latest_digest": self.latest_digest,
            "platform_digest": self.platform_digest,
            "image_platform": self.image_platform,
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


def _short_revision(value: str) -> str:
    cleaned = str(value or "").strip()
    return cleaned[:12] if cleaned else ""


class UpdateService:
    """Check the deployed tag directly against its container registry metadata.

    Update availability no longer depends on a repository-hosted version manifest or a GitHub Release.
    The running image carries its source revision through ``APP_REVISION``. The
    remote tag's OCI config carries the same standard revision label, so the two
    builds can be compared without mounting the Docker socket into FeedDock.
    """

    def __init__(
        self,
        *,
        image: str | None = None,
        current_version: str | None = None,
        current_revision: str | None = None,
        watchtower_url: str | None = None,
        watchtower_token: str | None = None,
        timeout: int | None = None,
        registry_scheme: str = "https",
        registry_username: str | None = None,
        registry_token: str | None = None,
        registry_client: RegistryImageClient | None = None,
    ) -> None:
        self.image = settings.deployed_image if image is None else image.strip()
        self.current_version = settings.app_version if current_version is None else current_version.strip()
        self.current_revision = settings.app_revision if current_revision is None else current_revision.strip()
        self.watchtower_url = settings.watchtower_url if watchtower_url is None else watchtower_url.rstrip("/")
        self.watchtower_token = settings.watchtower_token if watchtower_token is None else watchtower_token
        self.timeout = timeout or settings.request_timeout_seconds
        self.registry_username = (
            settings.update_registry_username
            if registry_username is None
            else registry_username.strip()
        )
        self.registry_token = (
            settings.update_registry_token
            if registry_token is None
            else registry_token.strip()
        )
        self.registry_client = registry_client or RegistryImageClient(
            self.image,
            timeout=self.timeout,
            scheme=registry_scheme,
            username=self.registry_username,
            token=self.registry_token,
        )

    @property
    def updater_configured(self) -> bool:
        return bool(self.watchtower_url and self.watchtower_token)

    @property
    def image_is_pinned(self) -> bool:
        return "@sha256:" in self.image

    def local_status(self) -> UpdateStatus:
        can_apply = self.updater_configured and not self.image_is_pinned
        return UpdateStatus(
            current_version=self.current_version,
            repository=self.image,
            updater_configured=self.updater_configured,
            deployed_image=self.image,
            can_apply_update=can_apply,
            current_revision=self.current_revision,
            message="未检查远端容器镜像",
        )

    def _cached_metadata(self, db: Session | None) -> tuple[RegistryImageMetadata | None, str]:
        rows = _setting_rows(db, (_CACHE_KEY, _CACHE_CHECKED_KEY))
        try:
            payload = json.loads(rows.get(_CACHE_KEY, "")) if rows.get(_CACHE_KEY) else None
            metadata = RegistryImageMetadata.from_cache_dict(payload) if payload else None
        except (ValueError, json.JSONDecodeError):
            metadata = None
        return metadata, rows.get(_CACHE_CHECKED_KEY, "")

    def _status_from_metadata(
        self,
        metadata: RegistryImageMetadata,
        *,
        source: str,
        checked_at: str,
        message_suffix: str = "",
    ) -> UpdateStatus:
        result = self.local_status()
        result.latest_version = metadata.version
        result.latest_revision = metadata.revision
        result.latest_digest = metadata.digest
        result.platform_digest = metadata.platform_digest
        result.published_at = metadata.created_at
        result.manifest_url = metadata.manifest_url
        result.image_platform = "/".join(
            part for part in (metadata.operating_system, metadata.architecture) if part
        )
        result.source = source
        result.checked_at = checked_at

        if self.current_revision and metadata.revision:
            revision_changed = self.current_revision != metadata.revision
            version_changed = bool(
                metadata.version
                and self.current_version
                and is_newer_version(metadata.version, self.current_version)
            )
            result.update_available = revision_changed or version_changed
            if revision_changed:
                result.message = (
                    "发现新容器镜像："
                    f"{_short_revision(self.current_revision)} → {_short_revision(metadata.revision)}"
                )
            elif version_changed:
                result.message = (
                    "发现同一代码 revision 的新镜像构建："
                    f"{self.current_version} → {metadata.version}"
                )
            else:
                result.message = "当前运行镜像与远端标签一致"
        elif metadata.version and self.current_version:
            result.update_available = is_newer_version(metadata.version, self.current_version)
            result.message = (
                "发现新容器镜像（当前镜像缺少 revision，已按镜像版本判断）"
                if result.update_available
                else "远端镜像版本未高于当前版本；当前镜像缺少 revision，无法做精确摘要比较"
            )
        else:
            result.update_available = False
            result.message = "已读取远端镜像，但当前或远端镜像缺少 revision，暂时无法精确判断"

        if self.image_is_pinned:
            result.message += "；当前使用 digest 固定镜像，需修改 FEEDDOCK_IMAGE 后才能更新"
        elif result.update_available and not self.updater_configured:
            result.message += "；配置 Watchtower 后可在线更新"
        if message_suffix:
            result.message += f"；{message_suffix}"
        return result

    def check(self, db: Session | None = None, *, force: bool = False) -> UpdateStatus:
        cached, cached_at = self._cached_metadata(db)
        parsed_cached_at = _parse_datetime(cached_at)
        if cached is not None and parsed_cached_at is not None and not force:
            age = datetime.now(timezone.utc) - parsed_cached_at
            if age < timedelta(hours=settings.update_check_cache_hours):
                return self._status_from_metadata(
                    cached,
                    source="container-registry-cache",
                    checked_at=cached_at,
                    message_suffix=f"使用 {settings.update_check_cache_hours} 小时镜像缓存",
                )

        try:
            metadata = self.registry_client.inspect()
            now = datetime.now(timezone.utc).isoformat()
            _save_settings(
                db,
                {
                    _CACHE_KEY: json.dumps(metadata.as_cache_dict(), ensure_ascii=False, sort_keys=True),
                    _CACHE_CHECKED_KEY: now,
                },
            )
            return self._status_from_metadata(
                metadata,
                source="container-registry",
                checked_at=now,
            )
        except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
            if cached is not None:
                return self._status_from_metadata(
                    cached,
                    source="container-registry-stale-cache",
                    checked_at=cached_at,
                    message_suffix=f"远端镜像查询失败，显示上次缓存：{exc}",
                )
            result = self.local_status()
            result.message = f"查询远端容器镜像失败：{exc}"
            return result

    def trigger_update(self) -> tuple[bool, str]:
        if self.image_is_pinned:
            return False, "当前 FEEDDOCK_IMAGE 使用 digest 固定，Watchtower 无法将其更新到新标签"
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
            return True, "已触发 Watchtower 检查远端镜像；digest 变化时会拉取镜像并重建 FeedDock"
        except httpx.HTTPError as exc:
            return False, f"调用更新服务失败：{exc}"
