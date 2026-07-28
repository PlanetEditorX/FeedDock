"""Modular notification subsystem."""

from .channels import normalize_bark_push_url
from .config import NOTIFICATION_EVENTS, NotificationConfig, load_notification_config, reset_notification_config, save_notification_config
from .service import preview_notification
from .templates import DEFAULT_BODY_TEMPLATE, DEFAULT_TITLE_TEMPLATE, EVENT_LABELS, TEMPLATE_FIELDS
from .types import NotificationResult

__all__ = [
    "DEFAULT_BODY_TEMPLATE",
    "DEFAULT_TITLE_TEMPLATE",
    "EVENT_LABELS",
    "NOTIFICATION_EVENTS",
    "NotificationConfig",
    "NotificationResult",
    "TEMPLATE_FIELDS",
    "load_notification_config",
    "normalize_bark_push_url",
    "preview_notification",
    "reset_notification_config",
    "save_notification_config",
]
