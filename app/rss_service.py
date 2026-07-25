from __future__ import annotations

import hashlib
import html
import posixpath
import re
import threading
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .database import SessionLocal
from .downloader import QBittorrentClient
from .models import FeedItem, Subscription, SystemLog
from .naming import media_folder_name, naming_context, render_desired_name
from .rss_parser import parse_feed
from .runtime_config import get_app_setting, load_qbittorrent_config


_refresh_lock = threading.Lock()
_MAGNET_RE = re.compile(r"magnet:\?[^\s\"'<>]+", re.IGNORECASE)
_REGEX_HINT_RE = re.compile(r"[\\.^$*+?{}\[\]|()]")
_DEFAULT_EPISODE_PATTERNS = (
    re.compile(r"(?:\bE(?:P)?|Episode|第)\s*0*(\d{1,4}(?:\.5)?)(?:\s*[集话])?", re.IGNORECASE),
    re.compile(r"-\s*0*(\d{1,4}(?:\.5)?)(?:\s*(?:v\d+)?\s*(?:\[|\(|$))", re.IGNORECASE),
    re.compile(r"\[\s*0*(\d{1,4}(?:\.5)?)\s*\]"),
)


def split_rules(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,，\n]", value or "") if part.strip()]


def split_keywords(value: str) -> list[str]:
    # Kept for backward compatibility with tests and integrations.
    return [part.casefold() for part in split_rules(value)]


def _rule_matches(title: str, rule: str) -> bool:
    if _REGEX_HINT_RE.search(rule):
        try:
            return re.search(rule, title, flags=re.IGNORECASE) is not None
        except re.error:
            pass
    return rule.casefold() in title.casefold()


def match_title(
    title: str,
    include_keywords: str,
    exclude_keywords: str,
    global_exclude_keywords: str = "",
) -> tuple[bool, str]:
    includes = split_rules(include_keywords)
    excludes = split_rules(exclude_keywords)
    global_excludes = split_rules(global_exclude_keywords)

    for rule in global_excludes:
        if _rule_matches(title, rule):
            return False, f"命中全局排除：{rule}"
    for rule in excludes:
        if _rule_matches(title, rule):
            return False, f"命中排除规则：{rule}"
    if includes and not any(_rule_matches(title, rule) for rule in includes):
        return False, "未命中任一匹配规则"
    return True, "匹配成功"


def _normalize_episode_value(value: str) -> str:
    cleaned = value.strip()
    try:
        number = Decimal(cleaned)
    except InvalidOperation:
        return cleaned
    if number == number.to_integral_value():
        return str(int(number))
    return format(number.normalize(), "f")


def episode_number(value: str) -> Decimal | None:
    try:
        return Decimal(value.strip())
    except (InvalidOperation, AttributeError):
        return None


def parse_episode(title: str, custom_regex: str = "", group_index: int = 1) -> str:
    if custom_regex:
        try:
            match = re.search(custom_regex, title, flags=re.IGNORECASE)
        except re.error:
            return ""
        if match:
            try:
                value = match.group(group_index)
            except IndexError:
                value = match.group(1) if match.groups() else match.group(0)
            if value is not None:
                return _normalize_episode_value(str(value))

    for pattern in _DEFAULT_EPISODE_PATTERNS:
        match = pattern.search(title)
        if match:
            return _normalize_episode_value(match.group(1))
    return ""


def apply_episode_offset(value: str, offset: int) -> str:
    number = episode_number(value)
    if number is None:
        return value
    return _normalize_episode_value(str(number + Decimal(offset)))


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


def _path_context(subscription: Subscription, episode: str, download_path: str) -> dict[str, Any]:
    # naming_context preserves every legacy variable and adds Emby-friendly
    # variables such as {title}, {media_folder}, {tmdb_id} and padded season /
    # episode values. Existing custom templates continue to work unchanged.
    return naming_context(subscription, episode, download_path)


def render_save_path(subscription: Subscription, episode: str, db: Session | None = None) -> str:
    download_path = load_qbittorrent_config(db).download_path
    context = _path_context(subscription, episode, download_path)
    template = (subscription.custom_download_path or subscription.save_path_template).strip()
    if not template:
        template = (
            "{base}/{media_folder}"
            if (subscription.media_type or "tv") == "movie"
            else "{base}/{media_folder}/Season {season:02}"
        )
    try:
        rendered = template.format_map(context)
    except (KeyError, ValueError):
        rendered = f"{context['base']}/{context['subscription']}/Season {context['season']}"

    normalized = posixpath.normpath("/" + rendered.lstrip("/"))
    if subscription.custom_download_path:
        # Custom paths are explicitly entered by the administrator and are sent
        # to qBittorrent as-is after normalization. FeedDock never touches them.
        return normalized

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


def _fetch_entries(url: str) -> list[dict[str, Any]]:
    headers = {
        "User-Agent": settings.rss_user_agent,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
    }
    response = httpx.get(
        url,
        headers=headers,
        timeout=settings.request_timeout_seconds,
        follow_redirects=True,
    )
    response.raise_for_status()
    return parse_feed(response.content)


