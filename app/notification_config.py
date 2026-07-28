"""Backward-compatible imports for the modular notification configuration."""

from .notification.config import (  # noqa: F401
    NOTIFICATION_EVENTS,
    NotificationConfig,
    load_notification_config,
    reset_notification_config,
    save_notification_config,
)

__all__ = [
    "NOTIFICATION_EVENTS",
    "NotificationConfig",
    "load_notification_config",
    "reset_notification_config",
    "save_notification_config",
]
