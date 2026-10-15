from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .image_registry import RegistryImageClient, RegistryImageMetadata
from .models import AppSetting


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
    current_build_source: str = ""
    current_created_at: str = ""
    metadata_consistent: bool = True

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
            "current_build_source": self.current_build_source,
            "current_created_at": self.current_created_at,
            "metadata_consistent": self.metadata_consistent,
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
    The running image carries immutable version and revision metadata in
    ``/app/.feeddock-build.json``. The remote tag's OCI config carries the same
    standard labels, so the two builds can be compared without mounting the
    Docker socket into FeedDock.
    """

    def __init__(
        self,
        *,
        image: str | None = None,
        current_version: str | None = None,
        current_revision: str | None = None,
        current_build_source: str | None = None,
        current_created_at: str | None = None,
        updater_url: str | None = None,
        updater_token: str | None = None,
        updater_token_file: str | Path | None = None,
        timeout: int | None = None,
        registry_scheme: str = "https",
        registry_username: str | None = None,
        registry_token: str | None = None,
        registry_client: RegistryImageClient | None = None,
    ) -> None:
        self.image = settings.deployed_image if image is None else image.strip()
        self.current_version = settings.app_version if current_version is None else current_version.strip()
        self.current_revision = settings.app_revision if current_revision is None else current_revision.strip()
        self.current_build_source = (
            settings.app_build_source
            if current_build_source is None
            else current_build_source.strip()
        )
        self.current_created_at = (
            settings.app_created_at
            if current_created_at is None
            else current_created_at.strip()
        )
        self.updater_url = settings.updater_url if updater_url is None else updater_url.rstrip("/")
        self.updater_token = settings.updater_token if updater_token is None else updater_token
        if updater_token_file is None:
            self.updater_token_file = settings.updater_token_file
        else:
            self.updater_token_file = Path(updater_token_file) if updater_token_file else None
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

    def _resolved_updater_token(self) -> str:
        if self.updater_token:
            return self.updater_token
        path = self.updater_token_file
        if path is None:
            return ""
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    @property
    def updater_configured(self) -> bool:
        return bool(self.updater_url and self._resolved_updater_token())

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
            current_build_source=self.current_build_source,
            current_created_at=self.current_created_at,
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
            immutable_local_metadata = self.current_build_source.startswith("image-file:")

            if revision_changed:
                result.update_available = True
                result.message = (
                    "发现新容器镜像："
                    f"{_short_revision(self.current_revision)} → {_short_revision(metadata.revision)}"
                )
            elif version_changed and immutable_local_metadata:
                # Same source commit, but a later immutable image build can still
                # contain a refreshed base image or dependency layer.
                result.update_available = True
                result.message = (
                    "发现同一代码 revision 的新镜像构建："
                    f"{self.current_version} → {metadata.version}"
                )
            elif version_changed:
                # Older deployments may expose APP_VERSION through the previous
                # container configuration. Treat it as a metadata inconsistency,
                # not proof that the running image is outdated.
                result.update_available = False
                result.metadata_consistent = False
                result.message = (
                    "当前代码 revision 已与远端一致，但本地版本标识来自容器环境变量："
                    f"{self.current_version} ≠ {metadata.version}；"
                    "请重新创建容器以刷新镜像内构建信息"
                )
            else:
                result.update_available = False
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
            result.message += "；启动 FeedDock 专用更新器后可在线更新"
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
            return False, "当前 FEEDDOCK_IMAGE 使用 digest 固定，无法自动更新到新标签"
        token = self._resolved_updater_token()
        if not self.updater_url or not token:
            return (
                False,
                "在线更新需要 FeedDock 专用更新器；请确认 updater 服务正在运行并可读取共享 Token",
            )
        try:
            # The updater is an internal Docker service. Never route this request
            # through the application's Internet proxy settings.
            with httpx.Client(
                timeout=max(self.timeout, 30),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = client.post(
                    f"{self.updater_url}/v1/update",
                    headers={"Authorization": f"Bearer {token}"},
                )
            if response.status_code == 409:
                return True, "FeedDock 更新任务已在执行，请稍后重新打开页面确认版本"
            if response.status_code not in {200, 202, 204}:
                body = response.text.strip()[:300]
                return False, f"更新服务返回 HTTP {response.status_code}{f'：{body}' if body else ''}"
            return True, "已启动 FeedDock 在线更新；专用更新器会拉取新镜像并只重建 FeedDock 容器"
        except httpx.RemoteProtocolError as exc:
            # Legacy updater implementations may close the connection as the
            # FeedDock container is being replaced. The request was already sent.
            return (
                True,
                "更新请求已发送，但更新器在返回响应前断开连接；FeedDock 可能正在被重建。"
                "请稍后重新打开页面确认版本"
                f"（{exc}）",
            )
        except httpx.HTTPError as exc:
            return False, f"调用更新服务失败：{exc}"
