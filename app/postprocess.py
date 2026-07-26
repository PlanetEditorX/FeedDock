from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_, select
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
_ACTIVE_SCRAPE_STATES = {"", "pending", "retry", "error"}


def normalize_pending_items(db: Session | None = None, *, limit: int = 50) -> dict[str, Any]:
    """Normalize tagged torrents and scrape only after qBittorrent reaches 100%."""

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
    emby_refresh_needed = False
    try:
        items = list(
            session.scalars(
                select(FeedItem)
                .where(
                    FeedItem.status == "queued",
                    FeedItem.qbit_tag != "",
                    or_(
                        FeedItem.rename_status.in_(_ACTIVE_RENAME_STATES),
                        FeedItem.scrape_status.in_(_ACTIVE_SCRAPE_STATES),
                    ),
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
                subscription = item.subscription
                if subscription and subscription.scrape_enabled:
                    if item.scrape_status != "success":
                        try:
                            from .scraper import scrape_subscription

                            scrape_result = scrape_subscription(session, subscription)
                            item.scrape_message = scrape_result.message[:2000]
                            if scrape_result.ok:
                                item.scrape_status = "success"
                                item.scraped_at = datetime.now(timezone.utc)
                                stats["scraped"] += 1
                                emby_refresh_needed = True
                            else:
                                item.scrape_status = "error"
                                stats["errors"] += 1
                        except Exception as exc:
                            item.scrape_status = "error"
                            item.scrape_message = f"自动刮削失败：{exc}"[:2000]
                            stats["errors"] += 1
                else:
                    item.scrape_status = "skipped"
                    item.scrape_message = "订阅未启用本地刮削"

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

        if emby_refresh_needed:
            try:
                from .scraper import refresh_emby_library

                refresh_emby_library(session)
            except Exception:
                pass
        if items:
            session.add(
                SystemLog(
                    level="INFO" if stats["errors"] == 0 else "WARNING",
                    message="qBittorrent 下载完成与刮削检查完成",
                    details=(
                        f"检查 {stats['checked']}，已规范化 {stats['renamed']}，"
                        f"下载完成 {stats['completed']}，等待 {stats['pending']}，"
                        f"需手动处理 {stats['manual_required']}，本地刮削 {stats['scraped']}，"
                        f"错误 {stats['errors']}"
                    ),
                )
            )
            session.commit()
        return {"ok": True, "message": "下载完成与刮削检查完成", **stats}
    finally:
        if owns_session:
            session.close()
        _normalize_lock.release()
