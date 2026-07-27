from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import FeedItem, Subscription, SystemLog
from .notifications import send_notification
from .settings_config import load_application_preferences


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _whole_episode(value: str, total: int) -> int | None:
    try:
        number = Decimal(str(value).strip())
    except Exception:
        return None
    if number != number.to_integral_value():
        return None
    integer = int(number)
    return integer if 1 <= integer <= total else None


def tracked_episode_numbers(
    db: Session,
    subscription: Subscription,
    *,
    completed_only: bool = False,
) -> set[int]:
    if subscription.total_episodes <= 0:
        return set()
    statement = select(FeedItem.episode).where(
        FeedItem.subscription_id == subscription.id,
        FeedItem.status.in_(("queued", "scheduled")),
    )
    if completed_only:
        statement = statement.where(FeedItem.completed_at.is_not(None))
    numbers: set[int] = set()
    for value in db.scalars(statement):
        number = _whole_episode(value, subscription.total_episodes)
        if number is not None:
            numbers.add(number)
    return numbers


def calculate_missing_episodes(db: Session, subscription: Subscription) -> list[int]:
    if not subscription.missing_detection or subscription.total_episodes <= 0:
        return []
    tracked = tracked_episode_numbers(db, subscription)
    return [number for number in range(1, subscription.total_episodes + 1) if number not in tracked]


def evaluate_missing_episodes(db: Session, subscription: Subscription) -> list[int]:
    missing = calculate_missing_episodes(db, subscription)
    signature = ",".join(str(value) for value in missing)
    if signature == subscription.last_missing_signature:
        return missing
    subscription.last_missing_signature = signature
    if missing and len(missing) <= 10:
        preview = "、".join(str(value) for value in missing)
        send_notification(
            db,
            "missing_episodes",
            f"发现遗漏集数：{subscription.name}",
            f"当前缺少第 {preview} 集，共 {len(missing)} 集。",
            subscription=subscription,
            details={"missing_episodes": missing},
        )
    return missing


def reset_monitor_state_for_changes(
    subscription: Subscription,
    changes: dict[str, object],
) -> None:
    """Invalidate persisted dedup state when monitor inputs are edited."""

    def changed(field: str) -> bool:
        return field in changes and changes[field] != getattr(subscription, field)

    if changed("total_episodes"):
        subscription.completion_notified_at = None
        subscription.last_missing_signature = ""

    if changed("auto_disable_when_complete") and bool(changes["auto_disable_when_complete"]):
        subscription.completion_notified_at = None

    if any(changed(field) for field in (
        "missing_detection",
        "episode_regex",
        "episode_group",
        "episode_offset",
    )):
        subscription.last_missing_signature = ""

    if any(changed(field) for field in (
        "stale_days",
        "rss_url",
        "backup_rss_url",
        "include_keywords",
        "exclude_keywords",
        "air_date",
    )):
        subscription.last_stale_notified_at = None


def record_new_feed_activity(subscription: Subscription, *, now: datetime | None = None) -> None:
    current = now or datetime.now(timezone.utc)
    subscription.last_new_item_at = current
    subscription.last_stale_notified_at = None


def evaluate_stale_subscription(
    db: Session,
    subscription: Subscription,
    *,
    now: datetime | None = None,
) -> bool:
    if subscription.stale_days <= 0 or not subscription.enabled:
        return False
    current = now or datetime.now(timezone.utc)
    base = (
        _utc(subscription.last_new_item_at)
        or _utc(subscription.last_checked_at)
        or _utc(subscription.created_at)
        or current
    )
    if current - base < timedelta(days=subscription.stale_days):
        return False
    last_notice = _utc(subscription.last_stale_notified_at)
    if last_notice is not None and last_notice >= base:
        return False
    subscription.last_stale_notified_at = current
    send_notification(
        db,
        "stale_subscription",
        f"番剧长期未更新：{subscription.name}",
        f"已连续 {subscription.stale_days} 天没有发现新的匹配条目，请检查 RSS、字幕组或播出状态。",
        subscription=subscription,
        details={"stale_days": subscription.stale_days, "last_activity_at": base.isoformat()},
    )
    return True


def evaluate_subscription_completion(
    db: Session,
    subscription: Subscription,
    *,
    now: datetime | None = None,
) -> bool:
    global_enabled = load_application_preferences(db).rss.auto_disable_complete
    if not (subscription.auto_disable_when_complete or global_enabled) or subscription.total_episodes <= 0:
        return False
    expected = set(range(1, subscription.total_episodes + 1))
    completed = tracked_episode_numbers(db, subscription, completed_only=True)
    if not expected.issubset(completed):
        return False

    current = now or datetime.now(timezone.utc)
    first_notice = subscription.completion_notified_at is None
    subscription.completion_notified_at = subscription.completion_notified_at or current
    subscription.enabled = False
    if first_notice:
        db.add(SystemLog(
            level="INFO",
            message=f"订阅已自动停用：{subscription.name}",
            details=f"已确认第 1-{subscription.total_episodes} 集全部下载完成",
        ))
        send_notification(
            db,
            "subscription_completed",
            f"订阅已完结：{subscription.name}",
            f"第 1-{subscription.total_episodes} 集均已下载完成，订阅已自动停用。",
            subscription=subscription,
            details={"completed_episodes": sorted(completed)},
        )
    return True
