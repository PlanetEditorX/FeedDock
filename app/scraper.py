from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import httpx
from sqlalchemy.orm import Session

from .config import settings
from .models import Subscription
from .naming import (
    canonical_title,
    canonical_year,
    media_folder_name,
    remote_to_local_path,
    safe_segment,
)
from .outbound import external_client
from .runtime_config import load_metadata_config, load_qbittorrent_config


@dataclass(slots=True)
class ScrapeResult:
    ok: bool
    message: str
    local_path: str = ""
    files: list[str] | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "message": self.message,
            "local_path": self.local_path,
            "files": self.files or [],
        }


def _write_xml(path: Path, root: ET.Element) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    temporary = path.with_suffix(path.suffix + ".tmp")
    tree.write(temporary, encoding="utf-8", xml_declaration=True)
    os.replace(temporary, path)


def _text(parent: ET.Element, name: str, value: str | int) -> None:
    if value in {"", 0, None}:
        return
    child = ET.SubElement(parent, name)
    child.text = str(value)


def _unique_id(parent: ET.Element, provider: str, value: int, *, default: bool = False) -> None:
    if value <= 0:
        return
    child = ET.SubElement(parent, "uniqueid", {"type": provider, "default": "true" if default else "false"})
    child.text = str(value)


def _download_image(url: str, destination: Path) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        if destination.is_file() and destination.stat().st_size > 1024:
            return True
    except OSError:
        pass
    try:
        with external_client(
            url,
            db=None,
            timeout=settings.request_timeout_seconds,
            headers={"User-Agent": settings.rss_user_agent},
        ) as client:
            response = client.get(url)
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "").lower()
            if "image" not in content_type and len(response.content) < 1024:
                return False
            temporary = destination.with_suffix(destination.suffix + ".tmp")
            temporary.write_bytes(response.content)
            os.replace(temporary, destination)
            return True
    except (httpx.HTTPError, OSError):
        return False


def _series_nfo(subscription: Subscription) -> ET.Element:
    root = ET.Element("tvshow")
    _text(root, "title", canonical_title(subscription))
    _text(root, "originaltitle", subscription.reference_title or subscription.name)
    _text(root, "sorttitle", canonical_title(subscription))
    _text(root, "year", canonical_year(subscription))
    _text(root, "plot", subscription.metadata_overview)
    _text(root, "premiered", subscription.air_date)
    _text(root, "status", "Continuing")
    tmdb_id = int(subscription.tmdb_id or 0)
    _unique_id(root, "tmdb", tmdb_id, default=bool(tmdb_id))
    _unique_id(root, "bangumi", int(subscription.bangumi_id or 0), default=not bool(tmdb_id))
    _text(root, "tmdbid", tmdb_id)
    if subscription.bgm_url:
        _text(root, "website", subscription.bgm_url)
    return root


def _season_nfo(subscription: Subscription) -> ET.Element:
    root = ET.Element("season")
    _text(root, "title", f"Season {int(subscription.season):02d}")
    _text(root, "seasonnumber", int(subscription.season))
    _text(root, "plot", subscription.metadata_overview)
    return root


def _movie_nfo(subscription: Subscription) -> ET.Element:
    root = ET.Element("movie")
    _text(root, "title", canonical_title(subscription))
    _text(root, "originaltitle", subscription.reference_title or subscription.name)
    _text(root, "year", canonical_year(subscription))
    _text(root, "plot", subscription.metadata_overview)
    _text(root, "premiered", subscription.air_date)
    tmdb_id = int(subscription.tmdb_id or 0)
    _unique_id(root, "tmdb", tmdb_id, default=bool(tmdb_id))
    _unique_id(root, "bangumi", int(subscription.bangumi_id or 0), default=not bool(tmdb_id))
    _text(root, "tmdbid", tmdb_id)
    return root


def scrape_local_metadata(db: Session, subscription: Subscription) -> ScrapeResult:
    config = load_metadata_config(db)
    qbit = load_qbittorrent_config(db)
    if not config.media_local_root:
        return ScrapeResult(
            False,
            "尚未配置本地媒体挂载目录。请先把 qBittorrent 下载目录挂载给 FeedDock。",
        )

    # Imported lazily to avoid a module cycle: rss_service uses naming helpers,
    # while the manual scraper needs the final path rendered by rss_service.
    from .rss_service import render_save_path

    remote_path = render_save_path(subscription, "1", db)
    try:
        local_path = Path(
            remote_to_local_path(
                remote_path,
                qbit.download_path,
                config.media_local_root,
            )
        )
    except ValueError as exc:
        return ScrapeResult(False, str(exc))

    files: list[str] = []
    try:
        if (subscription.media_type or "tv") == "movie":
            movie_root = local_path
            movie_root.mkdir(parents=True, exist_ok=True)
            nfo_path = movie_root / "movie.nfo"
            _write_xml(nfo_path, _movie_nfo(subscription))
            files.append(str(nfo_path))
            if _download_image(subscription.poster_url, movie_root / "poster.jpg"):
                files.append(str(movie_root / "poster.jpg"))
            if _download_image(subscription.backdrop_url, movie_root / "backdrop.jpg"):
                files.append(str(movie_root / "backdrop.jpg"))
            target = movie_root
        else:
            season_root = local_path
            series_root = season_root.parent
            season_root.mkdir(parents=True, exist_ok=True)
            tvshow_nfo = series_root / "tvshow.nfo"
            season_nfo = season_root / "season.nfo"
            _write_xml(tvshow_nfo, _series_nfo(subscription))
            _write_xml(season_nfo, _season_nfo(subscription))
            files.extend([str(tvshow_nfo), str(season_nfo)])
            if _download_image(subscription.poster_url, series_root / "poster.jpg"):
                files.append(str(series_root / "poster.jpg"))
            if _download_image(
                subscription.poster_url,
                series_root / f"season{int(subscription.season):02d}-poster.jpg",
            ):
                files.append(
                    str(series_root / f"season{int(subscription.season):02d}-poster.jpg")
                )
            if _download_image(subscription.backdrop_url, series_root / "backdrop.jpg"):
                files.append(str(series_root / "backdrop.jpg"))
            target = series_root
    except OSError as exc:
        return ScrapeResult(False, f"写入本地元数据失败：{exc}", str(local_path), files)

    return ScrapeResult(
        True,
        f"已为 {media_folder_name(subscription)} 写入本地 NFO/图片",
        str(target),
        files,
    )


