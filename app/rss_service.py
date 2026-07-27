from __future__ import annotations

import hashlib
import html
import posixpath
from pathlib import Path
import time
import re
import threading
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .database import SessionLocal
from .debug_logging import format_exception_details, log_event
from .downloader import QBittorrentClient
from .models import FeedItem, Subscription, SystemLog
from .naming import is_video_file, media_folder_name, naming_context, render_desired_name
from .rss_parser import parse_feed
from .outbound import external_get
from .notifications import send_notification
from .subscription_monitor import (
    calculate_missing_episodes as monitor_missing_episodes,
    evaluate_missing_episodes,
    evaluate_stale_subscription,
    evaluate_subscription_completion,
    record_new_feed_activity,
)
from .runtime_config import get_app_setting, load_automation_config, load_metadata_config, load_qbittorrent_config
from .settings_config import load_application_preferences


_refresh_lock = threading.Lock()
_MAGNET_RE = re.compile(r"magnet:\?[^\s\"'<>]+", re.IGNORECASE)
_REGEX_HINT_RE = re.compile(r"[\\.^$*+?{}\[\]|()]")
_DEFAULT_EPISODE_PATTERNS = (
    re.compile(r"(?:\bE(?:P)?|Episode|第)\s*0*(\d{1,4}(?:\.5)?)(?:\s*[集话])?", re.IGNORECASE),
    re.compile(r"-\s*0*(\d{1,4}(?:\.5)?)(?:\s*(?:v\d+)?\s*(?:\[|\(|$))", re.IGNORECASE),
    re.compile(r"\[\s*0*(\d{1,4}(?:\.5)?)\s*\]"),
)
_LEGACY_DEFAULT_SAVE_PATH_TEMPLATES = {
    "{base}/{subscription}/Season {season}",
    "{base}/{subscription}/Season {season:02}",
}


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
    # A single container-visible root is used by qBittorrent and FeedDock's
    # local scraper. Per-subscription customization belongs in the path
    # template below, never in a second, potentially unmapped root.
    qbit_root = posixpath.normpath("/" + load_qbittorrent_config(db).download_path.lstrip("/"))
    base_root = qbit_root

    context = _path_context(subscription, episode, base_root)
    template = (subscription.save_path_template or "").strip()
    # Early versions used {subscription}, which is the raw RSS title and
    # therefore cannot include the confirmed TMDB marker. Treat only the old
    # built-in defaults as upgrades; intentionally custom templates remain as-is.
    if template in _LEGACY_DEFAULT_SAVE_PATH_TEMPLATES:
        template = "{base}/{media_folder}/Season {season:02}"
    if not template:
        template = (
            "{base}/{media_folder}"
            if (subscription.media_type or "tv") == "movie"
            else "{base}/{media_folder}/Season {season:02}"
        )
    try:
        rendered = template.format_map(context)
    except (KeyError, ValueError, TypeError):
        rendered = (
            f"{context['base']}/{context['media_folder']}"
            if (subscription.media_type or "tv") == "movie"
            else f"{context['base']}/{context['media_folder']}/Season {context['season']:02d}"
        )

    normalized = posixpath.normpath("/" + rendered.lstrip("/"))
    if normalized != base_root and not normalized.startswith(base_root.rstrip("/") + "/"):
        return (
            f"{base_root}/{context['media_folder']}"
            if (subscription.media_type or "tv") == "movie"
            else f"{base_root}/{context['media_folder']}/Season {context['season']:02d}"
        )
    return normalized


def fingerprint_for(entry: Any, title: str, download_url: str) -> str:
    guid = str(_entry_value(entry, "id", "") or _entry_value(entry, "guid", "") or "").strip()
    raw = guid or download_url or f"{title}|{_entry_value(entry, 'published', '')}"
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()


def add_log(db: Session, level: str, message: str, details: str = "") -> None:
    normalized = level.upper()
    safe_details = details[:50000]
    log_event(normalized, message, safe_details, persist=False)
    db.add(SystemLog(level=normalized, message=message, details=safe_details))