def _load_subscription_entries(subscription: Subscription) -> tuple[list[dict[str, Any]], str]:
    primary_error: Exception | None = None
    try:
        entries = _fetch_entries(subscription.rss_url)
        if entries:
            return entries, subscription.primary_rss_name or "主 RSS"
        primary_error = ValueError("主 RSS 没有条目")
    except Exception as exc:
        primary_error = exc

    if subscription.backup_rss_url:
        try:
            entries = _fetch_entries(subscription.backup_rss_url)
            return entries, subscription.backup_rss_name or "备用 RSS"
        except Exception as backup_error:
            raise RuntimeError(f"主 RSS 失败：{primary_error}；备用 RSS 失败：{backup_error}") from backup_error
    raise RuntimeError(str(primary_error or "RSS 获取失败"))


def _before_air_date(published_at: datetime | None, air_date: str) -> bool:
    if not published_at or not air_date:
        return False
    try:
        return published_at.date() < date.fromisoformat(air_date)
    except ValueError:
        return False


def preview_subscription(subscription: Subscription, sample_title: str, db: Session | None = None) -> dict[str, str | bool]:
    global_excludes = get_app_setting("global_exclude_rules", "", db)
    parsed = parse_episode(sample_title, subscription.episode_regex, subscription.episode_group)
    adjusted = apply_episode_offset(parsed, subscription.episode_offset) if parsed else ""
    matched, reason = match_title(
        sample_title,
        subscription.include_keywords,
        subscription.exclude_keywords,
        global_excludes,
    )
    number = episode_number(adjusted)
    if matched and subscription.total_episodes and number is not None and number > subscription.total_episodes:
        matched, reason = False, f"集数 {adjusted} 超过总集数 {subscription.total_episodes}"
    return {
        "parsed_episode": parsed,
        "adjusted_episode": adjusted,
        "matched": matched,
        "match_reason": reason,
        "save_path": render_save_path(subscription, adjusted, db),
        "desired_name": render_desired_name(subscription, adjusted) if subscription.rename_enabled else "",
        "media_folder": media_folder_name(subscription),
    }


def calculate_missing_episodes(db: Session, subscription: Subscription) -> list[int]:
    if not subscription.missing_detection or subscription.total_episodes <= 0:
        return []
    values = db.scalars(
        select(FeedItem.episode).where(
            FeedItem.subscription_id == subscription.id,
            FeedItem.status == "queued",
        )
    )
    downloaded: set[int] = set()
    for value in values:
        number = episode_number(value)
        if number is not None and number == number.to_integral_value() and 1 <= number <= subscription.total_episodes:
            downloaded.add(int(number))
    return [episode for episode in range(1, subscription.total_episodes + 1) if episode not in downloaded]


def _sync_metadata_if_due(db: Session, subscription: Subscription) -> None:
    if not subscription.auto_metadata:
        return
    last = subscription.metadata_last_synced_at
    if last is not None:
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - last < timedelta(hours=settings.metadata_auto_sync_hours):
            return
    try:
        from .metadata_service import MetadataService

        MetadataService().sync(db, subscription, "auto")
    except Exception as exc:
        # Metadata outages must never prevent RSS processing. The error is
        # visible in the system log and the next scheduled run retries it.
        add_log(db, "WARNING", f"自动元数据同步失败：{subscription.name}", str(exc))
        db.commit()


