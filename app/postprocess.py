from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .database import SessionLocal
from .downloader import QBittorrentClient
from .media_sidecar import write_bangumi_ini
from .models import FeedItem, Subscription, SystemLog
from .notifications import send_notification
from .runtime_config import load_metadata_config
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


def normalize_pending_items(db: Session | None = None, *, limit: int = 50, allow_scrape: bool = True) -> dict[str, Any]:
    """Normalize tagged torrents and mark completed downloads without scraping."""

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
                if subscription is not None:
                    sidecar = write_bangumi_ini(subscription, item, load_metadata_config(session))
                    item.scrape_status = sidecar.state
                    item.scrape_message = sidecar.message[:2000]
                    if sidecar.state == "completed":
                        item.scraped_at = datetime.now(timezone.utc)
                        stats["scraped"] += 1
                    elif sidecar.state == "error":
                        stats["errors"] += 1
                else:
                    item.scrape_status = "skipped"
                    item.scrape_message = "订阅不存在"

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
