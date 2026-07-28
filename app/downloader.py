from __future__ import annotations

import posixpath
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urlparse

import httpx

from .config import settings
from .naming import is_subtitle_file, is_video_file, safe_segment
from .runtime_config import load_qbittorrent_config


@dataclass(slots=True)
class DownloaderResult:
    ok: bool
    message: str
    torrent_hash: str = ""
    torrent_name: str = ""
    verified: bool = False
    tag_removed: bool = False


@dataclass(slots=True)
class InternalTagCleanupResult:
    ok: bool
    message: str
    cleaned_tags: tuple[str, ...] = ()
    resolved_hashes: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class TorrentNormalizeResult:
    ok: bool
    state: str
    message: str
    torrent_hash: str = ""
    completed: bool = False
    progress: int = 0
    completed_at: datetime | None = None


class QBittorrentClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout: int | None = None,
        category: str | None = None,
    ) -> None:
        runtime = load_qbittorrent_config() if base_url is None else None
        self.base_url = (
            (runtime.url if runtime else settings.qbit_url) if base_url is None else base_url
        ).strip().rstrip("/")
        self.username = (
            (runtime.username if runtime else settings.qbit_username)
            if username is None
            else username
        )
        self.password = (
            (runtime.password if runtime else settings.qbit_password)
            if password is None
            else password
        )
        self.timeout = settings.request_timeout_seconds if timeout is None else timeout
        self.category = (
            (runtime.category if runtime else settings.qbit_category)
            if category is None
            else category
        )

    def _configuration_error(self) -> str:
        if not self.base_url:
            return "QBIT_URL 尚未配置"
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return "QBIT_URL 必须是有效的 HTTP 或 HTTPS 地址"
        if not self.username:
            return "QBIT_USERNAME 尚未配置"
        if not self.password:
            return "QBIT_PASSWORD 尚未配置"
        return ""

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=f"{self.base_url}/",
            timeout=self.timeout,
            follow_redirects=True,
            headers={"Referer": f"{self.base_url}/", "Origin": self.base_url},
        )

    def _login(self, client: httpx.Client) -> DownloaderResult:
        login = client.post(
            "api/v2/auth/login",
            data={"username": self.username, "password": self.password},
        )
        if login.status_code != 200 or login.text.strip() != "Ok.":
            return DownloaderResult(False, f"qBittorrent 登录失败：HTTP {login.status_code}")
        return DownloaderResult(True, "登录成功")

    def test(self) -> DownloaderResult:
        error = self._configuration_error()
        if error:
            return DownloaderResult(False, error)
        try:
            with self._client() as client:
                login = self._login(client)
                if not login.ok:
                    return login
                version = client.get("api/v2/app/version")
                version.raise_for_status()
                host = urlparse(self.base_url).netloc
                return DownloaderResult(
                    True, f"连接 qBittorrent 成功：{host}，版本 {version.text.strip()}"
                )
        except httpx.HTTPError as exc:
            return DownloaderResult(False, f"连接失败：{exc}")

    @staticmethod
    def _add_form_fields(
        *,
        save_path: str,
        category: str,
        rename: str,
        tags_value: str,
        seeding_minutes: int,
    ) -> dict[str, str]:
        fields = {
            "savepath": save_path,
            "category": category,
            "paused": "false",
        }
        if rename:
            fields["rename"] = safe_segment(rename)
        if tags_value:
            fields["tags"] = tags_value
        if seeding_minutes >= 0:
            fields["seedingTimeLimit"] = str(seeding_minutes)
        return fields

    @staticmethod
    def _response_error(response: httpx.Response) -> str:
        if response.status_code != 200:
            return f"添加任务失败：HTTP {response.status_code}"
        body = response.text.strip()
        if body not in {"Ok.", ""}:
            return f"添加任务失败：{body}"
        return ""

    def _verify_added_torrent(
        self,
        client: httpx.Client,
        *,
        tag: str,
        attempts: int = 10,
        interval: float = 0.3,
    ) -> DownloaderResult:
        if not tag:
            return DownloaderResult(
                True,
                "qBittorrent 已接受添加请求，但缺少任务标签，无法确认任务是否建立",
                verified=False,
            )

        last_error = ""
        for attempt in range(max(1, attempts)):
            try:
                response = client.get(
                    "api/v2/torrents/info",
                    params={"tag": tag, "sort": "added_on", "reverse": "true"},
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, list):
                    last_error = "qBittorrent 返回了无效的任务列表"
                elif payload:
                    torrent = payload[0]
                    torrent_hash = str(torrent.get("hash") or "").strip()
                    torrent_name = str(torrent.get("name") or "").strip()
                    state = str(torrent.get("state") or "").strip()
                    message = "qBittorrent 已确认任务"
                    if torrent_name:
                        message += f"：{torrent_name}"
                    if state:
                        message += f"；状态：{state}"
                    return DownloaderResult(
                        True,
                        message,
                        torrent_hash=torrent_hash,
                        torrent_name=torrent_name,
                        verified=True,
                    )
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                last_error = str(exc)
            if attempt + 1 < attempts:
                time.sleep(interval)

        detail = f"；回查错误：{last_error}" if last_error else ""
        return DownloaderResult(
            False,
            "qBittorrent 添加接口返回成功，但未在任务列表中找到新任务"
            f"（标签：{tag}）{detail}",
            verified=False,
        )

    @staticmethod
    def _cleanup_verified_tag(
        client: httpx.Client,
        *,
        tag: str,
        torrent_hash: str,
    ) -> DownloaderResult:
        """Remove one temporary FeedDock tag after the torrent hash is known."""

        if not tag:
            return DownloaderResult(True, "没有临时标签需要清理", tag_removed=True)
        if not torrent_hash:
            return DownloaderResult(False, "任务哈希为空，暂时保留临时标签")

        remove_response = client.post(
            "api/v2/torrents/removeTags",
            data={"hashes": torrent_hash, "tags": tag},
        )
        if remove_response.status_code != 200:
            return DownloaderResult(
                False, f"移除临时标签失败：HTTP {remove_response.status_code}"
            )

        delete_response = client.post(
            "api/v2/torrents/deleteTags",
            data={"tags": tag},
        )
        if delete_response.status_code != 200:
            return DownloaderResult(
                False, f"删除临时标签失败：HTTP {delete_response.status_code}"
            )
        return DownloaderResult(True, "临时标签已清理", tag_removed=True)

    def _finish_add(
        self,
        client: httpx.Client,
        response: httpx.Response,
        *,
        tag: str,
        rename: str,
    ) -> DownloaderResult:
        error = self._response_error(response)
        if error:
            return DownloaderResult(False, error)
        verified = self._verify_added_torrent(client, tag=tag)
        if verified.ok and rename and not verified.torrent_name:
            verified.message += f"；请求名称：{safe_segment(rename)}"
        if verified.ok and tag:
            cleanup = self._cleanup_verified_tag(
                client, tag=tag, torrent_hash=verified.torrent_hash
            )
            verified.tag_removed = cleanup.tag_removed
            if cleanup.ok:
                verified.message += "；临时标签已清理"
            else:
                verified.message += f"；临时标签稍后清理：{cleanup.message}"
        return verified

    def add_url(
        self,
        url: str,
        save_path: str,
        category: str | None = None,
        *,
        rename: str = "",
        tags: str | Iterable[str] = "",
        seeding_minutes: int = -1,
    ) -> DownloaderResult:
        error = self._configuration_error()
        if error:
            return DownloaderResult(False, error)
        if isinstance(tags, str):
            tags_value = tags.strip()
        else:
            tags_value = ",".join(value.strip() for value in tags if value.strip())
        try:
            with self._client() as client:
                login = self._login(client)
                if not login.ok:
                    return login
                fields = self._add_form_fields(
                    save_path=save_path,
                    category=category or self.category,
                    rename=rename,
                    tags_value=tags_value,
                    seeding_minutes=seeding_minutes,
                )
                files = {key: (None, value) for key, value in fields.items()}
                files["urls"] = (None, url)
                response = client.post("api/v2/torrents/add", files=files)
                return self._finish_add(
                    client, response, tag=tags_value.split(",", 1)[0].strip(), rename=rename
                )
        except httpx.HTTPError as exc:
            return DownloaderResult(False, f"请求 qBittorrent 失败：{exc}")

    def add_torrent(
        self,
        content: bytes,
        filename: str,
        save_path: str,
        category: str | None = None,
        *,
        rename: str = "",
        tags: str | Iterable[str] = "",
        seeding_minutes: int = -1,
    ) -> DownloaderResult:
        error = self._configuration_error()
        if error:
            return DownloaderResult(False, error)
        if not content:
            return DownloaderResult(False, "种子文件内容为空")
        if isinstance(tags, str):
            tags_value = tags.strip()
        else:
            tags_value = ",".join(value.strip() for value in tags if value.strip())
        try:
            with self._client() as client:
                login = self._login(client)
                if not login.ok:
                    return login
                data = self._add_form_fields(
                    save_path=save_path,
                    category=category or self.category,
                    rename=rename,
                    tags_value=tags_value,
                    seeding_minutes=seeding_minutes,
                )
                response = client.post(
                    "api/v2/torrents/add",
                    data=data,
                    files={
                        "torrents": (
                            safe_segment(filename or "feeddock.torrent"),
                            content,
                            "application/x-bittorrent",
                        )
                    },
                )
                return self._finish_add(
                    client, response, tag=tags_value.split(",", 1)[0].strip(), rename=rename
                )
        except httpx.HTTPError as exc:
            return DownloaderResult(False, f"请求 qBittorrent 失败：{exc}")


    def remove_internal_tag(self, *, tag: str, torrent_hash: str) -> DownloaderResult:
        """Retry removal of one temporary internal tag without affecting the torrent."""

        error = self._configuration_error()
        if error:
            return DownloaderResult(False, error)
        if not tag:
            return DownloaderResult(True, "没有临时标签需要清理", tag_removed=True)
        try:
            with self._client() as client:
                login = self._login(client)
                if not login.ok:
                    return login
                return self._cleanup_verified_tag(
                    client, tag=tag, torrent_hash=torrent_hash
                )
        except httpx.HTTPError as exc:
            return DownloaderResult(False, f"清理临时标签请求失败：{exc}")

    def cleanup_internal_tags(
        self,
        *,
        prefix: str = "feeddock-item-",
        batch_size: int = 100,
    ) -> InternalTagCleanupResult:
        """Resolve torrent hashes and remove legacy FeedDock item tags in batches."""

        error = self._configuration_error()
        if error:
            return InternalTagCleanupResult(False, error)
        try:
            with self._client() as client:
                login = self._login(client)
                if not login.ok:
                    return InternalTagCleanupResult(False, login.message)

                tags_response = client.get("api/v2/torrents/tags")
                tags_response.raise_for_status()
                payload = tags_response.json()
                if not isinstance(payload, list):
                    return InternalTagCleanupResult(
                        False, "qBittorrent 返回了无效的标签列表"
                    )
                tags = sorted(
                    {str(value).strip() for value in payload if str(value).strip().startswith(prefix)}
                )
                if not tags:
                    return InternalTagCleanupResult(True, "没有需要清理的 FeedDock 临时标签")

                resolved_hashes: dict[str, str] = {}
                torrents_response = client.get(
                    "api/v2/torrents/info",
                    params={"sort": "added_on", "reverse": "true"},
                )
                torrents_response.raise_for_status()
                torrents = torrents_response.json()
                if not isinstance(torrents, list):
                    return InternalTagCleanupResult(
                        False, "qBittorrent 返回了无效的任务列表"
                    )
                known_tags = set(tags)
                for torrent in torrents:
                    torrent_hash = str(torrent.get("hash") or "").strip()
                    raw_tags = torrent.get("tags") or ""
                    if isinstance(raw_tags, str):
                        torrent_tags = {value.strip() for value in raw_tags.split(",") if value.strip()}
                    elif isinstance(raw_tags, list):
                        torrent_tags = {str(value).strip() for value in raw_tags if str(value).strip()}
                    else:
                        torrent_tags = set()
                    for tag in torrent_tags & known_tags:
                        if torrent_hash and tag not in resolved_hashes:
                            resolved_hashes[tag] = torrent_hash

                cleaned: list[str] = []
                failures: list[str] = []
                size = max(1, int(batch_size or 100))
                for offset in range(0, len(tags), size):
                    batch = tags[offset : offset + size]
                    joined = ",".join(batch)
                    remove_response = client.post(
                        "api/v2/torrents/removeTags",
                        data={"hashes": "all", "tags": joined},
                    )
                    if remove_response.status_code != 200:
                        failures.append(
                            f"移除 {len(batch)} 个标签失败：HTTP {remove_response.status_code}"
                        )
                        continue
                    delete_response = client.post(
                        "api/v2/torrents/deleteTags",
                        data={"tags": joined},
                    )
                    if delete_response.status_code != 200:
                        failures.append(
                            f"删除 {len(batch)} 个标签失败：HTTP {delete_response.status_code}"
                        )
                        continue
                    cleaned.extend(batch)

                if failures:
                    return InternalTagCleanupResult(
                        False,
                        f"已清理 {len(cleaned)} 个标签；" + "；".join(failures),
                        tuple(cleaned),
                        resolved_hashes,
                    )
                return InternalTagCleanupResult(
                    True,
                    f"已清理 {len(cleaned)} 个 FeedDock 临时标签",
                    tuple(cleaned),
                    resolved_hashes,
                )
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            return InternalTagCleanupResult(False, f"清理 FeedDock 临时标签失败：{exc}")

    def active_download_count(self) -> tuple[bool, int, str]:
        error = self._configuration_error()
        if error:
            return False, 0, error
        try:
            with self._client() as client:
                login = self._login(client)
                if not login.ok:
                    return False, 0, login.message
                response = client.get(
                    "api/v2/torrents/info",
                    params={"filter": "downloading", "category": self.category},
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, list):
                    return False, 0, "qBittorrent 返回了无效的任务列表"
                return True, len(payload), "已读取活动下载数"
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            return False, 0, f"读取活动下载数失败：{exc}"

    def delete_torrent_record(self, torrent_hash: str) -> DownloaderResult:
        """Remove a qBittorrent task while explicitly preserving its files.

        qBittorrent's delete endpoint can also remove downloaded data.  FeedDock
        always sends ``deleteFiles=false`` here so this cleanup only removes the
        WebUI task/history record from qBittorrent.
        """

        error = self._configuration_error()
        if error:
            return DownloaderResult(False, error)
        normalized_hash = str(torrent_hash or "").strip()
        if not normalized_hash:
            return DownloaderResult(False, "任务哈希为空")
        try:
            with self._client() as client:
                login = self._login(client)
                if not login.ok:
                    return login
                response = client.post(
                    "api/v2/torrents/delete",
                    data={"hashes": normalized_hash, "deleteFiles": "false"},
                )
                if response.status_code != 200:
                    return DownloaderResult(
                        False,
                        f"删除 qBittorrent 任务记录失败：HTTP {response.status_code}",
                    )
                return DownloaderResult(True, "qBittorrent 任务记录已删除，下载文件已保留")
        except httpx.HTTPError as exc:
            return DownloaderResult(False, f"删除 qBittorrent 任务记录请求失败：{exc}")

    def add_trackers(self, torrent_hash: str, trackers: Iterable[str]) -> DownloaderResult:
        error = self._configuration_error()
        if error:
            return DownloaderResult(False, error)
        values = [str(value).strip() for value in trackers if str(value).strip()]
        if not torrent_hash:
            return DownloaderResult(False, "任务哈希为空")
        if not values:
            return DownloaderResult(True, "没有需要添加的 Tracker")
        try:
            with self._client() as client:
                login = self._login(client)
                if not login.ok:
                    return login
                response = client.post(
                    "api/v2/torrents/addTrackers",
                    data={"hash": torrent_hash, "urls": "\n".join(values)},
                )
                if response.status_code != 200:
                    return DownloaderResult(False, f"添加 Tracker 失败：HTTP {response.status_code}")
                return DownloaderResult(True, f"已添加 {len(values)} 个 Tracker")
        except httpx.HTTPError as exc:
            return DownloaderResult(False, f"添加 Tracker 请求失败：{exc}")

    def normalize_single_video(
        self,
        *,
        tag: str = "",
        torrent_hash: str = "",
        desired_name: str = "",
    ) -> TorrentNormalizeResult:
        """Inspect one FeedDock torrent by hash (preferred) or temporary tag.

        Renaming may happen as soon as magnet metadata is available, but local
        scraping is intentionally deferred until qBittorrent reports 100%.
        Multi-video packs are never guessed; they may still be scraped after
        completion because series-level NFO files do not require file renaming.
        """

        error = self._configuration_error()
        if error:
            return TorrentNormalizeResult(False, "error", error)
        if not torrent_hash and not tag:
            return TorrentNormalizeResult(False, "skipped", "没有任务哈希或临时标签")

        try:
            with self._client() as client:
                login = self._login(client)
                if not login.ok:
                    return TorrentNormalizeResult(False, "error", login.message)
                lookup_params = {"hashes": torrent_hash} if torrent_hash else {"tag": tag}
                torrents_response = client.get("api/v2/torrents/info", params=lookup_params)
                torrents_response.raise_for_status()
                torrents = torrents_response.json()
                if not isinstance(torrents, list) or not torrents:
                    return TorrentNormalizeResult(False, "pending", "等待 qBittorrent 建立任务")
                torrent = sorted(
                    torrents,
                    key=lambda value: int(value.get("added_on") or 0),
                    reverse=True,
                )[0]
                resolved_hash = str(torrent.get("hash") or "")
                if not resolved_hash:
                    return TorrentNormalizeResult(False, "pending", "等待 qBittorrent 返回任务哈希")

                try:
                    progress_value = max(0.0, min(1.0, float(torrent.get("progress") or 0.0)))
                except (TypeError, ValueError):
                    progress_value = 0.0
                progress = int(round(progress_value * 100))
                amount_left = torrent.get("amount_left")
                state_name = str(torrent.get("state") or "")
                completed = progress_value >= 0.999999 or (
                    amount_left is not None
                    and int(amount_left or 0) == 0
                    and state_name not in {"metaDL", "checkingResumeData", "unknown"}
                )
                completed_at: datetime | None = None
                if completed:
                    try:
                        completion_timestamp = int(torrent.get("completion_on") or 0)
                    except (TypeError, ValueError):
                        completion_timestamp = 0
                    if completion_timestamp > 0:
                        completed_at = datetime.fromtimestamp(
                            completion_timestamp,
                            tz=timezone.utc,
                        )

                files_response = client.get(
                    "api/v2/torrents/files", params={"hash": resolved_hash}
                )
                files_response.raise_for_status()
                files = files_response.json()
                if not isinstance(files, list) or not files:
                    return TorrentNormalizeResult(
                        False,
                        "pending",
                        "磁力链接元数据尚未获取",
                        resolved_hash,
                        completed,
                        progress,
                        completed_at,
                    )
                videos = [file for file in files if is_video_file(str(file.get("name") or ""))]
                if not videos:
                    state = "completed_no_video" if completed else "waiting_completion"
                    return TorrentNormalizeResult(
                        False,
                        state,
                        "暂未发现视频文件",
                        resolved_hash,
                        completed,
                        progress,
                        completed_at,
                    )

                rename_message = ""
                manual_required = False
                if desired_name:
                    if len(videos) > 1:
                        manual_required = True
                        rename_message = f"检测到 {len(videos)} 个视频文件，已保留原文件名"
                    else:
                        video_path = str(videos[0].get("name") or "")
                        directory, filename = posixpath.split(video_path)
                        old_stem, extension = posixpath.splitext(filename)
                        target_stem = safe_segment(desired_name)
                        new_video_path = posixpath.join(directory, target_stem + extension)
                        if video_path != new_video_path:
                            rename_response = client.post(
                                "api/v2/torrents/renameFile",
                                data={
                                    "hash": resolved_hash,
                                    "oldPath": video_path,
                                    "newPath": new_video_path,
                                },
                            )
                            if rename_response.status_code != 200:
                                return TorrentNormalizeResult(
                                    False,
                                    "error",
                                    f"视频文件重命名失败：HTTP {rename_response.status_code}",
                                    resolved_hash,
                                    completed,
                                    progress,
                                )

                        subtitle_count = 0
                        for file in files:
                            subtitle_path = str(file.get("name") or "")
                            if not is_subtitle_file(subtitle_path):
                                continue
                            subtitle_dir, subtitle_filename = posixpath.split(subtitle_path)
                            if subtitle_dir != directory:
                                continue
                            subtitle_stem, subtitle_ext = posixpath.splitext(subtitle_filename)
                            if not subtitle_stem.startswith(old_stem):
                                continue
                            suffix = subtitle_stem[len(old_stem) :]
                            new_subtitle_path = posixpath.join(
                                subtitle_dir, target_stem + suffix + subtitle_ext
                            )
                            if subtitle_path == new_subtitle_path:
                                continue
                            response = client.post(
                                "api/v2/torrents/renameFile",
                                data={
                                    "hash": resolved_hash,
                                    "oldPath": subtitle_path,
                                    "newPath": new_subtitle_path,
                                },
                            )
                            if response.status_code == 200:
                                subtitle_count += 1

                        rename_message = f"已规范化为 {target_stem + extension}"
                        if subtitle_count:
                            rename_message += f"，并同步重命名 {subtitle_count} 个字幕"

                if completed:
                    state = "manual_required" if manual_required else "completed"
                    message = rename_message or "下载已完成"
                    if rename_message:
                        message += "；下载已完成"
                    return TorrentNormalizeResult(
                        True,
                        state,
                        message,
                        resolved_hash,
                        True,
                        100,
                        completed_at,
                    )

                state = "manual_required_waiting" if manual_required else "waiting_completion"
                message = rename_message or "任务已建立"
                message += f"；等待下载完成（{progress}%）"
                return TorrentNormalizeResult(
                    True, state, message, resolved_hash, False, progress
                )
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            return TorrentNormalizeResult(False, "error", f"重命名或完成状态检查失败：{exc}")
