"""Public notification API.

Implementation details live under :mod:`app.notification`.  This compatibility
module keeps existing imports and patch points stable for callers and tests.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .models import FeedItem, Subscription
from .notification.service import safe_channel_error, send_notification as _send_notification
from .notification.types import NotificationResult
from .outbound import external_post


def _safe_channel_error(exc: Exception, *, secrets: list[str]) -> str:
    """Compatibility wrapper around the credential-redacting formatter."""

    return safe_channel_error(exc, secrets=secrets)


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
    """Send a notification using the configured templates and channels."""

    return _send_notification(
        db,
        event,
        title,
        message,
        post=external_post,
        subscription=subscription,
        item=item,
        details=details,
        force=force,
    )


__all__ = ["NotificationResult", "send_notification"]
