from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import SessionLocal
from .downloader import QBittorrentClient
from .logging_service import record_event, record_exception
from .models import FeedItem


_normalize_lock = threading.Lock()
_ACTIVE_RENAME_STATES = {"", "pending", "retry", "error", "waiting_completion", "manual_required_waiting"}


def normalize_pending_items(db: Session | None = None, *, limit: int = 50, **_ignored: Any) -> dict[str, Any]:
    """Update qBittorrent progress and normalize single-video torrent names.

    Media scraping is not part of this workflow; only progress and naming are handled.
    """
    if not _normalize_lock.acquire(blocking=False):
        return {"ok": False, "message": "已有下载完成检查正在运行", "checked": 0}
    owns_session = db is None
    session = db or SessionLocal()
    stats = {"checked": 0, "renamed": 0, "completed": 0, "pending": 0, "manual_required": 0, "errors": 0}
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
            try:
                result = client.normalize_single_video(tag=item.qbit_tag, desired_name=item.desired_name)
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
            except Exception as exc:
                stats["errors"] += 1
                item.rename_status = "error"
                item.rename_message = f"后处理异常：{type(exc).__name__}: {exc}"[:2000]
                record_exception(
                    f"qBittorrent 后处理失败：条目 {item.id}",
                    exc,
                    source="postprocess",
                    context={"item_id": item.id},
                )
        if items:
            record_event(
                "INFO" if stats["errors"] == 0 else "WARNING",
                "qBittorrent 下载完成检查结束",
                f"检查 {stats['checked']}，规范化 {stats['renamed']}，完成 {stats['completed']}，等待 {stats['pending']}，需手动 {stats['manual_required']}，错误 {stats['errors']}",
                source="postprocess",
            )
            session.commit()
        return {"ok": True, "message": "下载完成与命名检查结束", **stats}
    finally:
        if owns_session:
            session.close()
        _normalize_lock.release()
