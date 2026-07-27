from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import FeedItem, Subscription
from .naming import canonical_title, canonical_year, is_video_file
from .outbound import external_get
from .runtime_config import MetadataConfig, load_metadata_config


_MAX_IMAGE_BYTES = 25 * 1024 * 1024
_SEASON_DIRECTORY_RE = re.compile(r"^season\s+\d+$", re.IGNORECASE)
_IMAGE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


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


def _xml_text(value: object) -> str:
    text = str(value or "")
    return "".join(character for character in text if character in "\n\r\t" or ord(character) >= 32)


def _add_text(parent: ET.Element, tag: str, value: object) -> ET.Element | None:
    text = _xml_text(value).strip()
    if not text:
        return None
    node = ET.SubElement(parent, tag)
    node.text = text
    return node


def _add_unique_ids(parent: ET.Element, subscription: Subscription) -> None:
    identifiers = [
        ("tmdb", int(subscription.tmdb_id or 0)),
        ("bangumi", int(subscription.bangumi_id or 0)),
        ("anilist", int(subscription.anilist_id or 0)),
    ]
    available = [(provider, value) for provider, value in identifiers if value > 0]
    preferred = (subscription.metadata_source or "").strip().casefold()
    default_provider = preferred if any(provider == preferred for provider, _ in available) else (
        available[0][0] if available else ""
    )
    for provider, value in available:
        attributes = {"type": provider}
        if provider == default_provider:
            attributes["default"] = "true"
        node = ET.SubElement(parent, "uniqueid", attributes)
        node.text = str(value)


def _xml_bytes(root: ET.Element) -> bytes:
    try:
        ET.indent(root, space="  ")
    except AttributeError:  # pragma: no cover - Python 3.8 compatibility
        pass
    return ET.tostring(root, encoding="utf-8", xml_declaration=True, short_empty_elements=False)


def _atomic_write(path: Path, content: bytes) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            if path.read_bytes() == content:
                return False
        except OSError:
            pass
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return True


def _safe_media_directory(path_value: str, root_value: str) -> Path:
    if not path_value or not root_value:
        raise ValueError("媒体目录或媒体根目录未配置")
    root = Path(root_value).expanduser().resolve(strict=False)
    target = Path(path_value).expanduser().resolve(strict=False)
    if target != root and root not in target.parents:
        raise ValueError("下载目录不在允许的媒体根目录内")
    if not target.exists():
        raise FileNotFoundError(f"下载目录不存在：{target}")
    if not target.is_dir():
        raise ValueError(f"下载路径不是目录：{target}")
    return target


def _series_directory(subscription: Subscription, item_directory: Path) -> tuple[Path, Path]:
    if (subscription.media_type or "tv").strip().casefold() == "movie":
        return item_directory, item_directory
    if _SEASON_DIRECTORY_RE.match(item_directory.name):
        return item_directory.parent, item_directory
    expected = f"season {int(subscription.season or 0):02d}"
    if item_directory.name.casefold() == expected:
        return item_directory.parent, item_directory
    return item_directory, item_directory


def _premiered(subscription: Subscription) -> str:
    value = str(subscription.air_date or "").strip()
    return value if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) else ""


def _title_values(subscription: Subscription) -> tuple[str, str]:
    title = canonical_title(subscription).strip() or subscription.name.strip() or "未命名媒体"
    original = (subscription.reference_title or subscription.name or title).strip()
    return title, original


def _base_metadata(root: ET.Element, subscription: Subscription) -> None:
    title, original = _title_values(subscription)
    _add_text(root, "title", title)
    if original and original != title:
        _add_text(root, "originaltitle", original)
    _add_text(root, "sorttitle", title)
    _add_text(root, "plot", subscription.metadata_overview)
    year = canonical_year(subscription)
    if year > 0:
        _add_text(root, "year", year)
    premiered = _premiered(subscription)
    if premiered:
        _add_text(root, "premiered", premiered)
    rating = float(subscription.metadata_rating or 0.0)
    if rating > 0:
        _add_text(root, "rating", f"{rating:.1f}")
    if (subscription.poster_url or "").strip():
        thumb = ET.SubElement(root, "thumb", {"aspect": "poster"})
        thumb.text = _xml_text(subscription.poster_url).strip()
    if (subscription.backdrop_url or "").strip():
        fanart = ET.SubElement(root, "fanart")
        thumb = ET.SubElement(fanart, "thumb")
        thumb.text = _xml_text(subscription.backdrop_url).strip()
    _add_unique_ids(root, subscription)


def _tvshow_nfo(subscription: Subscription) -> bytes:
    root = ET.Element("tvshow")
    _base_metadata(root, subscription)
    return _xml_bytes(root)


