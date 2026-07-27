from __future__ import annotations

import posixpath
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from .models import Subscription


_ILLEGAL_SEGMENT_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".m4v", ".ts", ".webm"}
_SUBTITLE_EXTENSIONS = {".ass", ".ssa", ".srt", ".vtt", ".sub", ".sup"}


def _value(obj: object, name: str, default: Any = "") -> Any:
    value = getattr(obj, name, default)
    return default if value is None else value


def safe_segment(value: str, fallback: str = "未命名") -> str:
    cleaned = _ILLEGAL_SEGMENT_RE.sub("_", value or "").strip().strip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned or fallback




def title_with_year(title: str, year: int) -> str:
    """Return a display title with one trailing ``(YYYY)`` suffix."""

    cleaned = " ".join((title or "").split()).strip()
    if not cleaned:
        return ""
    if year <= 0:
        return cleaned
    cleaned = re.sub(r"\s*\(\d{4}\)\s*$", "", cleaned).rstrip()
    return f"{cleaned} ({year})"

def canonical_title(subscription: Subscription) -> str:
    mode = str(_value(subscription, "naming_mode", "auto") or "auto").strip().lower()
    manual = str(_value(subscription, "manual_title", "") or "").strip()
    tmdb = str(_value(subscription, "tmdb_title", "") or "").strip()
    bangumi = str(_value(subscription, "reference_title", "") or "").strip()
    original = str(_value(subscription, "name", "") or "").strip()

    if mode == "manual" and manual:
        return manual
    if mode == "tmdb" and tmdb:
        return tmdb
    if mode == "bangumi" and bangumi:
        return bangumi
    return manual or tmdb or bangumi or original or "未命名番剧"


def canonical_year(subscription: Subscription) -> int:
    metadata_year = int(_value(subscription, "metadata_year", 0) or 0)
    if metadata_year:
        return metadata_year
    air_date = str(_value(subscription, "air_date", "") or "").strip()
    if len(air_date) >= 4 and air_date[:4].isdigit():
        return int(air_date[:4])
    return 0


def _without_duplicate_year(title: str, year: int) -> str:
    if year:
        # Metadata may correct a year embedded in an RSS/third-party title.
        # Keep exactly one authoritative year in the media folder.
        return re.sub(r"\s*\(\d{4}\)\s*$", "", title).rstrip()
    return title


def media_folder_name(subscription: Subscription) -> str:
    title = safe_segment(canonical_title(subscription))
    year = canonical_year(subscription)
    base = _without_duplicate_year(title, year)
    if year:
        base = f"{base} ({year})"
    # Keep the default media directory human-readable. Provider IDs belong in
    # NFO metadata, not in the filesystem name. Custom templates can still use
    # ``{tmdb_id}`` through ``naming_context`` when explicitly requested.
    return safe_segment(base)


def season_folder_name(subscription: Subscription) -> str:
    season = int(_value(subscription, "season", 1) or 0)
    return f"Season {season:02d}"


def episode_template_value(value: str) -> int | str:
    try:
        number = Decimal((value or "").strip())
    except (InvalidOperation, AttributeError):
        return value or "unknown"
    if number == number.to_integral_value():
        return int(number)
    return format(number.normalize(), "f")


def _episode_pad(value: str) -> str:
    episode = episode_template_value(value)
    if isinstance(episode, int):
        return f"{episode:02d}"
    return str(episode)


def naming_context(subscription: Subscription, episode: str, base_path: str = "") -> dict[str, Any]:
    name = str(_value(subscription, "name", "") or "")
    reference_title = str(_value(subscription, "reference_title", "") or "")
    tmdb_title = str(_value(subscription, "tmdb_title", "") or "")
    manual_title = str(_value(subscription, "manual_title", "") or "")
    season = int(_value(subscription, "season", 1) or 0)
    title = safe_segment(canonical_title(subscription))
    year = canonical_year(subscription)
    return {
        "base": base_path.rstrip("/"),
        "subscription": safe_segment(name, "未命名订阅"),
        "reference_title": safe_segment(reference_title or name),
        "tmdb_title": safe_segment(tmdb_title or reference_title or name),
        "manual_title": safe_segment(manual_title or name),
        "title": title,
        "media_folder": media_folder_name(subscription),
        "season": season,
        "season_pad": f"{season:02d}",
        "episode": episode_template_value(episode),
        "episode_pad": _episode_pad(episode),
        "year": year or "",
        "tmdb_id": int(_value(subscription, "tmdb_id", 0) or 0),
        "bangumi_id": int(_value(subscription, "bangumi_id", 0) or 0),
        "media_type": str(_value(subscription, "media_type", "tv") or "tv"),
    }


def render_desired_name(subscription: Subscription, episode: str) -> str:
    context = naming_context(subscription, episode)
    media_type = str(_value(subscription, "media_type", "tv") or "tv").lower()
    template = str(_value(subscription, "file_name_template", "") or "").strip()
    if not template:
        template = "{title} ({year})" if media_type == "movie" else "{title} - S{season:02}E{episode:02}"
    try:
        rendered = template.format_map(context)
    except (KeyError, ValueError, TypeError):
        if media_type == "movie":
            rendered = f"{context['title']} ({context['year']})" if context["year"] else str(context["title"])
        else:
            rendered = f"{context['title']} - S{context['season']:02d}E{_episode_pad(episode)}"
    return safe_segment(rendered)


def default_save_path_template(media_type: str = "tv") -> str:
    return "{base}/{media_folder}" if media_type == "movie" else "{base}/{media_folder}/Season {season:02}"


def normalize_remote_path(path: str) -> str:
    return posixpath.normpath("/" + (path or "").lstrip("/"))


def remote_to_local_path(remote_path: str, remote_root: str, local_root: str) -> str:
    remote = normalize_remote_path(remote_path)
    root = normalize_remote_path(remote_root)
    if remote != root and not remote.startswith(root.rstrip("/") + "/"):
        raise ValueError("下载路径不在已配置的 qBittorrent 保存根目录下")
    relative = posixpath.relpath(remote, root)
    if relative == ".":
        relative = ""
    return posixpath.normpath(posixpath.join(local_root, relative))


def is_video_file(path: str) -> bool:
    return posixpath.splitext(path)[1].lower() in _VIDEO_EXTENSIONS


def is_subtitle_file(path: str) -> bool:
    return posixpath.splitext(path)[1].lower() in _SUBTITLE_EXTENSIONS