def process_subscription(db: Session, subscription: Subscription) -> dict[str, int]:
    stats = {"new": 0, "queued": 0, "skipped": 0, "errors": 0}
    _sync_metadata_if_due(db, subscription)
    try:
        entries, source_name = _load_subscription_entries(subscription)
    except Exception as exc:
        subscription.last_checked_at = datetime.now(timezone.utc)
        subscription.last_error = str(exc)[:1000]
        add_log(db, "ERROR", f"订阅检查失败：{subscription.name}", str(exc))
        db.commit()
        stats["errors"] += 1
        return stats

    global_excludes = get_app_setting("global_exclude_rules", "", db)
    candidates: list[dict[str, Any]] = []
    for order, entry in enumerate(reversed(entries)):
        title = str(_entry_value(entry, "title", "未命名条目") or "未命名条目").strip()
        download_url = extract_download_url(entry)
        fingerprint = fingerprint_for(entry, title, download_url)
        exists = db.scalar(
            select(FeedItem.id).where(
                FeedItem.subscription_id == subscription.id,
                FeedItem.fingerprint == fingerprint,
            )
        )
        if exists:
            continue

        published_at = _parse_datetime(entry)
        matched, reason = match_title(
            title,
            subscription.include_keywords,
            subscription.exclude_keywords,
            global_excludes,
        )
        parsed_episode = parse_episode(title, subscription.episode_regex, subscription.episode_group)
        episode = apply_episode_offset(parsed_episode, subscription.episode_offset) if parsed_episode else ""
        number = episode_number(episode)
        if matched and _before_air_date(published_at, subscription.air_date):
            matched, reason = False, f"发布日期早于 {subscription.air_date}"
        if matched and subscription.total_episodes and number is not None:
            if number <= 0:
                matched, reason = False, f"偏移后的集数 {episode} 无效"
            elif number > subscription.total_episodes:
                matched, reason = False, f"集数 {episode} 超过总集数 {subscription.total_episodes}"

        candidates.append(
            {
                "entry": entry,
                "order": order,
                "title": title,
                "download_url": download_url,
                "source_url": str(_entry_value(entry, "link", "") or "").strip(),
                "fingerprint": fingerprint,
                "guid": str(_entry_value(entry, "id", "") or _entry_value(entry, "guid", "") or ""),
                "published_at": published_at,
                "episode": episode,
                "episode_number": number,
                "matched": matched,
                "reason": reason,
            }
        )

    latest_candidate: dict[str, Any] | None = None
    if subscription.only_latest:
        eligible = [candidate for candidate in candidates if candidate["matched"]]
        numbered = [candidate for candidate in eligible if candidate["episode_number"] is not None]
        if numbered:
            latest_candidate = max(numbered, key=lambda candidate: (candidate["episode_number"], candidate["order"]))
        elif eligible:
            latest_candidate = max(eligible, key=lambda candidate: candidate["order"])

    downloader = QBittorrentClient()
    for candidate in candidates:
        item = FeedItem(
            subscription_id=subscription.id,
            fingerprint=candidate["fingerprint"],
            guid=candidate["guid"],
            title=candidate["title"],
            download_url=candidate["download_url"],
            source_url=candidate["source_url"],
            episode=candidate["episode"],
            published_at=candidate["published_at"],
            status="discovered",
            reason=candidate["reason"],
        )
        db.add(item)
        db.flush()
        stats["new"] += 1

        if not candidate["matched"]:
            item.status = "skipped"
            stats["skipped"] += 1
            continue
        if subscription.only_latest and latest_candidate is not candidate:
            item.status = "skipped"
            item.reason = "已启用“只下载最新集”"
            stats["skipped"] += 1
            continue
        if not candidate["download_url"]:
            item.status = "error"
            item.reason = "未找到 torrent、magnet 或可下载链接"
            stats["errors"] += 1
            continue

        save_path = render_save_path(subscription, candidate["episode"], db)
        item.save_path = save_path
        desired_name = (
            render_desired_name(subscription, candidate["episode"])
            if subscription.rename_enabled and candidate["episode"]
            else ""
        )
        qbit_tag = f"feeddock-item-{item.id}" if desired_name else ""
        item.desired_name = desired_name
        item.qbit_tag = qbit_tag
        result = downloader.add_url(
            candidate["download_url"],
            save_path,
            rename=desired_name,
            tags=qbit_tag,
        )
        if result.ok:
            item.status = "queued"
            item.reason = result.message
            item.rename_status = "pending" if desired_name else "skipped"
            item.rename_message = (
                "等待 qBittorrent 获取种子文件列表" if desired_name else "未启用规范命名"
            )
            stats["queued"] += 1
        else:
            item.status = "error"
            item.reason = result.message
            item.rename_status = "error" if desired_name else ""
            item.rename_message = result.message if desired_name else ""
            stats["errors"] += 1

    subscription.last_checked_at = datetime.now(timezone.utc)
    subscription.last_error = ""
    add_log(
        db,
        "INFO",
        f"订阅检查完成：{subscription.name}",
        f"来源 {source_name}；新增 {stats['new']}，推送 {stats['queued']}，跳过 {stats['skipped']}，错误 {stats['errors']}",
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
        try:
            from .postprocess import normalize_pending_items

            normalize_pending_items(limit=50)
        except Exception:
            pass
        return {"ok": True, "message": "刷新完成", **totals}
    finally:
        _refresh_lock.release()


def retry_item(db: Session, item: FeedItem) -> tuple[bool, str]:
    subscription = db.get(Subscription, item.subscription_id)
    if not subscription:
        return False, "订阅不存在"
    if not item.download_url:
        return False, "该条目没有可下载链接"

    save_path = item.save_path or render_save_path(subscription, item.episode, db)
    desired_name = (
        render_desired_name(subscription, item.episode)
        if subscription.rename_enabled and item.episode
        else ""
    )
    item.qbit_tag = item.qbit_tag or (f"feeddock-item-{item.id}" if desired_name else "")
    item.desired_name = desired_name
    result = QBittorrentClient().add_url(
        item.download_url,
        save_path,
        rename=desired_name,
        tags=item.qbit_tag,
    )
    item.save_path = save_path
    item.status = "queued" if result.ok else "error"
    item.reason = result.message
    item.rename_status = "pending" if result.ok and desired_name else ("error" if desired_name else "skipped")
    item.rename_message = "等待 qBittorrent 获取种子文件列表" if result.ok and desired_name else result.message
    db.commit()
    return result.ok, result.message