def trigger_tmm_scrape(db: Session, subscription: Subscription) -> ScrapeResult:
    """Ask tinyMediaManager to scan and scrape the completed media path."""
    config = load_metadata_config(db)
    if not config.tmm_configured:
        return ScrapeResult(False, "尚未启用 tinyMediaManager 或地址/API Key 未配置")
    qbit = load_qbittorrent_config(db)
    from .rss_service import render_save_path

    season_path = render_save_path(subscription, "1", db)
    target_path = season_path if (subscription.media_type or "tv") == "movie" else str(Path(season_path).parent)
    endpoint = "movie" if (subscription.media_type or "tv") == "movie" else "tvshow"
    # TMM must mount the same media directory at the same container path, for
    # example /media in qBittorrent, FeedDock and tinyMediaManager.
    if not target_path.startswith(qbit.download_path.rstrip("/") + "/") and target_path != qbit.download_path:
        return ScrapeResult(False, "tinyMediaManager 路径不在统一下载根目录中", target_path)
    commands = [
        {"action": "update", "scope": {"name": "path", "args": [target_path]}},
        {"action": "scrape", "scope": {"name": "path", "args": [target_path]}},
        {"action": "downloadMissingArtwork", "scope": {"name": "path", "args": [target_path]}},
    ]
    try:
        with httpx.Client(timeout=max(60, settings.request_timeout_seconds), follow_redirects=True, trust_env=False) as client:
            response = client.post(
                f"{config.tmm_url}/api/{endpoint}",
                headers={"api-key": config.tmm_api_key, "Content-Type": "application/json"},
                json=commands,
            )
            if response.status_code not in {200, 201, 202, 204}:
                detail = response.text.strip()[:500]
                return ScrapeResult(False, f"tinyMediaManager 调用失败：HTTP {response.status_code} {detail}", target_path)
        return ScrapeResult(True, "已提交 tinyMediaManager 扫描、刮削与补图任务", target_path)
    except httpx.HTTPError as exc:
        return ScrapeResult(False, f"连接 tinyMediaManager 失败：{exc}", target_path)


def scrape_subscription(db: Session, subscription: Subscription) -> ScrapeResult:
    mode = (getattr(subscription, "scrape_mode", "local") or "local").strip().lower()
    if mode == "off" or not getattr(subscription, "scrape_enabled", True):
        return ScrapeResult(True, "该订阅已跳过刮削")
    results: list[ScrapeResult] = []
    if mode in {"local", "both"}:
        results.append(scrape_local_metadata(db, subscription))
    if mode in {"tmm", "both"}:
        results.append(trigger_tmm_scrape(db, subscription))
    if not results:
        return ScrapeResult(False, f"未知刮削模式：{mode}")
    ok = all(result.ok for result in results)
    files = [item for result in results for item in (result.files or [])]
    local_path = next((result.local_path for result in results if result.local_path), "")
    return ScrapeResult(ok, "；".join(result.message for result in results), local_path, files)


def test_tmm_connection(db: Session) -> ScrapeResult:
    config = load_metadata_config(db)
    if not config.tmm_url or not config.tmm_api_key:
        return ScrapeResult(False, "请先填写 tinyMediaManager 地址和 API Key")
    try:
        with httpx.Client(timeout=settings.request_timeout_seconds, follow_redirects=True, trust_env=False) as client:
            response = client.post(
                f"{config.tmm_url}/api/tvshow",
                headers={"api-key": config.tmm_api_key, "Content-Type": "application/json"},
                json={"action": "update", "scope": {"name": "path", "args": ["/__feeddock_connection_test__"]}},
            )
        if response.status_code in {200, 201, 202, 204, 400, 404, 422}:
            return ScrapeResult(True, f"tinyMediaManager API 可访问（HTTP {response.status_code}）")
        return ScrapeResult(False, f"tinyMediaManager API 返回 HTTP {response.status_code}")
    except httpx.HTTPError as exc:
        return ScrapeResult(False, f"连接 tinyMediaManager 失败：{exc}")


def refresh_emby_library(db: Session) -> ScrapeResult:
    config = load_metadata_config(db)
    if not config.emby_url or not config.emby_api_key:
        return ScrapeResult(False, "尚未配置 Emby 地址和 API Key")
    try:
        with external_client(config.emby_url, db=db, timeout=settings.request_timeout_seconds) as client:
            response = client.post(
                f"{config.emby_url}/Library/Refresh",
                headers={"X-Emby-Token": config.emby_api_key},
            )
            if response.status_code not in {200, 204}:
                return ScrapeResult(False, f"Emby 刷新失败：HTTP {response.status_code}")
        return ScrapeResult(True, "已通知 Emby 刷新媒体库")
    except httpx.HTTPError as exc:
        return ScrapeResult(False, f"连接 Emby 失败：{exc}")
