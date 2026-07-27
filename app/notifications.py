from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
from typing import Any

from sqlalchemy.orm import Session

from .models import FeedItem, Subscription, SystemLog
from .notification_config import NOTIFICATION_EVENTS, load_notification_config
from .outbound import external_post


@dataclass(slots=True)
class NotificationResult:
    ok: bool
    sent: int = 0
    skipped: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def message(self) -> str:
        if self.skipped:
            return "通知未启用或事件未勾选"
        if self.ok:
            return f"通知发送成功，共 {self.sent} 个渠道"
        return "；".join(self.errors) or "通知发送失败"


def _context_payload(
    event: str,
    title: str,
    message: str,
    *,
    subscription: Subscription | None,
    item: FeedItem | None,
    details: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "event": event,
        "title": title,
        "message": message,
        "subscription": None if subscription is None else {
            "id": subscription.id,
            "name": subscription.name,
            "enabled": subscription.enabled,
            "total_episodes": subscription.total_episodes,
        },
        "item": None if item is None else {
            "id": item.id,
            "title": item.title,
            "episode": item.episode,
            "status": item.status,
            "save_path": item.save_path,
        },
        "details": details or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _safe_channel_error(exc: Exception, *, secrets: list[str]) -> str:
    """Return a user-visible error without leaking channel credentials."""

    text = str(exc)
    for secret in sorted({value for value in secrets if value}, key=len, reverse=True):
        text = text.replace(secret, "***")
    text = re.sub(r"(https://api\.telegram\.org/bot)[^/\s]+", r"\1***", text, flags=re.IGNORECASE)
    return text[:2000]


def send_notification(
    db: Session,
    event: str,
    title: str,
    message: str,
    *,
    subscription: Subscription | None = None,
    item: FeedItem | None = None,
    details: dict[str, Any] | None = None,
    force: bool = False,
) -> NotificationResult:
    if event not in NOTIFICATION_EVENTS:
        raise ValueError(f"未知通知事件：{event}")
    config = load_notification_config(db)
    if not force and (not config.enabled or event not in config.events):
        return NotificationResult(ok=True, skipped=True)

    payload = _context_payload(
        event, title.strip() or "FeedDock", message.strip(),
        subscription=subscription, item=item, details=details,
    )
    errors: list[str] = []
    sent = 0

    if config.telegram_enabled:
        if not config.telegram_bot_token or not config.telegram_chat_id:
            errors.append("Telegram 配置不完整")
        else:
            try:
                response = external_post(
                    f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage",
                    db=db,
                    json={
                        "chat_id": config.telegram_chat_id,
                        "text": f"{payload['title']}\n\n{payload['message']}",
                        "disable_web_page_preview": True,
                    },
                )
                response.raise_for_status()
                sent += 1
            except Exception as exc:
                errors.append(f"Telegram：{_safe_channel_error(exc, secrets=[config.telegram_bot_token])}")

    if config.bark_enabled:
        if not config.bark_device_key:
            errors.append("Bark 配置不完整")
        else:
            try:
                response = external_post(
                    f"{config.bark_server_url.rstrip('/')}/push",
                    db=db,
                    json={
                        "title": payload["title"],
                        "body": payload["message"],
                        "device_key": config.bark_device_key,
                        "group": "FeedDock",
                    },
                )
                response.raise_for_status()
                sent += 1
            except Exception as exc:
                errors.append(f"Bark：{_safe_channel_error(exc, secrets=[config.bark_device_key])}")

    if config.webhook_enabled:
        if not config.webhook_url:
            errors.append("Webhook 配置不完整")
        else:
            try:
                headers = {"Content-Type": "application/json", **config.webhook_headers}
                response = external_post(config.webhook_url, db=db, headers=headers, json=payload)
                response.raise_for_status()
                sent += 1
            except Exception as exc:
                errors.append(
                    f"Webhook：{_safe_channel_error(exc, secrets=[config.webhook_url, *config.webhook_headers.values()])}"
                )

    if errors:
        db.add(SystemLog(
            level="WARNING",
            message=f"通知发送部分失败：{event}",
            details="；".join(errors)[:50000],
        ))
    return NotificationResult(ok=not errors and sent > 0, sent=sent, errors=errors)
