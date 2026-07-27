from __future__ import annotations

import threading
from typing import Any

from sqlalchemy import select

from .database import SessionLocal
from .debug_logging import format_exception_details, log_event
from .metadata_service import MetadataService
from .models import Subscription, SystemLog
from .settings_config import load_application_preferences


_metadata_refresh_lock = threading.Lock()


def _add_log(db, level: str, message: str, details: str = "") -> None:
    normalized = level.upper()
    safe_details = details[:50000]
    log_event(normalized, message, safe_details, persist=False)
    db.add(SystemLog(level=normalized, message=message, details=safe_details))


def refresh_all_metadata() -> dict[str, Any]:
    """Synchronize metadata for every subscription without refreshing RSS feeds."""

    if not _metadata_refresh_lock.acquire(blocking=False):
        with SessionLocal() as db:
            _add_log(db, "WARNING", "同步订阅元数据未启动", "已有元数据同步任务正在运行")
            db.commit()
        return {"ok": False, "message": "已有元数据同步任务正在运行", "subscriptions": 0}

    totals = {"subscriptions": 0, "updated": 0, "errors": 0}
    try:
        with SessionLocal() as db:
            subscriptions = list(db.scalars(select(Subscription).order_by(Subscription.id)))
            _add_log(db, "INFO", "开始同步订阅元数据", f"待处理订阅：{len(subscriptions)}")
            db.commit()
            service = MetadataService(timeout=load_application_preferences(db).rss.timeout_seconds)
            for subscription in subscriptions:
                totals["subscriptions"] += 1
                try:
                    record = service.sync(db, subscription, "auto")
                    totals["updated"] += 1
                    _add_log(
                        db,
                        "INFO",
                        f"订阅元数据已同步：{subscription.name}",
                        (
                            f"订阅 ID：{subscription.id}\n"
                            f"来源：{record.provider}\n"
                            f"元数据 ID：{record.id}\n"
                            f"总集数：{record.total_episodes or subscription.total_episodes or 0}"
                        ),
                    )
                except Exception as exc:
                    totals["errors"] += 1
                    _add_log(
                        db,
                        "WARNING",
                        f"订阅元数据同步失败：{subscription.name}",
                        format_exception_details(
                            exc,
                            stage="metadata.refresh-all",
                            context={
                                "subscription_id": subscription.id,
                                "subscription_name": subscription.name,
                            },
                        ),
                    )
                db.commit()

            _add_log(
                db,
                "INFO" if totals["errors"] == 0 else "WARNING",
                "同步订阅元数据完成",
                (
                    f"订阅 {totals['subscriptions']}，"
                    f"成功 {totals['updated']}，错误 {totals['errors']}"
                ),
            )
            db.commit()
        return {
            "ok": totals["errors"] == 0,
            "message": "订阅元数据同步完成",
            **totals,
        }
    finally:
        _metadata_refresh_lock.release()
