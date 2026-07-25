from __future__ import annotations

import threading
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .database import SessionLocal
from .downloader import QBittorrentClient
from .models import FeedItem, SystemLog


_normalize_lock = threading.Lock()


def normalize_pending_items(db: Session | None = None, *, limit: int = 50) -> dict[str, Any]:
    if not _normalize_lock.acquire(blocking=False):
        return {"ok": False, "message": "已有重命名检查正在运行", "checked": 0}
    owns_session = db is None
    session = db or SessionLocal()
    stats = {"checked": 0, "renamed": 0, "pending": 0, "manual_required": 0, "errors": 0, "scraped": 0}
    emby_refresh_needed = False
    try:
        items = list(
            session.scalars(
                select(FeedItem)
                .where(
                    FeedItem.status == "queued",
                    FeedItem.qbit_tag != "",
                    FeedItem.desired_name != "",
                    or_(
                        FeedItem.rename_status == "",
                        FeedItem.rename_status == "pending",
                        FeedItem.rename_status == "retry",
                        FeedItem.rename_status == "error",
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
            item.rename_status = result.state
            item.rename_message = result.message[:2000]
            if result.torrent_hash:
                item.torrent_hash = result.torrent_hash
            if result.state == "renamed":
                stats["renamed"] += 1
                subscription = item.subscription
                if subscription and subscription.scrape_enabled:
                    try:
                        from .scraper import scrape_subscription

                        scrape_result = scrape_subscription(session, subscription)
                        item.rename_message = f"{item.rename_message}；{scrape_result.message}"[:2000]
                        if scrape_result.ok:
                            stats["scraped"] += 1
                            emby_refresh_needed = True
                    except Exception as exc:
                        item.rename_message = f"{item.rename_message}；自动刮削失败：{exc}"[:2000]
            elif result.state == "pending":
                stats["pending"] += 1
            elif result.state == "manual_required":
                stats["manual_required"] += 1
            else:
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
                    message="qBittorrent 规范命名检查完成",
                    details=(
                        f"检查 {stats['checked']}，已重命名 {stats['renamed']}，"
                        f"等待元数据 {stats['pending']}，需手动处理 {stats['manual_required']}，"
                        f"本地刮削 {stats['scraped']}，错误 {stats['errors']}"
                    ),
                )
            )
            session.commit()
        return {"ok": True, "message": "规范命名检查完成", **stats}
    finally:
        if owns_session:
            session.close()
        _normalize_lock.release()
