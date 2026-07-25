from __future__ import annotations

import hashlib
import html
import posixpath
import re
import threading
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .database import SessionLocal
from .downloader import QBittorrentClient
from .models import FeedItem, Subscription, SystemLog
from .rss_parser import parse_feed
from .runtime_config import load_qbittorrent_config


_refresh_lock = threading.Lock()
_MAGNET_RE = re.compile(r"magnet:\?[^\s\"'<>]+", re.IGNORECASE)
_DEFAULT_EPISODE_PATTERNS = (
    re.compile(r"(?:\bE(?:P)?|Episode|第)\s*0*(\d{1,4})(?:\s*[集话])?", re.IGNORECASE),
    re.compile(r"-\s*0*(\d{1,4})(?:\s*(?:v\d+)?\s*(?:\[|\(|$))", re.IGNORECASE),
    re.compile(r"\[\s*0*(\d{1,4})\s*\]"),
)


def split_keywords(value: str) -> list[str]:
    return [part.strip().casefold() for part in re.split(r"[,，\n]", value) if part.strip()]


def match_title(title: str, include_keywords: str, exclude_keywords: str) -> tuple[bool, str]:
    normalized = title.casefold()
    includes = split_keywords(include_keywords)
    excludes = split_keywords(exclude_keywords)

    hit_excludes = [keyword for keyword in excludes if keyword in normalized]
    if hit_excludes:
        return False, f"命中排除词：{', '.join(hit_excludes)}"

    if includes and not any(keyword in normalized for keyword in includes):
        return False, "未命中任一包含词"

    return True, "匹配成功"


def parse_episode(title: str, custom_regex: str = "") -> str:
    patterns: list[re.Pattern[str]] = []
    if custom_regex:
        try:
            patterns.append(re.compile(custom_regex, re.IGNORECASE))
        except re.error:
            return ""
    patterns.extend(_DEFAULT_EPISODE_PATTERNS)

    for pattern in patterns:
        match = pattern.search(title)
        if not match:
            continue
        value = match.group(1) if match.groups() else match.group(0)
        try:
            return str(int(value))
        except (TypeError, ValueError):
            return str(value).strip()
    return ""


def _entry_value(entry: Any, key: str, default: Any = "") -> Any:
    if isinstance(entry, dict):
        return entry.get(key, default)
    return getattr(entry, key, default)


def extract_download_url(entry: Any) -> str:
    enclosures = _entry_value(entry, "enclosures", []) or []
    for enclosure in enclosures:
        href = enclosure.get("href", "") if isinstance(enclosure, dict) else getattr(enclosure, "href", "")
        media_type = enclosure.get("type", "") if isinstance(enclosure, dict) else getattr(enclosure, "type", "")
        if href and ("bittorrent" in media_type.lower() or href.lower().endswith(".torrent")):
            return href.strip()

    links = _entry_value(entry, "links", []) or []
    for link in links:
        href = link.get("href", "") if isinstance(link, dict) else getattr(link, "href", "")
        media_type = link.get("type", "") if isinstance(link, dict) else getattr(link, "type", "")
        if href.startswith("magnet:") or "bittorrent" in media_type.lower() or href.lower().endswith(".torrent"):
            return href.strip()

    for field in ("link", "summary", "description"):
        raw = str(_entry_value(entry, field, "") or "")
        match = _MAGNET_RE.search(html.unescape(raw))
        if match:
            return match.group(0)

    return ""


def _parse_datetime(entry: Any) -> datetime | None:
    value = _entry_value(entry, "published_datetime", None)
    return value if isinstance(value, datetime) else None


