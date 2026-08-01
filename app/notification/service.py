"""Orchestrate template rendering and multi-channel notification delivery."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from ..models import FeedItem, Subscription, SystemLog
from .channels import PostCallable, send_bark, send_telegram, send_webhook
from .config import NOTIFICATION_EVENTS, NotificationConfig, load_notification_config
from .templates import render_notification, sample_payload
from .types import NotificationResult


def context_payload(
    event: str,
    title: str,
    message: str,
    *,
    subscription: Subscription | None,
    item: FeedItem | None,
    details: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the canonical payload shared by templates and webhooks."""

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
            "filename": str((details or {}).get("filename") or item.desired_name or item.title),
        },
        "details": details or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _public_image_url(value: object) -> str:
    """Return a Bark-compatible HTTP(S) artwork URL or an empty string."""

    cleaned = str(value or "").strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return cleaned


def safe_channel_error(exc: Exception, *, secrets: list[str]) -> str:
    """Return a user-visible error without leaking channel credentials."""

    text = str(exc)
    for secret in sorted({value for value in secrets if value}, key=len, reverse=True):
        text = text.replace(secret, "***")
    text = re.sub(r"(https://api\.telegram\.org/bot)[^/\s]+", r"\1***", text, flags=re.IGNORECASE)
    return text[:2000]


def preview_notification(*, event: str, title_template: str, body_template: str) -> dict[str, Any]:
    """Render the same sample payload and templates used by real delivery."""

    if event not in NOTIFICATION_EVENTS:
        raise ValueError(f"未知通知事件：{event}")
    payload = sample_payload(event)
    rendered_title, rendered_body = render_notification(
        payload,
        title_template=title_template,
        body_template=body_template,
    )
    return {
        "event": payload["event"],
        "title": rendered_title,
        "body": rendered_body,
        "context": payload,
    }


def _dispatch_telegram(
    config: NotificationConfig,
    db: Session,
    post: PostCallable,
    title: str,
    body: str,
) -> tuple[int, str | None]:
    if not config.telegram_enabled:
        return 0, None
    if not config.telegram_bot_token or not config.telegram_chat_id:
        return 0, "Telegram 配置不完整"
    try:
        send_telegram(
            post=post,
            db=db,
            bot_token=config.telegram_bot_token,
            chat_id=config.telegram_chat_id,
            title=title,
            body=body,
        )
        return 1, None
    except Exception as exc:
        return 0, f"Telegram：{safe_channel_error(exc, secrets=[config.telegram_bot_token])}"


def _dispatch_bark(
    config: NotificationConfig,
    db: Session,
    post: PostCallable,
    title: str,
    body: str,
    cover_url: str,
) -> tuple[int, str | None]:
    if not config.bark_enabled:
        return 0, None
    if not config.bark_device_key:
        return 0, "Bark 配置不完整"
    try:
        send_bark(
            post=post,
            db=db,
            server_url=config.bark_server_url,
            device_key=config.bark_device_key,
            title=title,
            body=body,
            icon=cover_url,
            image=cover_url,
        )
        return 1, None
    except Exception as exc:
        return 0, f"Bark：{safe_channel_error(exc, secrets=[config.bark_device_key])}"


def _dispatch_webhook(
    config: NotificationConfig,
    db: Session,
    post: PostCallable,
    payload: dict[str, Any],
) -> tuple[int, str | None]:
    if not config.webhook_enabled:
        return 0, None
    if not config.webhook_url:
        return 0, "Webhook 配置不完整"
    try:
        send_webhook(
            post=post,
            db=db,
            url=config.webhook_url,
            headers=config.webhook_headers,
            payload=payload,
        )
        return 1, None
    except Exception as exc:
        secrets = [config.webhook_url, *config.webhook_headers.values()]
        return 0, f"Webhook：{safe_channel_error(exc, secrets=secrets)}"


def send_notification(
    db: Session,
    event: str,
    title: str,
    message: str,
    *,
    post: PostCallable,
    subscription: Subscription | None = None,
    item: FeedItem | None = None,
    details: dict[str, Any] | None = None,
    force: bool = False,
) -> NotificationResult:
    """Render and deliver one notification to every enabled channel."""

    if event not in NOTIFICATION_EVENTS:
        raise ValueError(f"未知通知事件：{event}")
    config = load_notification_config(db)
    if not force and (not config.enabled or event not in config.events):
        return NotificationResult(ok=True, skipped=True)

    original_payload = context_payload(
        event,
        title.strip() or "FeedDock",
        message.strip(),
        subscription=subscription,
        item=item,
        details=details,
    )
    rendered_title, rendered_body = render_notification(
        original_payload,
        title_template=config.title_template,
        body_template=config.body_template,
    )
    payload = {
        **original_payload,
        "raw_title": original_payload["title"],
        "raw_message": original_payload["message"],
        "title": rendered_title,
        "message": rendered_body,
    }

    errors: list[str] = []
    sent = 0

    # Telegram
    t_sent, t_err = _dispatch_telegram(
        config, db, post, title=rendered_title, body=rendered_body
    )
    sent += t_sent
    if t_err:
        errors.append(t_err)

    # Bark
    cover_url = _public_image_url(
        (details or {}).get("cover_url")
        or (subscription.poster_url if subscription is not None else "")
    )
    b_sent, b_err = _dispatch_bark(
        config, db, post, title=rendered_title, body=rendered_body, cover_url=cover_url
    )
    sent += b_sent
    if b_err:
        errors.append(b_err)

    # Webhook
    w_sent, w_err = _dispatch_webhook(config, db, post, payload=payload)
    sent += w_sent
    if w_err:
        errors.append(w_err)

    if errors:
        db.add(SystemLog(
            level="WARNING",
            message=f"通知发送部分失败：{event}",
            details="；".join(errors)[:50000],
        ))
    return NotificationResult(ok=not errors and sent > 0, sent=sent, errors=errors)