def _download_log_details(
    item: FeedItem,
    subscription: Subscription,
    *,
    save_path: str = "",
    desired_name: str = "",
    extra: str = "",
) -> str:
    """Build a useful log message without exposing private RSS passkeys."""

    values = [
        f"订阅 ID：{subscription.id}",
        f"条目 ID：{item.id}",
        f"集数：{item.episode or '未识别'}",
        f"标题：{item.title}",
        f"保存位置：{save_path or item.save_path or '未确定'}",
        f"任务标签：{item.qbit_tag or '未生成'}",
    ]
    if desired_name or item.desired_name:
        values.append(f"任务名称：{desired_name or item.desired_name}")
    if extra:
        values.append(extra)
    return "\n".join(values)


def _fetch_entries(url: str, db: Session | None = None) -> list[dict[str, Any]]:
    headers = {
        "User-Agent": settings.rss_user_agent,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
    }
    response = external_get(
        url,
        db=db,
        headers=headers,
        timeout=(load_application_preferences(db).rss.timeout_seconds if db is not None else settings.request_timeout_seconds),
    )
    response.raise_for_status()
    return parse_feed(response.content)


def _load_subscription_entries(subscription: Subscription, db: Session | None = None) -> tuple[list[dict[str, Any]], str]:
    primary_error: Exception | None = None
    try:
        entries = _fetch_entries(subscription.rss_url, db)
        if entries:
            return entries, subscription.primary_rss_name or "主 RSS"
        primary_error = ValueError("主 RSS 没有条目")
    except Exception as exc:
        primary_error = exc

    if subscription.backup_rss_url:
        try:
            entries = _fetch_entries(subscription.backup_rss_url, db)
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
    episode_recognized = bool(adjusted)
    # A metadata title such as “番剧名 (2026)” normally has no episode number.
    # Preview the path and naming template with E01 rather than emitting
    # ``Eunknown``. Real downloads still require a parsed RSS episode and never
    # use this preview-only fallback.
    preview_episode = adjusted or "1"
    matched, reason = match_title(
        sample_title,
        subscription.include_keywords,
        subscription.exclude_keywords,
        global_excludes,
    )
    number = episode_number(adjusted)
    if matched and subscription.total_episodes and number is not None and number > subscription.total_episodes:
        matched, reason = False, f"集数 {adjusted} 超过总集数 {subscription.total_episodes}"
    elif matched and not episode_recognized:
        reason = "标题匹配通过；示例标题未识别集数，文件名按第 1 集演示"
    return {
        "parsed_episode": parsed,
        "adjusted_episode": adjusted,
        "episode_recognized": episode_recognized,
        "preview_episode": preview_episode,
        "matched": matched,
        "match_reason": reason,
        "save_path": render_save_path(subscription, preview_episode, db),
        "desired_name": render_desired_name(subscription, preview_episode) if subscription.rename_enabled else "",
        "media_folder": media_folder_name(subscription),
    }


def calculate_missing_episodes(db: Session, subscription: Subscription) -> list[int]:
    return monitor_missing_episodes(db, subscription)


def _sync_metadata_if_due(db: Session, subscription: Subscription) -> None:
    config = load_metadata_config(db)
    global_enabled = bool(config.auto_scrape_enabled)
    if not subscription.auto_metadata and not global_enabled:
        return
    if global_enabled and not subscription.auto_metadata:
        activity = subscription.last_new_item_at or subscription.last_checked_at or subscription.created_at
        if activity is not None:
            if activity.tzinfo is None:
                activity = activity.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - activity > timedelta(days=config.follow_days):
                return
    last = subscription.metadata_last_synced_at
    if last is not None:
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - last < timedelta(hours=settings.metadata_auto_sync_hours):
            return
    try:
        from .metadata_service import MetadataService

        MetadataService(timeout=load_application_preferences(db).rss.timeout_seconds).sync(db, subscription, "auto")
    except Exception as exc:
        add_log(
            db,
            "WARNING",
            f"自动元数据同步失败：{subscription.name}",
            format_exception_details(
                exc,
                stage="rss.auto-metadata",
                context={"subscription_id": subscription.id, "subscription_name": subscription.name},
            ),
        )
        db.commit()