def _season_nfo(subscription: Subscription) -> bytes:
    root = ET.Element("season")
    season = int(subscription.season or 0)
    _add_text(root, "title", f"Season {season:02d}")
    _add_text(root, "seasonnumber", season)
    _add_text(root, "plot", subscription.metadata_overview)
    return _xml_bytes(root)


def _episode_nfo(subscription: Subscription, item: FeedItem) -> bytes:
    root = ET.Element("episodedetails")
    title, _ = _title_values(subscription)
    episode = str(item.episode or "").strip()
    _add_text(root, "title", f"第 {episode} 集" if episode else item.title)
    _add_text(root, "showtitle", title)
    _add_text(root, "season", int(subscription.season or 0))
    _add_text(root, "episode", episode)
    if item.published_at is not None:
        published = item.published_at
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        _add_text(root, "aired", published.date().isoformat())
    _add_text(root, "plot", subscription.metadata_overview)
    return _xml_bytes(root)


def _movie_nfo(subscription: Subscription) -> bytes:
    root = ET.Element("movie")
    _base_metadata(root, subscription)
    return _xml_bytes(root)


def _candidate_videos(directory: Path, *, maximum: int = 5000) -> list[Path]:
    videos: list[Path] = []
    root_depth = len(directory.parts)
    for current_root, directories, filenames in os.walk(directory):
        current = Path(current_root)
        depth = len(current.parts) - root_depth
        if depth >= 3:
            directories[:] = []
        for filename in filenames:
            candidate = current / filename
            if is_video_file(candidate.name):
                videos.append(candidate)
                if len(videos) >= maximum:
                    return videos
    return videos


def _find_episode_video(directory: Path, desired_name: str) -> Path | None:
    videos = _candidate_videos(directory)
    desired = (desired_name or "").strip().casefold()
    if desired:
        exact = [video for video in videos if video.stem.casefold() == desired]
        if len(exact) == 1:
            return exact[0]
    return videos[0] if len(videos) == 1 else None




def _detected_image_extension(content: bytes) -> str:
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return ".webp"
    return ""

def _image_extension(content_type: str, url: str) -> str:
    media_type = (content_type or "").split(";", 1)[0].strip().casefold()
    if media_type in _IMAGE_EXTENSIONS:
        return _IMAGE_EXTENSIONS[media_type]
    suffix = Path(urlparse(url).path).suffix.casefold()
    return suffix if suffix in {".jpg", ".jpeg", ".png", ".webp"} else ".jpg"


def _download_artwork(
    db: Session,
    url: str,
    directory: Path,
    basename: str,
    *,
    timeout: int = 30,
) -> tuple[Path | None, str]:
    cleaned = (url or "").strip()
    if not cleaned:
        return None, ""
    for extension in (".jpg", ".jpeg", ".png", ".webp"):
        existing = directory / f"{basename}{extension}"
        try:
            if existing.is_file() and existing.stat().st_size > 0:
                return existing, ""
        except OSError:
            pass
    try:
        response = external_get(
            cleaned,
            db=db,
            timeout=timeout,
            headers={"Accept": "image/webp,image/png,image/jpeg,image/*;q=0.8"},
        )
        response.raise_for_status()
        content = bytes(response.content or b"")
        if not content:
            return None, f"{basename} 图片为空"
        if len(content) > _MAX_IMAGE_BYTES:
            return None, f"{basename} 图片超过 25 MiB"
        content_type = response.headers.get("Content-Type", "")
        if content_type and not content_type.casefold().startswith("image/"):
            return None, f"{basename} 返回的不是图片"
        detected_extension = _detected_image_extension(content)
        if not detected_extension:
            return None, f"{basename} 图片格式无效，仅支持 JPEG、PNG 和 WebP"
        extension = detected_extension or _image_extension(content_type, cleaned)
        target = directory / f"{basename}{extension}"
        _atomic_write(target, content)
        return target, ""
    except Exception as exc:
        return None, f"{basename} 下载失败：{exc}"


