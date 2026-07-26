from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import SessionLocal
from .downloader import QBittorrentClient
from .models import FeedItem, SystemLog


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
    }
    try:
        items = list(
            session.scalars(
                select(FeedItem)
                .where(
                    FeedItem.status == "queued",
                    FeedItem.qbit_tag != "",
                    FeedItem.rename_status.in_(_ACTIVE_RENAME_STATES),
                )
                .order_by(FeedItem.id)
                .limit(limit)
            )
        )
        client = QBittorrentClient()
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

            if "已规范化" in result.message and previous_state not in {"completed", "manual_required"}:
                stats["renamed"] += 1

            if result.completed:
                stats["completed"] += 1
                item.completed_at = item.completed_at or datetime.now(timezone.utc)
                item.scrape_status = "skipped"
                item.scrape_message = "FeedDock 已移除刮削功能，请交由外部媒体库识别"

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

        if items:
            session.add(
                SystemLog(
                    level="INFO" if stats["errors"] == 0 else "WARNING",
                    message="qBittorrent 下载完成检查完成",
                    details=(
                        f"检查 {stats['checked']}，已规范化 {stats['renamed']}，"
                        f"下载完成 {stats['completed']}，等待 {stats['pending']}，"
                        f"需手动处理 {stats['manual_required']}，"
                        f"错误 {stats['errors']}"
                    ),
                )
            )
        session.commit()
        return {"ok": True, "message": "下载完成检查完成", **stats}
    finally:
        if owns_session:
            session.close()
        _normalize_lock.release()
