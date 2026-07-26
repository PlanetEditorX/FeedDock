from __future__ import annotations

import posixpath
from dataclasses import dataclass
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


@dataclass(slots=True)
class TorrentNormalizeResult:
    ok: bool
    state: str
    message: str
    torrent_hash: str = ""
    completed: bool = False
    progress: int = 0


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

    def add_url(
        self,
        url: str,
        save_path: str,
        category: str | None = None,
        *,
        rename: str = "",
        tags: str | Iterable[str] = "",
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

                files: dict[str, tuple[None, str]] = {
                    "urls": (None, url),
                    "savepath": (None, save_path),
                    "category": (None, category or self.category),
                    "paused": (None, "false"),
                }
                if rename:
                    files["rename"] = (None, safe_segment(rename))
                if tags_value:
                    files["tags"] = (None, tags_value)
                response = client.post("api/v2/torrents/add", files=files)
                if response.status_code != 200:
                    return DownloaderResult(False, f"添加任务失败：HTTP {response.status_code}")
                body = response.text.strip()
                if body not in {"Ok.", ""}:
                    return DownloaderResult(False, f"添加任务失败：{body}")
                message = "任务已推送到 qBittorrent"
                if rename:
                    message += f"；任务名称：{safe_segment(rename)}"
                return DownloaderResult(True, message)
        except httpx.HTTPError as exc:
            return DownloaderResult(False, f"请求 qBittorrent 失败：{exc}")

    def normalize_single_video(self, *, tag: str, desired_name: str = "") -> TorrentNormalizeResult:
        """Inspect one tagged torrent, normalize a single video, and report completion.

        Renaming may happen as soon as magnet metadata is available, but local
        completion tracking is intentionally deferred until qBittorrent reports 100%.
        Multi-video packs are never guessed; they remain available for manual naming after
        completion because series-level NFO files do not require file renaming.
        """

        error = self._configuration_error()
        if error:
            return TorrentNormalizeResult(False, "error", error)
        if not tag:
            return TorrentNormalizeResult(False, "skipped", "没有任务标签")

        try:
            with self._client() as client:
                login = self._login(client)
                if not login.ok:
                    return TorrentNormalizeResult(False, "error", login.message)
                torrents_response = client.get("api/v2/torrents/info", params={"tag": tag})
                torrents_response.raise_for_status()
                torrents = torrents_response.json()
                if not isinstance(torrents, list) or not torrents:
                    return TorrentNormalizeResult(False, "pending", "等待 qBittorrent 建立任务")
                torrent = sorted(
                    torrents,
                    key=lambda value: int(value.get("added_on") or 0),
                    reverse=True,
                )[0]
                torrent_hash = str(torrent.get("hash") or "")
                if not torrent_hash:
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

                files_response = client.get(
                    "api/v2/torrents/files", params={"hash": torrent_hash}
                )
                files_response.raise_for_status()
                files = files_response.json()
                if not isinstance(files, list) or not files:
                    return TorrentNormalizeResult(
                        False, "pending", "磁力链接元数据尚未获取", torrent_hash, completed, progress
                    )
                videos = [file for file in files if is_video_file(str(file.get("name") or ""))]
                if not videos:
                    state = "completed_no_video" if completed else "waiting_completion"
                    return TorrentNormalizeResult(
                        False, state, "暂未发现视频文件", torrent_hash, completed, progress
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
                                    "hash": torrent_hash,
                                    "oldPath": video_path,
                                    "newPath": new_video_path,
                                },
                            )
                            if rename_response.status_code != 200:
                                return TorrentNormalizeResult(
                                    False,
                                    "error",
                                    f"视频文件重命名失败：HTTP {rename_response.status_code}",
                                    torrent_hash,
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
                                    "hash": torrent_hash,
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
                        True, state, message, torrent_hash, True, 100
                    )

                state = "manual_required_waiting" if manual_required else "waiting_completion"
                message = rename_message or "任务已建立"
                message += f"；等待下载完成（{progress}%）"
                return TorrentNormalizeResult(
                    True, state, message, torrent_hash, False, progress
                )
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            return TorrentNormalizeResult(False, "error", f"重命名或完成状态检查失败：{exc}")