def _refresh_total_episodes_if_due(db: Session, subscription: Subscription) -> None:
    policy = load_application_preferences(db).rss
    if not policy.auto_disable_complete or subscription.total_episodes_locked or int(subscription.bangumi_id or 0) <= 0:
        return
    checked = subscription.total_episodes_checked_at
    if checked is not None:
        if checked.tzinfo is None:
            checked = checked.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - checked < timedelta(hours=12):
            return
    try:
        from .metadata_service import MetadataService

        record = MetadataService(timeout=policy.timeout_seconds).get(
            db, provider="bangumi", metadata_id=int(subscription.bangumi_id), season=subscription.season
        )
        if record.total_episodes > 0:
            subscription.total_episodes = record.total_episodes
            subscription.total_episodes_source = "bangumi"
        subscription.total_episodes_checked_at = datetime.now(timezone.utc)
    except Exception as exc:
        add_log(db, "WARNING", f"Bangumi 总集数更新失败：{subscription.name}", str(exc))


def _existing_video_matches(item: FeedItem, subscription: Subscription, db: Session) -> bool:
    policy = load_application_preferences(db).rss
    if not policy.auto_skip_existing or not subscription.rename_enabled or not item.desired_name:
        return False
    try:
        root = Path(load_qbittorrent_config(db).download_path).resolve(strict=False)
        directory = Path(item.save_path).resolve(strict=False)
        if directory != root and root not in directory.parents:
            return False
        if not directory.is_dir():
            return False
        target = item.desired_name.casefold()
        for index, child in enumerate(directory.iterdir()):
            if index >= 2000:
                break
            if child.is_file() and is_video_file(child.name) and child.stem.casefold() == target:
                return True
    except (OSError, RuntimeError, ValueError):
        return False
    return False