def _write_manifest(
    directory: Path,
    subscription: Subscription,
    item: FeedItem,
    files: Iterable[Path],
) -> Path:
    manifest = {
        "generator": "FeedDock",
        "subscription_id": subscription.id,
        "feed_item_id": item.id,
        "metadata_source": subscription.metadata_source,
        "tmdb_id": int(subscription.tmdb_id or 0),
        "bangumi_id": int(subscription.bangumi_id or 0),
        "anilist_id": int(subscription.anilist_id or 0),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": [
            str(path.relative_to(directory)) if path == directory or directory in path.parents else str(path)
            for path in files
        ],
    }
    target = directory / ".feeddock-scrape.json"
    _atomic_write(target, json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8") + b"\n")
    return target


def scrape_completed_item(
    db: Session,
    subscription: Subscription,
    item: FeedItem,
    config: MetadataConfig | None = None,
) -> ScrapeResult:
    """Write media-library sidecar metadata for one completed download."""

    metadata = config or load_metadata_config(db)
    try:
        item_directory = _safe_media_directory(item.save_path, metadata.media_local_root)
        media_root, season_directory = _series_directory(subscription, item_directory)
        generated: list[Path] = []
        warnings: list[str] = []
        media_type = (subscription.media_type or "tv").strip().casefold()

        if media_type == "movie":
            movie_nfo = media_root / "movie.nfo"
            movie_content = _movie_nfo(subscription)
            _atomic_write(movie_nfo, movie_content)
            generated.append(movie_nfo)
            video = _find_episode_video(item_directory, item.desired_name)
            if video is not None:
                matching_nfo = video.with_suffix(".nfo")
                _atomic_write(matching_nfo, movie_content)
                generated.append(matching_nfo)
            else:
                warnings.append("未能唯一定位电影文件，已仅写入 movie.nfo")
        else:
            tvshow_nfo = media_root / "tvshow.nfo"
            season_nfo = season_directory / "season.nfo"
            _atomic_write(tvshow_nfo, _tvshow_nfo(subscription))
            _atomic_write(season_nfo, _season_nfo(subscription))
            generated.extend((tvshow_nfo, season_nfo))

            video = _find_episode_video(item_directory, item.desired_name)
            if video is not None:
                episode_nfo = video.with_suffix(".nfo")
                _atomic_write(episode_nfo, _episode_nfo(subscription, item))
                generated.append(episode_nfo)
            else:
                warnings.append("未能唯一定位视频文件，已跳过剧集 NFO")

        poster, poster_error = _download_artwork(db, subscription.poster_url, media_root, "poster")
        if poster is not None:
            generated.append(poster)
            if media_type != "movie":
                poster_bytes = poster.read_bytes()
                season_folder_poster = season_directory / f"poster{poster.suffix}"
                series_season_poster = media_root / (
                    f"season{int(subscription.season or 0):02d}-poster{poster.suffix}"
                )
                _atomic_write(season_folder_poster, poster_bytes)
                _atomic_write(series_season_poster, poster_bytes)
                generated.extend((season_folder_poster, series_season_poster))
        elif poster_error:
            warnings.append(poster_error)

        fanart, fanart_error = _download_artwork(db, subscription.backdrop_url, media_root, "fanart")
        if fanart is not None:
            generated.append(fanart)
        elif fanart_error:
            warnings.append(fanart_error)

        manifest = _write_manifest(media_root, subscription, item, generated)
        generated.append(manifest)
        file_names = [str(path) for path in generated]
        message = f"已写入媒体库元数据：{len(generated)} 个文件"
        if warnings:
            message += "；" + "；".join(warnings)
        return ScrapeResult(True, message[:2000], str(media_root), file_names)
    except Exception as exc:
        return ScrapeResult(False, f"写入媒体库元数据失败：{exc}")


def scrape_local_metadata(db: Session, subscription: Subscription) -> ScrapeResult:
    items = list(
        db.scalars(
            select(FeedItem)
            .where(
                FeedItem.subscription_id == subscription.id,
                FeedItem.completed_at.is_not(None),
            )
            .order_by(FeedItem.id)
        )
    )
    if not items:
        return ScrapeResult(False, "没有已完成的下载条目可刮削")
    generated: list[str] = []
    failures: list[str] = []
    local_path = ""
    for item in items:
        result = scrape_completed_item(db, subscription, item)
        if result.ok:
            generated.extend(result.files or [])
            local_path = local_path or result.local_path
        else:
            failures.append(f"条目 {item.id}：{result.message}")
    if failures:
        return ScrapeResult(False, "；".join(failures)[:2000], local_path, generated)
    return ScrapeResult(True, f"已刮削 {len(items)} 个已完成条目", local_path, generated)


def trigger_tmm_scrape(db: Session, subscription: Subscription) -> ScrapeResult:
    return ScrapeResult(False, "tinyMediaManager 远程刮削尚未启用，请使用 FeedDock 本地 NFO/图片刮削")


def scrape_subscription(db: Session, subscription: Subscription) -> ScrapeResult:
    return scrape_local_metadata(db, subscription)


def test_tmm_connection(db: Session) -> ScrapeResult:
    return ScrapeResult(False, "tinyMediaManager 配置与测试入口尚未启用")


def refresh_emby_library(db: Session) -> ScrapeResult:
    return ScrapeResult(False, "媒体库刷新入口尚未启用；NFO 与图片写入后请由媒体服务器扫描目录")
