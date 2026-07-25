from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from .config import settings
from .runtime_config import load_qbittorrent_config


@dataclass(slots=True)
class DownloaderResult:
    ok: bool
    message: str


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
        self.base_url = ((runtime.url if runtime else settings.qbit_url) if base_url is None else base_url).strip().rstrip("/")
        self.username = (runtime.username if runtime else settings.qbit_username) if username is None else username
        self.password = (runtime.password if runtime else settings.qbit_password) if password is None else password
        self.timeout = settings.request_timeout_seconds if timeout is None else timeout
        self.category = (runtime.category if runtime else settings.qbit_category) if category is None else category

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
                return DownloaderResult(True, f"连接 qBittorrent 成功：{host}，版本 {version.text.strip()}")
        except httpx.HTTPError as exc:
            return DownloaderResult(False, f"连接失败：{exc}")

    def add_url(self, url: str, save_path: str, category: str | None = None) -> DownloaderResult:
        error = self._configuration_error()
        if error:
            return DownloaderResult(False, error)
        try:
            with self._client() as client:
                login = self._login(client)
                if not login.ok:
                    return login

                response = client.post(
                    "api/v2/torrents/add",
                    files={
                        "urls": (None, url),
                        "savepath": (None, save_path),
                        "category": (None, category or self.category),
                        "paused": (None, "false"),
                    },
                )
                if response.status_code != 200:
                    return DownloaderResult(False, f"添加任务失败：HTTP {response.status_code}")
                body = response.text.strip()
                if body not in {"Ok.", ""}:
                    return DownloaderResult(False, f"添加任务失败：{body}")
                return DownloaderResult(True, "任务已推送到 qBittorrent")
        except httpx.HTTPError as exc:
            return DownloaderResult(False, f"请求 qBittorrent 失败：{exc}")