def _push_feed_item(db: Session, item: FeedItem, subscription: Subscription) -> tuple[bool, str]:
    preferences = load_application_preferences(db)
    save_path = item.save_path or render_save_path(subscription, item.episode, db)
    desired_name = (
        render_desired_name(subscription, item.episode)
        if subscription.rename_enabled and item.episode
        else ""
    )
    item.save_path = save_path
    item.desired_name = desired_name
    item.qbit_tag = item.qbit_tag or f"feeddock-item-{item.id}"
    item.scrape_status = "pending" if load_metadata_config(db).bangumi_ini_enabled else "skipped"
    item.scrape_message = "等待下载完成后生成 bangumi.ini" if item.scrape_status == "pending" else "交由外部媒体库识别"
    add_log(
        db,
        "INFO",
        f"准备推送到下载器：{subscription.name}",
        _download_log_details(
            item, subscription, save_path=save_path, desired_name=desired_name,
            extra=f"下载器：qBittorrent；最多尝试 {preferences.download.retry_count + 1} 次",
        ),
    )

    if _existing_video_matches(item, subscription, db):
        item.status = "skipped"
        item.reason = "目标目录中已存在同名视频文件"
        item.rename_status = "skipped"
        item.rename_message = item.reason
        add_log(
            db,
            "INFO",
            f"跳过下载器推送：{subscription.name}",
            _download_log_details(item, subscription, extra=item.reason),
        )
        return True, item.reason

    client = QBittorrentClient(timeout=preferences.rss.timeout_seconds)
    if preferences.download.concurrent_limit > 0 and hasattr(client, "active_download_count"):
        ok, active, message = client.active_download_count()
        if ok and active >= preferences.download.concurrent_limit:
            item.status = "scheduled"
            item.reason = f"等待下载并发空位（{active}/{preferences.download.concurrent_limit}）"
            item.rename_status = "pending"
            item.rename_message = item.reason
            add_log(
                db,
                "INFO",
                f"下载任务等待并发空位：{subscription.name}",
                _download_log_details(item, subscription, extra=item.reason),
            )
            return True, item.reason
        if not ok:
            add_log(db, "WARNING", "读取下载并发数失败，继续尝试推送", message)

    attempts = preferences.download.retry_count + 1
    result = None
    for attempt in range(attempts):
        try:
            result = client.add_url(
                item.download_url,
                save_path,
                rename=desired_name,
                tags=item.qbit_tag,
                seeding_minutes=preferences.download.seeding_minutes,
            )
        except TypeError:
            # Compatibility with third-party downloader test doubles and older adapters.
            result = client.add_url(item.download_url, save_path, rename=desired_name, tags=item.qbit_tag)
        if result.ok:
            break
        if attempt + 1 < attempts:
            add_log(
                db,
                "WARNING",
                f"下载器推送失败，准备重试：{subscription.name}",
                _download_log_details(
                    item, subscription,
                    extra=f"第 {attempt + 1}/{attempts} 次尝试失败：{result.message}",
                ),
            )
            time.sleep(min(1.0, 0.2 * (attempt + 1)))
    assert result is not None
    if result.ok:
        item.status = "queued"
        item.reason = result.message
        item.rename_status = "pending"
        item.rename_message = "等待 qBittorrent 获取文件列表并完成下载"
        add_log(
            db,
            "INFO",
            f"已推送到下载器：{subscription.name}",
            _download_log_details(
                item, subscription,
                extra=f"结果：{result.message}；实际尝试 {attempt + 1} 次",
            ),
        )
        send_notification(
            db,
            "download_started",
            f"开始下载：{subscription.name}",
            f"第 {item.episode or '?'} 集已推送到 qBittorrent。\n{item.title}",
            subscription=subscription,
            item=item,
        )
    else:
        item.status = "error"
        item.reason = f"{result.message}（已尝试 {attempts} 次）"
        item.rename_status = "error"
        item.rename_message = item.reason
        add_log(
            db,
            "ERROR",
            f"最终未能推送到下载器：{subscription.name}",
            _download_log_details(item, subscription, extra=item.reason),
        )
        send_notification(
            db,
            "rss_error",
            f"下载任务推送失败：{subscription.name}",
            f"{item.title}\n{item.reason}",
            subscription=subscription,
            item=item,
        )
    return result.ok, item.reason


def dispatch_scheduled_downloads(db: Session | None = None, *, limit: int = 500, include_daily: bool = True) -> dict[str, int | bool | str]:
    owns = db is None
    session = db or SessionLocal()
    stats = {"checked": 0, "queued": 0, "waiting": 0, "skipped": 0, "errors": 0}
    try:
        statement = select(FeedItem).where(FeedItem.status == "scheduled")
        if not include_daily:
            statement = statement.where(FeedItem.reason.like("等待下载并发空位%"))
        items = list(session.scalars(statement.order_by(FeedItem.id).limit(limit)))
        for item in items:
            stats["checked"] += 1
            subscription = session.get(Subscription, item.subscription_id)
            if not subscription or not subscription.enabled:
                item.status = "skipped"
                item.reason = "订阅已删除或停用"
                continue
            ok, _ = _push_feed_item(session, item, subscription)
            if item.status == "queued" and ok:
                stats["queued"] += 1
            elif item.status == "scheduled" and ok:
                stats["waiting"] += 1
            elif item.status == "skipped":
                stats["skipped"] += 1
            else:
                stats["errors"] += 1
        if items:
            add_log(
                session,
                "INFO" if not stats["errors"] else "WARNING",
                "定时下载任务执行完成",
                (
                    f"检查 {stats['checked']}，推送 {stats['queued']}，"
                    f"等待空位 {stats['waiting']}，跳过 {stats['skipped']}，错误 {stats['errors']}"
                ),
            )
            session.commit()
        return {"ok": True, "message": "定时下载任务执行完成", **stats}
    finally:
        if owns:
            session.close()


