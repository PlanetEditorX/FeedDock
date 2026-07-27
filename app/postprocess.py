from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .config import settings
from .database import SessionLocal
from .debug_logging import format_exception_details, log_event
from .downloader import QBittorrentClient
from .media_sidecar import write_bangumi_ini
from .metadata_service import MetadataService
from .models import FeedItem, Subscription, SystemLog
from .notifications import send_notification
from .runtime_config import load_metadata_config
from .scraper import scrape_completed_item
from .settings_config import load_application_preferences
from .subscription_monitor import evaluate_subscription_completion


_normalize_lock = threading.Lock()
_ACTIVE_RENAME_STATES = {
    "",
    "pending",
    "retry",
    "error",
    "waiting_completion",
    "manual_required_waiting",
}


def _add_log(db: Session, level: str, message: str, details: str = "") -> None:
    normalized = level.upper()
    safe_details = details[:50000]
    log_event(normalized, message, safe_details, persist=False)
    db.add(SystemLog(level=normalized, message=message, details=safe_details))


def _metadata_sync_due(subscription: Subscription) -> bool:
    last = subscription.metadata_last_synced_at
    if last is None:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - last >= timedelta(hours=settings.metadata_auto_sync_hours)


def normalize_pending_items(db: Session | None = None, *, limit: int = 50, allow_scrape: bool = True) -> dict[str, Any]:
    """Normalize tagged torrents, detect completion, and run configured post-download metadata work."""

    if not _normalize_lock.acquire(blocking=False):
        return {"ok": False, "message": "已有下载完成检查正在运行", "checked": 0}
    owns_session = db is None
    session = db or SessionLocal()
    stats = {
        "checked": 0,
        "renamed": 0,
        "completed": 0,
        "pending": 0,
        "manual_required": 0,
        "errors": 0,
        "scraped": 0,
        "trackers_applied": 0,
    }
    try:
        items = list(
            session.scalars(
                select(FeedItem)
                .where(
                    FeedItem.status == "queued",
                    FeedItem.qbit_tag != "",
                    or_(
                        FeedItem.rename_status.in_(_ACTIVE_RENAME_STATES),
                        FeedItem.scrape_status.in_(("pending", "error")),
                        FeedItem.trackers_status == "error",
                    ),
                )
                .order_by(FeedItem.id)
                .limit(limit)
            )
        )
        client = QBittorrentClient()
        completed_subscription_ids: set[int] = set()
        for item in items:
            stats["checked"] += 1
            result = client.normalize_single_video(
                tag=item.qbit_tag,
                desired_name=item.desired_name,
            )
            previous_state = item.rename_status
            item.rename_status = result.state
            item.rename_message = result.message[:2000]
            item.download_progress = max(0, min(100, int(result.progress or 0)))

            created_at = item.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            missing_task_expired = (
                result.state == "pending"
                and result.message == "等待 qBittorrent 建立任务"
                and (datetime.now(timezone.utc) - created_at).total_seconds() >= 120
            )
            if missing_task_expired:
                item.status = "error"
                item.reason = "qBittorrent 中未找到已记录的任务，请点击重试下载"
                item.rename_status = "error"
                item.rename_message = item.reason
                session.add(
                    SystemLog(
                        level="ERROR",
                        message="qBittorrent 中未找到已记录任务",
                        details=(
                            f"条目 ID：{item.id}\n任务标签：{item.qbit_tag}\n"
                            f"标题：{item.title}\n处理：已标记为错误，可重新推送"
                        ),
                    )
                )
                stats["errors"] += 1
                continue
            if result.torrent_hash:
                item.torrent_hash = result.torrent_hash
                tracker_policy = load_application_preferences(session).trackers
                if tracker_policy.enabled and tracker_policy.trackers and item.trackers_applied_at is None:
                    tracker_result = client.add_trackers(result.torrent_hash, tracker_policy.trackers)
                    item.trackers_status = "completed" if tracker_result.ok else "error"
                    item.trackers_message = tracker_result.message[:2000]
                    if tracker_result.ok:
                        item.trackers_applied_at = datetime.now(timezone.utc)
                        stats["trackers_applied"] += 1
                    else:
                        stats["errors"] += 1

            if "已规范化" in result.message and previous_state not in {"completed", "manual_required"}:
                stats["renamed"] += 1

            if result.completed:
                stats["completed"] += 1
                newly_completed = item.completed_at is None
                item.completed_at = item.completed_at or datetime.now(timezone.utc)
                if newly_completed:
                    completed_subscription_ids.add(item.subscription_id)
                    subscription = session.get(Subscription, item.subscription_id)
                    if subscription is not None:
                        send_notification(
                            session,
                            "download_completed",
                            f"下载完成：{subscription.name}",
                            f"第 {item.episode or '?'} 集下载完成。\n{item.title}",
                            subscription=subscription,
                            item=item,
                            details={"progress": 100},
                        )
                subscription = session.get(Subscription, item.subscription_id)
                metadata_config = load_metadata_config(session)
                should_process_scrape = allow_scrape and item.scrape_status != "completed" and (
                    metadata_config.auto_scrape_enabled or metadata_config.bangumi_ini_enabled
                )
                if subscription is not None and should_process_scrape:
                    completed_actions: list[str] = []
                    scrape_errors: list[str] = []
                    if metadata_config.auto_scrape_enabled:
                        if _metadata_sync_due(subscription):
                            try:
                                record = MetadataService(
                                    timeout=load_application_preferences(session).rss.timeout_seconds
                                ).sync(session, subscription, "auto")
                                completed_actions.append(f"元数据已同步（{record.provider}）")
                                _add_log(
                                    session,
                                    "INFO",
                                    f"下载完成后元数据已同步：{subscription.name}",
                                    (
                                        f"订阅 ID：{subscription.id}\n条目 ID：{item.id}\n"
                                        f"来源：{record.provider}\n元数据 ID：{record.id}"
                                    ),
                                )
                            except Exception as exc:
                                scrape_errors.append(f"元数据同步失败：{exc}")
                                _add_log(
                                    session,
                                    "WARNING",
                                    f"下载完成后元数据同步失败：{subscription.name}",
                                    format_exception_details(
                                        exc,
                                        stage="postprocess.metadata",
                                        context={
                                            "subscription_id": subscription.id,
                                            "item_id": item.id,
                                            "subscription_name": subscription.name,
                                        },
                                    ),
                                )
                        else:
                            completed_actions.append("元数据已是最新")

                        local_scrape = scrape_completed_item(
                            session, subscription, item, metadata_config
                        )
                        if local_scrape.ok:
                            completed_actions.append(local_scrape.message)
                            _add_log(
                                session,
                                "INFO",
                                f"媒体库元数据已写入：{subscription.name}",
                                (
                                    f"订阅 ID：{subscription.id}\n条目 ID：{item.id}\n"
                                    f"媒体目录：{local_scrape.local_path}\n"
                                    f"文件：{', '.join(local_scrape.files or [])}"
                                )[:50000],
                            )
                        else:
                            scrape_errors.append(local_scrape.message)
                            _add_log(
                                session,
                                "WARNING",
                                f"媒体库元数据写入失败：{subscription.name}",
                                (
                                    f"订阅 ID：{subscription.id}\n条目 ID：{item.id}\n"
                                    f"错误：{local_scrape.message}"
                                ),
                            )

                    if metadata_config.bangumi_ini_enabled:
                        sidecar = write_bangumi_ini(subscription, item, metadata_config)
                        if sidecar.state == "completed":
                            completed_actions.append("bangumi.ini 已生成")
                        elif sidecar.state == "error":
                            scrape_errors.append(sidecar.message)
                        elif sidecar.message:
                            completed_actions.append(sidecar.message)

                    if scrape_errors:
                        item.scrape_status = "error"
                        item.scrape_message = "；".join(scrape_errors)[:2000]
                        stats["errors"] += 1
                    else:
                        item.scrape_status = "completed"
                        item.scrape_message = "；".join(completed_actions)[:2000] or "下载完成后刮削已完成"
                        item.scraped_at = datetime.now(timezone.utc)
                        stats["scraped"] += 1
                elif subscription is None:
                    item.scrape_status = "skipped"
                    item.scrape_message = "订阅不存在"
                elif not should_process_scrape and not (
                    metadata_config.auto_scrape_enabled or metadata_config.bangumi_ini_enabled
                ):
                    item.scrape_status = "skipped"
                    item.scrape_message = "未启用下载完成后自动刮削"

                if result.state == "manual_required":
                    stats["manual_required"] += 1
            elif result.state in {"pending", "waiting_completion", "manual_required_waiting"}:
                stats["pending"] += 1
                if result.state == "manual_required_waiting":
                    stats["manual_required"] += 1
            elif result.state == "manual_required":
                stats["manual_required"] += 1
            elif result.state not in {"skipped"}:
                stats["errors"] += 1

        for subscription_id in completed_subscription_ids:
            subscription = session.get(Subscription, subscription_id)
            if subscription is not None:
                evaluate_subscription_completion(session, subscription)

        if items:
            session.add(
                SystemLog(
                    level="INFO" if stats["errors"] == 0 else "WARNING",
                    message="qBittorrent 下载完成检查完成",
                    details=(
                        f"检查 {stats['checked']}，已规范化 {stats['renamed']}，"
                        f"下载完成 {stats['completed']}，等待 {stats['pending']}，"
                        f"需手动处理 {stats['manual_required']}，"
                        f"Tracker {stats['trackers_applied']}，错误 {stats['errors']}"
                    ),
                )
            )
        session.commit()
        return {"ok": True, "message": "下载完成检查完成", **stats}
    finally:
        if owns_session:
            session.close()
        _normalize_lock.release()
