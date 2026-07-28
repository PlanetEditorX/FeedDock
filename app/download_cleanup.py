from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import SessionLocal
from .debug_logging import log_event
from .downloader import QBittorrentClient
from .models import FeedItem, SystemLog
from .settings_config import load_application_preferences


_cleanup_lock = threading.Lock()
_READY_RENAME_STATES = {"completed", "manual_required", "completed_no_video"}
_BLOCKED_SCRAPE_STATES = {"pending", "retry", "error", "waiting_completion"}


def _utc(value: datetime) -> datetime:
    """Normalize SQLite's timezone-naive timestamps before delay comparison."""

    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def cleanup_completed_torrent_records(
    db: Session | None = None,
    *,
    limit: int = 200,
    now: datetime | None = None,
    client: QBittorrentClient | None = None,
) -> dict[str, Any]:
    """Delete due qBittorrent task records without deleting downloaded files.

    The feature is controlled by the download settings.  A completed item is
    held until its configured delay has elapsed and local post-processing is no
    longer pending or failed.  Successful cleanup is persisted on the FeedItem
    so the same torrent is never submitted repeatedly.
    """

    if not _cleanup_lock.acquire(blocking=False):
        return {
            "ok": False,
            "enabled": True,
            "message": "已有 qBittorrent 完成任务清理正在运行",
            "checked": 0,
            "removed": 0,
            "blocked": 0,
            "errors": 0,
        }

    owns_session = db is None
    session = db or SessionLocal()
    try:
        policy = load_application_preferences(session).download
        if not policy.cleanup_completed_enabled:
            return {
                "ok": True,
                "enabled": False,
                "message": "qBittorrent 完成任务自动清理未启用",
                "checked": 0,
                "removed": 0,
                "blocked": 0,
                "errors": 0,
            }

        current = _utc(now or datetime.now(timezone.utc))
        cutoff = current - timedelta(minutes=policy.cleanup_completed_delay_minutes)
        items = list(
            session.scalars(
                select(FeedItem)
                .where(
                    FeedItem.completed_at.is_not(None),
                    FeedItem.completed_at <= cutoff,
                    FeedItem.torrent_hash != "",
                    FeedItem.qbit_record_removed_at.is_(None),
                )
                .order_by(FeedItem.completed_at, FeedItem.id)
                .limit(max(1, limit))
            )
        )

        stats = {"checked": len(items), "removed": 0, "blocked": 0, "errors": 0}
        downloader = client or QBittorrentClient()
        for item in items:
            # Do not remove the qBittorrent task while naming, Tracker handling,
            # or local metadata work still needs an operator retry.
            if (
                item.rename_status not in _READY_RENAME_STATES
                or item.scrape_status in _BLOCKED_SCRAPE_STATES
                or item.trackers_status == "error"
            ):
                stats["blocked"] += 1
                continue

            result = downloader.delete_torrent_record(item.torrent_hash)
            item.qbit_record_remove_message = result.message[:2000]
            if result.ok:
                item.qbit_record_removed_at = current
                stats["removed"] += 1
            else:
                stats["errors"] += 1

        if items and (stats["removed"] or stats["errors"]):
            details = (
                f"到期检查 {stats['checked']}，已删除记录 {stats['removed']}，"
                f"等待后处理 {stats['blocked']}，错误 {stats['errors']}\n"
                f"等待时间：{policy.cleanup_completed_delay_minutes} 分钟\n"
                "删除文件：否"
            )
            level = "INFO" if stats["errors"] == 0 else "WARNING"
            log_event(level, "qBittorrent 完成任务记录清理完成", details, persist=False)
            session.add(
                SystemLog(
                    level=level,
                    message="qBittorrent 完成任务记录清理完成",
                    details=details,
                )
            )

        session.commit()
        return {
            "ok": stats["errors"] == 0,
            "enabled": True,
            "message": "qBittorrent 完成任务记录清理完成",
            "delay_minutes": policy.cleanup_completed_delay_minutes,
            **stats,
        }
    finally:
        if owns_session:
            session.close()
        _cleanup_lock.release()