def process_subscription(db: Session, subscription: Subscription) -> dict[str, int]:
    stats = {"new": 0, "queued": 0, "skipped": 0, "errors": 0}
    add_log(
        db,
        "INFO",
        f"开始检查订阅：{subscription.name}",
        f"订阅 ID：{subscription.id}\nRSS 来源：{subscription.primary_rss_name or '主 RSS'}",
    )
    db.commit()
    preferences = load_application_preferences(db)
    if not preferences.rss.enabled:
        add_log(db, "WARNING", f"跳过订阅检查：{subscription.name}", "RSS 开关已关闭")
        db.commit()
        return stats
    _refresh_total_episodes_if_due(db, subscription)
    _sync_metadata_if_due(db, subscription)
    try:
        entries, source_name = _load_subscription_entries(subscription, db)
    except Exception as exc:
        subscription.last_checked_at = datetime.now(timezone.utc)
        subscription.last_error = str(exc)[:1000]
        add_log(
            db,
            "ERROR",
            f"订阅检查失败：{subscription.name}",
            format_exception_details(
                exc,
                stage="rss.load",
                context={
                    "subscription_id": subscription.id,
                    "subscription_name": subscription.name,
                    "rss_url": subscription.rss_url,
                    "backup_rss_url": subscription.backup_rss_url,
                },
            ),
        )
        send_notification(
            db,
            "rss_error",
            f"RSS 检查失败：{subscription.name}",
            str(exc),
            subscription=subscription,
        )
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

        item.save_path = render_save_path(subscription, candidate["episode"], db)
        desired_name = (render_desired_name(subscription, candidate["episode"])
                        if subscription.rename_enabled and candidate["episode"] else "")
        item.desired_name = desired_name
        item.qbit_tag = f"feeddock-item-{item.id}"
        item.scrape_status = "pending" if load_metadata_config(db).bangumi_ini_enabled else "skipped"
        item.scrape_message = "等待下载完成后生成 bangumi.ini" if item.scrape_status == "pending" else "交由外部媒体库识别"
        automation = load_automation_config(db)
        if automation.download_enabled:
            item.status = "scheduled"
            item.reason = f"等待每日 {automation.daily_time}（{automation.timezone}）统一推送"
            item.rename_status = "pending"
            item.rename_message = "等待定时推送"
            item.scrape_message = "等待下载完成后生成 bangumi.ini" if item.scrape_status == "pending" else "交由外部媒体库识别"
            add_log(
                db,
                "INFO",
                f"下载任务等待定时推送：{subscription.name}",
                _download_log_details(item, subscription, extra=item.reason),
            )
        else:
            ok, _ = _push_feed_item(db, item, subscription)
            if item.status == "skipped":
                stats["skipped"] += 1
            elif item.status in {"queued", "scheduled"} and ok:
                stats["queued"] += 1
            else:
                stats["errors"] += 1

    now = datetime.now(timezone.utc)
    if any(candidate["matched"] for candidate in candidates):
        record_new_feed_activity(subscription, now=now)
    evaluate_missing_episodes(db, subscription)
    evaluate_stale_subscription(db, subscription, now=now)
    evaluate_subscription_completion(db, subscription, now=now)
    subscription.last_checked_at = now
    subscription.last_error = ""
    add_log(
        db,
        "INFO",
        f"订阅检查完成：{subscription.name}",
        f"来源 {source_name}；新增 {stats['new']}，推送 {stats['queued']}，跳过 {stats['skipped']}，错误 {stats['errors']}",
    )
    db.commit()
    return stats


