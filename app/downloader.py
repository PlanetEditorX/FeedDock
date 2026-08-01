from __future__ import annotations

import base64
import hashlib
import posixpath
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse

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
    retryable: bool = True


@dataclass(slots=True)
class _AddResponseOutcome:
    accepted: bool
    message: str
    torrent_ids: tuple[str, ...] = ()
    retryable: bool = True


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
    media_filename: str = ""
    download_path: str = ""


@dataclass(slots=True)
class TorrentRelocateResult:
    ok: bool
    found: bool
    moved: bool
    message: str
    download_path: str = ""


class QBittorrentClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        auth_mode: str | None = None,
        username: str | None = None,
        password: str | None = None,
        api_key: str | None = None,
        timeout: int | None = None,
        category: str | None = None,
    ) -> None:
        runtime = load_qbittorrent_config() if base_url is None else None
        self.base_url = (
            (runtime.url if runtime else settings.qbit_url) if base_url is None else base_url
        ).strip().rstrip("/")
        self.auth_mode = (
            (runtime.auth_mode if runtime else settings.qbit_auth_mode)
            if auth_mode is None
            else auth_mode
        ).strip().lower()
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
        self.api_key = (
            (runtime.api_key if runtime else settings.qbit_api_key)
            if api_key is None
            else api_key
        ).strip()
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
        if self.auth_mode not in {"password", "api_key"}:
            return "QBIT_AUTH_MODE 必须是 password 或 api_key"
        if self.auth_mode == "api_key":
            if not self.api_key:
                return "QBIT_API_KEY 尚未配置"
            if len(self.api_key) != 32 or not self.api_key.startswith("qbt_"):
                return "QBIT_API_KEY 格式无效，应为 qbt_ 开头的 32 位密钥"
            return ""
        if not self.username:
            return "QBIT_USERNAME 尚未配置"
        if not self.password:
            return "QBIT_PASSWORD 尚未配置"
        return ""

    def _client(self) -> httpx.Client:
        headers = {"Referer": f"{self.base_url}/", "Origin": self.base_url}
        if self.auth_mode == "api_key" and self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return httpx.Client(
            base_url=f"{self.base_url}/",
            timeout=self.timeout,
            follow_redirects=True,
            headers=headers,
        )

    def _login(self, client: httpx.Client) -> DownloaderResult:
        if self.auth_mode == "api_key":
            # API-key authentication is stateless and qBittorrent explicitly
            # rejects API keys on the login/logout endpoints. The Bearer header
            # is attached to every request by ``_client`` instead.
            return DownloaderResult(True, "API 密钥认证已启用")
        login = client.post(
            "api/v2/auth/login",
            data={"username": self.username, "password": self.password},
        )
        body = login.text.strip()
        # Older qBittorrent versions return ``200 Ok.`` while newer WebAPI
        # versions may return ``204 No Content`` (or ``200`` with an empty
        # body).  Invalid credentials on legacy versions can still be a
        # ``200 Fails.`` response, so do not accept every 2xx blindly here.
        if login.status_code == 204 or (
            login.status_code == 200 and body in {"", "Ok."}
        ):
            return DownloaderResult(True, "登录成功")
        detail = f"：{body}" if body else ""
        return DownloaderResult(
            False, f"qBittorrent 登录失败：HTTP {login.status_code}{detail}"
        )

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
                if self.auth_mode == "api_key" and version.status_code in {401, 403}:
                    return DownloaderResult(
                        False,
                        "qBittorrent API 密钥认证失败，请确认密钥有效且版本不低于 5.2.0",
                    )
                version.raise_for_status()
                host = urlparse(self.base_url).netloc
                auth_label = "API 密钥" if self.auth_mode == "api_key" else "账号密码"
                return DownloaderResult(
                    True,
                    f"连接 qBittorrent 成功：{host}，版本 {version.text.strip()}，认证方式：{auth_label}",
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
    def _add_response_outcome(response: httpx.Response) -> _AddResponseOutcome:
        """Normalize legacy and WebAPI 2.14+ torrent-add responses."""

        status = response.status_code
        body = response.text.strip()
        payload: Any = None
        try:
            payload = response.json()
        except (ValueError, TypeError):
            payload = None

        if isinstance(payload, dict) and any(
            key in payload
            for key in ("success_count", "pending_count", "failure_count", "added_torrent_ids")
        ):
            def _count(key: str) -> int:
                try:
                    return max(0, int(payload.get(key, 0) or 0))
                except (TypeError, ValueError):
                    return 0

            success_count = _count("success_count")
            pending_count = _count("pending_count")
            failure_count = _count("failure_count")
            raw_ids = payload.get("added_torrent_ids") or []
            if not isinstance(raw_ids, list):
                raw_ids = []
            torrent_ids = tuple(
                str(value).strip().lower() for value in raw_ids if str(value).strip()
            )
            counts = (
                f"成功 {success_count}，等待 {pending_count}，失败 {failure_count}"
            )
            if 200 <= status < 300 and (success_count > 0 or pending_count > 0):
                return _AddResponseOutcome(
                    True,
                    f"qBittorrent 已接受添加请求（{counts}）",
                    torrent_ids=torrent_ids,
                )
            if status == 409 or failure_count > 0:
                return _AddResponseOutcome(
                    False,
                    f"添加任务失败：qBittorrent 拒绝了全部任务（HTTP {status}；{counts}）",
                    torrent_ids=torrent_ids,
                    retryable=False,
                )

        if 200 <= status < 300:
            if body in {"", "Ok."}:
                return _AddResponseOutcome(True, "qBittorrent 已接受添加请求")
            return _AddResponseOutcome(
                False,
                f"添加任务失败：{body[:500]}",
                retryable=False,
            )

        detail = f"；响应：{body[:500]}" if body else ""
        retryable = status >= 500 or status in {408, 425, 429}
        return _AddResponseOutcome(
            False,
            f"添加任务失败：HTTP {status}{detail}",
            retryable=retryable,
        )

    @staticmethod
    def _bencode_value_end(data: bytes, start: int, *, depth: int = 0) -> int:
        if depth > 100 or start >= len(data):
            raise ValueError("无效的种子元数据")
        marker = data[start : start + 1]
        if marker == b"i":
            end = data.find(b"e", start + 1)
            if end < 0:
                raise ValueError("无效的整数编码")
            return end + 1
        if marker in {b"l", b"d"}:
            position = start + 1
            while position < len(data) and data[position : position + 1] != b"e":
                position = QBittorrentClient._bencode_value_end(
                    data, position, depth=depth + 1
                )
                if marker == b"d":
                    position = QBittorrentClient._bencode_value_end(
                        data, position, depth=depth + 1
                    )
            if position >= len(data):
                raise ValueError("无效的列表或字典编码")
            return position + 1
        if marker.isdigit():
            colon = data.find(b":", start)
            if colon < 0:
                raise ValueError("无效的字符串编码")
            try:
                length = int(data[start:colon])
            except ValueError as exc:
                raise ValueError("无效的字符串长度") from exc
            end = colon + 1 + length
            if length < 0 or end > len(data):
                raise ValueError("种子字符串超出数据范围")
            return end
        raise ValueError("未知的 bencode 类型")

    @staticmethod
    def _read_bencoded_string(data: bytes, start: int) -> tuple[bytes, int]:
        colon = data.find(b":", start)
        if colon < 0:
            raise ValueError("无效的字典键")
        try:
            length = int(data[start:colon])
        except ValueError as exc:
            raise ValueError("无效的字典键长度") from exc
        value_start = colon + 1
        value_end = value_start + length
        if length < 0 or value_end > len(data):
            raise ValueError("字典键超出数据范围")
        return data[value_start:value_end], value_end

    @classmethod
    def _torrent_hash_candidates(cls, content: bytes) -> tuple[str, ...]:
        """Return possible v1/v2 info hashes without adding a bencode dependency."""

        try:
            if not content.startswith(b"d"):
                return ()
            position = 1
            info_bytes = b""
            while position < len(content) and content[position : position + 1] != b"e":
                key, position = cls._read_bencoded_string(content, position)
                value_start = position
                position = cls._bencode_value_end(content, position)
                if key == b"info":
                    info_bytes = content[value_start:position]
                    break
            if not info_bytes:
                return ()
            return (
                hashlib.sha1(info_bytes).hexdigest(),
                hashlib.sha256(info_bytes).hexdigest(),
            )
        except (ValueError, IndexError):
            return ()

    @staticmethod
    def _magnet_hash_candidates(url: str) -> tuple[str, ...]:
        parsed = urlparse(url)
        if parsed.scheme.lower() != "magnet":
            return ()
        candidates: list[str] = []
        for xt in parse_qs(parsed.query).get("xt", []):
            lowered = xt.strip().lower()
            if lowered.startswith("urn:btih:"):
                value = xt.rsplit(":", 1)[-1].strip()
                if len(value) == 40:
                    try:
                        bytes.fromhex(value)
                    except ValueError:
                        continue
                    candidates.append(value.lower())
                elif len(value) == 32:
                    try:
                        decoded = base64.b32decode(value.upper())
                    except (ValueError, base64.binascii.Error):
                        continue
                    candidates.append(decoded.hex())
            elif lowered.startswith("urn:btmh:1220"):
                value = lowered.removeprefix("urn:btmh:1220")
                if len(value) == 64:
                    try:
                        bytes.fromhex(value)
                    except ValueError:
                        continue
                    candidates.append(value)
        return tuple(dict.fromkeys(candidates))

    @staticmethod
    def _result_from_torrent(
        torrent: dict[str, Any], *, prefix: str = "qBittorrent 已确认任务"
    ) -> DownloaderResult:
        torrent_hash = str(torrent.get("hash") or "").strip()
        torrent_name = str(torrent.get("name") or "").strip()
        state = str(torrent.get("state") or "").strip()
        message = prefix
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

    def _find_existing_torrent(
        self,
        client: httpx.Client,
        *,
        torrent_hashes: Iterable[str] = (),
        expected_name: str = "",
    ) -> DownloaderResult | None:
        hashes = tuple(
            dict.fromkeys(
                value.strip().lower() for value in torrent_hashes if value.strip()
            )
        )
        try:
            if hashes:
                response = client.get(
                    "api/v2/torrents/info", params={"hashes": "|".join(hashes)}
                )
                response.raise_for_status()
                payload = response.json()
                if isinstance(payload, list) and payload:
                    by_hash = {
                        str(item.get("hash") or "").strip().lower(): item
                        for item in payload
                        if isinstance(item, dict)
                    }
                    for value in hashes:
                        if value in by_hash:
                            return self._result_from_torrent(
                                by_hash[value],
                                prefix="qBittorrent 中已存在相同任务，已复用",
                            )
                    first = next((item for item in payload if isinstance(item, dict)), None)
                    if first is not None:
                        return self._result_from_torrent(
                            first, prefix="qBittorrent 中已存在相同任务，已复用"
                        )

            normalized_name = safe_segment(expected_name).strip().casefold()
            if normalized_name:
                response = client.get("api/v2/torrents/info", params={"filter": "all"})
                response.raise_for_status()
                payload = response.json()
                if isinstance(payload, list):
                    for torrent in payload:
                        if not isinstance(torrent, dict):
                            continue
                        name = str(torrent.get("name") or "").strip()
                        if name.casefold() == normalized_name:
                            return self._result_from_torrent(
                                torrent,
                                prefix="qBittorrent 中已存在同名任务，已复用",
                            )
        except (httpx.HTTPError, ValueError, TypeError):
            return None
        return None

    def _verify_added_torrent(
        self,
        client: httpx.Client,
        *,
        tag: str,
        torrent_hashes: Iterable[str] = (),
        attempts: int = 10,
        interval: float = 0.3,
    ) -> DownloaderResult:
        hashes = tuple(
            dict.fromkeys(
                value.strip().lower() for value in torrent_hashes if value.strip()
            )
        )
        if not tag and not hashes:
            return DownloaderResult(
                True,
                "qBittorrent 已接受添加请求，但缺少任务标识，无法确认任务是否建立",
                verified=False,
            )

        last_error = ""
        for attempt in range(max(1, attempts)):
            try:
                params = (
                    {"hashes": "|".join(hashes)}
                    if hashes
                    else {"tag": tag, "sort": "added_on", "reverse": "true"}
                )
                response = client.get("api/v2/torrents/info", params=params)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, list):
                    last_error = "qBittorrent 返回了无效的任务列表"
                elif payload:
                    torrent = next(
                        (
                            item
                            for wanted in hashes
                            for item in payload
                            if isinstance(item, dict)
                            and str(item.get("hash") or "").strip().lower() == wanted
                        ),
                        None,
                    )
                    if torrent is None:
                        torrent = next(
                            (item for item in payload if isinstance(item, dict)), None
                        )
                    if torrent is not None:
                        return self._result_from_torrent(torrent)
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                last_error = str(exc)
            if attempt + 1 < attempts:
                time.sleep(interval)

        detail = f"；回查错误：{last_error}" if last_error else ""
        identifier = f"哈希：{'|'.join(hashes)}" if hashes else f"标签：{tag}"
        return DownloaderResult(
            False,
            "qBittorrent 添加接口返回成功，但未在任务列表中找到新任务"
            f"（{identifier}）{detail}",
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
        if not 200 <= remove_response.status_code < 300:
            return DownloaderResult(
                False, f"移除临时标签失败：HTTP {remove_response.status_code}"
            )

        delete_response = client.post(
            "api/v2/torrents/deleteTags",
            data={"tags": tag},
        )
        if not 200 <= delete_response.status_code < 300:
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
        expected_hashes: Iterable[str] = (),
    ) -> DownloaderResult:
        outcome = self._add_response_outcome(response)
        hash_candidates = tuple(
            dict.fromkeys((*outcome.torrent_ids, *tuple(expected_hashes)))
        )
        if not outcome.accepted:
            if response.status_code == 409:
                existing = self._find_existing_torrent(
                    client, torrent_hashes=hash_candidates, expected_name=rename
                )
                if existing is not None:
                    existing.retryable = False
                    existing.tag_removed = True
                    return existing
            return DownloaderResult(
                False, outcome.message, retryable=outcome.retryable
            )

        verified = self._verify_added_torrent(
            client, tag=tag, torrent_hashes=hash_candidates
        )
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
                    client,
                    response,
                    tag=tags_value.split(",", 1)[0].strip(),
                    rename=rename,
                    expected_hashes=self._magnet_hash_candidates(url),
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
                    client,
                    response,
                    tag=tags_value.split(",", 1)[0].strip(),
                    rename=rename,
                    expected_hashes=self._torrent_hash_candidates(content),
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
                    if not 200 <= remove_response.status_code < 300:
                        failures.append(
                            f"移除 {len(batch)} 个标签失败：HTTP {remove_response.status_code}"
                        )
                        continue
                    delete_response = client.post(
                        "api/v2/torrents/deleteTags",
                        data={"tags": joined},
                    )
                    if not 200 <= delete_response.status_code < 300:
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
                if not 200 <= response.status_code < 300:
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
                if not 200 <= response.status_code < 300:
                    return DownloaderResult(False, f"添加 Tracker 失败：HTTP {response.status_code}")
                return DownloaderResult(True, f"已添加 {len(values)} 个 Tracker")
        except httpx.HTTPError as exc:
            return DownloaderResult(False, f"添加 Tracker 请求失败：{exc}")

    def relocate_single_video(
        self,
        *,
        torrent_hash: str,
        target_save_path: str,
        desired_name: str,
    ) -> TorrentRelocateResult:
        """Rename one video torrent and move it to a new qBittorrent location."""

        error = self._configuration_error()
        if error:
            return TorrentRelocateResult(False, False, False, error)
        normalized_hash = str(torrent_hash or "").strip()
        if not normalized_hash:
            return TorrentRelocateResult(False, False, False, "任务哈希为空")
        target_location = posixpath.normpath("/" + str(target_save_path or "").lstrip("/"))
        try:
            with self._client() as client:
                login = self._login(client)
                if not login.ok:
                    return TorrentRelocateResult(False, False, False, login.message)
                torrents_response = client.get(
                    "api/v2/torrents/info", params={"hashes": normalized_hash}
                )
                torrents_response.raise_for_status()
                torrents = torrents_response.json()
                if not isinstance(torrents, list) or not torrents:
                    return TorrentRelocateResult(False, False, False, "qBittorrent 中已找不到试看任务")
                torrent = torrents[0]
                resolved_hash = str(torrent.get("hash") or normalized_hash).strip()
                current_location = posixpath.normpath(
                    "/" + str(torrent.get("save_path") or "").lstrip("/")
                )

                files_response = client.get(
                    "api/v2/torrents/files", params={"hash": resolved_hash}
                )
                files_response.raise_for_status()
                files = files_response.json()
                if not isinstance(files, list) or not files:
                    return TorrentRelocateResult(False, True, False, "试看任务尚未取得文件列表")
                videos = [file for file in files if is_video_file(str(file.get("name") or ""))]
                if len(videos) != 1:
                    return TorrentRelocateResult(
                        False,
                        True,
                        False,
                        f"试看任务包含 {len(videos)} 个视频文件，无法自动迁移",
                    )

                video_path = str(videos[0].get("name") or "")
                directory, filename = posixpath.split(video_path)
                old_stem, extension = posixpath.splitext(filename)
                target_stem = safe_segment(desired_name)
                new_video_path = posixpath.join(directory, target_stem + extension)
                renamed = False
                if video_path != new_video_path:
                    response = client.post(
                        "api/v2/torrents/renameFile",
                        data={
                            "hash": resolved_hash,
                            "oldPath": video_path,
                            "newPath": new_video_path,
                        },
                    )
                    if not 200 <= response.status_code < 300:
                        return TorrentRelocateResult(
                            False,
                            True,
                            False,
                            f"试看视频重命名失败：HTTP {response.status_code}",
                        )
                    renamed = True

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
                    if 200 <= response.status_code < 300:
                        subtitle_count += 1

                relocated = current_location != target_location
                if relocated:
                    response = client.post(
                        "api/v2/torrents/setLocation",
                        data={"hashes": resolved_hash, "location": target_location},
                    )
                    if not 200 <= response.status_code < 300:
                        current_path = posixpath.join(current_location, new_video_path)
                        return TorrentRelocateResult(
                            False,
                            True,
                            renamed,
                            f"试看文件移动失败：HTTP {response.status_code}",
                            current_path,
                        )

                final_path = posixpath.join(target_location, new_video_path)
                actions = []
                if renamed:
                    actions.append(f"重命名为 {posixpath.basename(new_video_path)}")
                if subtitle_count:
                    actions.append(f"同步重命名 {subtitle_count} 个字幕")
                if relocated:
                    actions.append(f"移动到 {target_location}")
                message = "试看文件已" + "，".join(actions) if actions else "试看文件已在目标位置"
                return TorrentRelocateResult(
                    True, True, renamed or relocated, message, final_path
                )
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            return TorrentRelocateResult(False, False, False, f"试看文件迁移请求失败：{exc}")

    @staticmethod
    def _rename_single_video_and_subtitles(
        client: httpx.Client,
        *,
        resolved_hash: str,
        files: list,
        videos: list,
        torrent_save_path: str,
        desired_name: str,
        initial_video_path: str,
        completed: bool,
        progress: int,
    ) -> tuple[TorrentNormalizeResult | None, bool, str, str, str]:
        media_filename = posixpath.basename(initial_video_path)
        media_download_path = posixpath.join(torrent_save_path, initial_video_path)
        manual_required = False
        rename_message = ""

        if not desired_name:
            return None, manual_required, rename_message, media_filename, media_download_path

        if len(videos) > 1:
            manual_required = True
            rename_message = f"检测到 {len(videos)} 个视频文件，已保留原文件名"
            return None, manual_required, rename_message, media_filename, media_download_path

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
            if not 200 <= rename_response.status_code < 300:
                error_result = TorrentNormalizeResult(
                    False,
                    "error",
                    f"视频文件重命名失败：HTTP {rename_response.status_code}",
                    resolved_hash,
                    completed,
                    progress,
                )
                return error_result, manual_required, rename_message, media_filename, media_download_path

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
            if 200 <= response.status_code < 300:
                subtitle_count += 1

        media_filename = target_stem + extension
        media_download_path = posixpath.join(torrent_save_path, new_video_path)
        rename_message = f"已规范化为 {media_filename}"
        if subtitle_count:
            rename_message += f"，并同步重命名 {subtitle_count} 个字幕"

        return None, manual_required, rename_message, media_filename, media_download_path

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
                torrent_save_path = posixpath.normpath(
                    "/" + str(torrent.get("save_path") or "").lstrip("/")
                )
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

                initial_video_path = str(videos[0].get("name") or "")
                error_result, manual_required, rename_message, media_filename, media_download_path = self._rename_single_video_and_subtitles(
                    client,
                    resolved_hash=resolved_hash,
                    files=files,
                    videos=videos,
                    torrent_save_path=torrent_save_path,
                    desired_name=desired_name,
                    initial_video_path=initial_video_path,
                    completed=completed,
                    progress=progress,
                )
                if error_result:
                    return error_result

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
                        media_filename,
                        media_download_path,
                    )

                state = "manual_required_waiting" if manual_required else "waiting_completion"
                message = rename_message or "任务已建立"
                message += f"；等待下载完成（{progress}%）"
                return TorrentNormalizeResult(
                    True,
                    state,
                    message,
                    resolved_hash,
                    False,
                    progress,
                    None,
                    media_filename,
                    media_download_path,
                )
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            return TorrentNormalizeResult(False, "error", f"重命名或完成状态检查失败：{exc}")