def _safe_segment(value: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", value).strip().strip(".")
    return cleaned or "未命名订阅"


def render_save_path(subscription: Subscription, episode: str) -> str:
    download_path = load_qbittorrent_config().download_path
    context = {
        "base": download_path.rstrip("/"),
        "subscription": _safe_segment(subscription.name),
        "episode": episode or "unknown",
    }
    try:
        rendered = subscription.save_path_template.format_map(context)
    except (KeyError, ValueError):
        rendered = f"{context['base']}/{context['subscription']}"

    # Normalize and collapse dot segments because the path is sent into a Linux container.
    normalized = posixpath.normpath("/" + rendered.lstrip("/"))
    base = posixpath.normpath("/" + download_path.lstrip("/"))
    if not (normalized == base or normalized.startswith(base.rstrip("/") + "/")):
        return f"{base}/{context['subscription']}"
    return normalized


def fingerprint_for(entry: Any, title: str, download_url: str) -> str:
    guid = str(_entry_value(entry, "id", "") or _entry_value(entry, "guid", "") or "").strip()
    raw = guid or download_url or f"{title}|{_entry_value(entry, 'published', '')}"
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()


def add_log(db: Session, level: str, message: str, details: str = "") -> None:
    db.add(SystemLog(level=level.upper(), message=message, details=details[:4000]))


def process_subscription(db: Session, subscription: Subscription) -> dict[str, int]:
    stats = {"new": 0, "queued": 0, "skipped": 0, "errors": 0}
    headers = {"User-Agent": settings.rss_user_agent, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"}

    try:
        response = httpx.get(
            subscription.rss_url,
            headers=headers,
            timeout=settings.request_timeout_seconds,
            follow_redirects=True,
        )
        response.raise_for_status()
        entries = parse_feed(response.content)
    except Exception as exc:  # Network and parser errors are logged per subscription.
        subscription.last_checked_at = datetime.now(timezone.utc)
        subscription.last_error = str(exc)[:1000]
        add_log(db, "ERROR", f"订阅检查失败：{subscription.name}", str(exc))
        db.commit()
        stats["errors"] += 1
        return stats

    downloader = QBittorrentClient()
    for entry in reversed(entries):
        title = str(_entry_value(entry, "title", "未命名条目") or "未命名条目").strip()
        download_url = extract_download_url(entry)
        source_url = str(_entry_value(entry, "link", "") or "").strip()
        fingerprint = fingerprint_for(entry, title, download_url)
        guid = str(_entry_value(entry, "id", "") or _entry_value(entry, "guid", "") or "")

        exists = db.scalar(
            select(FeedItem.id).where(
                FeedItem.subscription_id == subscription.id,
                FeedItem.fingerprint == fingerprint,
            )
        )
        if exists:
            continue

        matched, reason = match_title(title, subscription.include_keywords, subscription.exclude_keywords)
        episode = parse_episode(title, subscription.episode_regex)
        item = FeedItem(
            subscription_id=subscription.id,
            fingerprint=fingerprint,
            guid=guid,
            title=title,
            download_url=download_url,
            source_url=source_url,
            episode=episode,
            published_at=_parse_datetime(entry),
            status="discovered",
            reason=reason,
        )
        db.add(item)
        db.flush()

        stats["new"] += 1
        if not matched:
            item.status = "skipped"
            stats["skipped"] += 1
            continue
        if not download_url:
            item.status = "error"
            item.reason = "未找到 torrent、magnet 或可下载链接"
            stats["errors"] += 1
            continue

        save_path = render_save_path(subscription, episode)
        item.save_path = save_path
        result = downloader.add_url(download_url, save_path)
        if result.ok:
            item.status = "queued"
            item.reason = result.message
            stats["queued"] += 1
        else:
            item.status = "error"
            item.reason = result.message
            stats["errors"] += 1

    subscription.last_checked_at = datetime.now(timezone.utc)
    subscription.last_error = ""
    add_log(
        db,
        "INFO",
        f"订阅检查完成：{subscription.name}",
        f"新增 {stats['new']}，推送 {stats['queued']}，跳过 {stats['skipped']}，错误 {stats['errors']}",
    )
    db.commit()
    return stats


def refresh_all() -> dict[str, int | bool | str]:
    if not _refresh_lock.acquire(blocking=False):
        return {"ok": False, "message": "已有刷新任务正在运行", "subscriptions": 0, "queued": 0}

    totals = {"subscriptions": 0, "new": 0, "queued": 0, "skipped": 0, "errors": 0}
    try:
        with SessionLocal() as db:
            subscriptions = list(
                db.scalars(select(Subscription).where(Subscription.enabled.is_(True)).order_by(Subscription.id))
            )
            for subscription in subscriptions:
                totals["subscriptions"] += 1
                result = process_subscription(db, subscription)
                for key in ("new", "queued", "skipped", "errors"):
                    totals[key] += result[key]
        return {"ok": True, "message": "刷新完成", **totals}
    finally:
        _refresh_lock.release()


def retry_item(db: Session, item: FeedItem) -> tuple[bool, str]:
    subscription = db.get(Subscription, item.subscription_id)
    if not subscription:
        return False, "订阅不存在"
    if not item.download_url:
        return False, "该条目没有可下载链接"

    save_path = item.save_path or render_save_path(subscription, item.episode)
    result = QBittorrentClient().add_url(item.download_url, save_path)
    item.save_path = save_path
    item.status = "queued" if result.ok else "error"
    item.reason = result.message
    db.commit()
    return result.ok, result.message