def refresh_subscription(
    subscription_id: int,
    *,
    trigger: str = "manual",
) -> dict[str, int | bool | str]:
    """Refresh one subscription, used after creation and by future targeted actions."""

    acquired = _refresh_lock.acquire(timeout=300)
    if not acquired:
        with SessionLocal() as db:
            add_log(
                db,
                "WARNING",
                "新订阅自动刷新等待超时",
                f"订阅 ID：{subscription_id}；触发来源：{trigger}",
            )
            db.commit()
        return {"ok": False, "message": "等待现有刷新任务超时", "subscription_id": subscription_id}

    try:
        with SessionLocal() as db:
            subscription = db.get(Subscription, subscription_id)
            if not subscription:
                return {"ok": False, "message": "订阅不存在", "subscription_id": subscription_id}
            if not subscription.enabled:
                add_log(
                    db,
                    "INFO",
                    f"跳过新订阅自动刷新：{subscription.name}",
                    "订阅当前为停用状态",
                )
                db.commit()
                return {"ok": True, "message": "订阅已停用，未执行刷新", "subscription_id": subscription_id}
            add_log(
                db,
                "INFO",
                f"新订阅自动刷新开始：{subscription.name}",
                f"订阅 ID：{subscription.id}；触发来源：{trigger}",
            )
            db.commit()
            result = process_subscription(db, subscription)
            add_log(
                db,
                "INFO" if not result["errors"] else "WARNING",
                f"新订阅自动刷新完成：{subscription.name}",
                (
                    f"新增 {result['new']}，推送 {result['queued']}，"
                    f"跳过 {result['skipped']}，错误 {result['errors']}"
                ),
            )
            db.commit()
            return {"ok": not bool(result["errors"]), "message": "新订阅自动刷新完成", **result}
    finally:
        _refresh_lock.release()


def refresh_all() -> dict[str, int | bool | str]:
    if not _refresh_lock.acquire(blocking=False):
        with SessionLocal() as db:
            add_log(db, "WARNING", "刷新全部订阅未启动", "已有刷新任务正在运行")
            db.commit()
        return {"ok": False, "message": "已有刷新任务正在运行", "subscriptions": 0, "queued": 0}

    totals = {"subscriptions": 0, "new": 0, "queued": 0, "skipped": 0, "errors": 0}
    try:
        with SessionLocal() as db:
            add_log(db, "INFO", "开始刷新全部订阅", "正在读取所有启用订阅")
            db.commit()
            if not load_application_preferences(db).rss.enabled:
                add_log(db, "WARNING", "刷新全部订阅已跳过", "RSS 开关已关闭")
                db.commit()
                return {"ok": True, "message": "RSS 开关已关闭", **totals}
            subscriptions = list(
                db.scalars(select(Subscription).where(Subscription.enabled.is_(True)).order_by(Subscription.id))
            )
            for subscription in subscriptions:
                totals["subscriptions"] += 1
                result = process_subscription(db, subscription)
                for key in ("new", "queued", "skipped", "errors"):
                    totals[key] += result[key]
            add_log(
                db,
                "INFO" if not totals["errors"] else "WARNING",
                "刷新全部订阅完成",
                (
                    f"订阅 {totals['subscriptions']}，新增 {totals['new']}，"
                    f"推送 {totals['queued']}，跳过 {totals['skipped']}，错误 {totals['errors']}"
                ),
            )
            db.commit()
        try:
            from .postprocess import normalize_pending_items

            normalize_pending_items(limit=50)
        except Exception as exc:
            with SessionLocal() as db:
                add_log(db, "WARNING", "刷新后的下载完成检查失败", str(exc))
                db.commit()
        return {"ok": True, "message": "刷新完成", **totals}
    finally:
        _refresh_lock.release()


def retry_item(db: Session, item: FeedItem) -> tuple[bool, str]:
    subscription = db.get(Subscription, item.subscription_id)
    if not subscription:
        return False, "订阅不存在"
    if not item.download_url:
        return False, "该条目没有可下载链接"

    ok, message = _push_feed_item(db, item, subscription)
    db.commit()
    return ok, message
