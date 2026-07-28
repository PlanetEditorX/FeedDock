"""Persistent notification settings stored in ``AppSetting`` rows."""

from __future__ import annotations

from dataclasses import dataclass
import json
from urllib.parse import urlparse

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import AppSetting
from .templates import (
    DEFAULT_BODY_TEMPLATE,
    DEFAULT_TITLE_TEMPLATE,
    EVENT_LABELS,
    validate_template,
)


NOTIFICATION_EVENTS = frozenset(EVENT_LABELS)

_NOTIFICATION_KEYS = {
    "notification_enabled",
    "notification_events",
    "notification_title_template",
    "notification_body_template",
    "notification_telegram_enabled",
    "notification_telegram_bot_token",
    "notification_telegram_chat_id",
    "notification_bark_enabled",
    "notification_bark_server_url",
    "notification_bark_device_key",
    "notification_webhook_enabled",
    "notification_webhook_url",
    "notification_webhook_headers_json",
}


@dataclass(frozen=True, slots=True)
class NotificationConfig:
    enabled: bool = False
    events: frozenset[str] = frozenset(NOTIFICATION_EVENTS)
    title_template: str = DEFAULT_TITLE_TEMPLATE
    body_template: str = DEFAULT_BODY_TEMPLATE
    telegram_enabled: bool = False
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    bark_enabled: bool = False
    bark_server_url: str = "https://api.day.app"
    bark_device_key: str = ""
    webhook_enabled: bool = False
    webhook_url: str = ""
    webhook_headers_json: str = "{}"
    source: str = "web"

    @property
    def configured_channels(self) -> tuple[str, ...]:
        channels: list[str] = []
        if self.telegram_enabled and self.telegram_bot_token and self.telegram_chat_id:
            channels.append("telegram")
        if self.bark_enabled and self.bark_server_url and self.bark_device_key:
            channels.append("bark")
        if self.webhook_enabled and self.webhook_url:
            channels.append("webhook")
        return tuple(channels)

    @property
    def configured(self) -> bool:
        return bool(self.configured_channels)

    @property
    def webhook_headers(self) -> dict[str, str]:
        try:
            value = json.loads(self.webhook_headers_json or "{}")
        except json.JSONDecodeError:
            return {}
        if not isinstance(value, dict):
            return {}
        return {str(key): str(item) for key, item in value.items()}

    def public_dict(self) -> dict[str, object]:
        """Return browser-safe settings; channel credentials are never exposed."""

        return {
            "enabled": self.enabled,
            "events": sorted(self.events),
            "title_template": self.title_template,
            "body_template": self.body_template,
            "telegram_enabled": self.telegram_enabled,
            "telegram_bot_token_configured": bool(self.telegram_bot_token),
            "telegram_chat_id": self.telegram_chat_id,
            "bark_enabled": self.bark_enabled,
            "bark_server_url": self.bark_server_url,
            "bark_device_key_configured": bool(self.bark_device_key),
            "webhook_enabled": self.webhook_enabled,
            "webhook_url_configured": bool(self.webhook_url),
            "webhook_headers_configured": bool(self.webhook_headers),
            "configured_channels": list(self.configured_channels),
            "configured": self.configured,
            "source": self.source,
        }


def _as_bool(value: str, default: bool = False) -> bool:
    if value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _valid_http_url(value: str, field_name: str, *, allow_empty: bool = True) -> str:
    cleaned = value.strip().rstrip("/")
    if not cleaned and allow_empty:
        return ""
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field_name}必须是有效的 HTTP 或 HTTPS 地址")
    if len(cleaned) > 4000:
        raise ValueError(f"{field_name}过长")
    return cleaned


def _normalize_events(events: object) -> frozenset[str]:
    if isinstance(events, str):
        values = [part.strip() for part in events.split(",")]
    else:
        values = [str(part).strip() for part in (events or [])]
    invalid = sorted({value for value in values if value and value not in NOTIFICATION_EVENTS})
    if invalid:
        raise ValueError(f"未知通知事件：{', '.join(invalid)}")
    return frozenset(value for value in values if value)



def _stored_template(value: str | None, default: str, field_name: str, max_length: int) -> str:
    """Load imported/legacy template values defensively, falling back to defaults."""

    try:
        return validate_template(value or default, field_name, max_length=max_length)
    except ValueError:
        return default

def load_notification_config(db: Session) -> NotificationConfig:
    rows = {
        row.key: row.value
        for row in db.scalars(select(AppSetting).where(AppSetting.key.in_(_NOTIFICATION_KEYS)))
    }
    events = _normalize_events(rows.get("notification_events", ",".join(sorted(NOTIFICATION_EVENTS))))
    return NotificationConfig(
        enabled=_as_bool(rows.get("notification_enabled", "0")),
        events=events,
        title_template=_stored_template(rows.get("notification_title_template"), DEFAULT_TITLE_TEMPLATE, "通知标题模板", 1000),
        body_template=_stored_template(rows.get("notification_body_template"), DEFAULT_BODY_TEMPLATE, "通知正文模板", 10000),
        telegram_enabled=_as_bool(rows.get("notification_telegram_enabled", "0")),
        telegram_bot_token=rows.get("notification_telegram_bot_token", ""),
        telegram_chat_id=rows.get("notification_telegram_chat_id", "").strip(),
        bark_enabled=_as_bool(rows.get("notification_bark_enabled", "0")),
        bark_server_url=(
            rows.get("notification_bark_server_url", "https://api.day.app").strip().rstrip("/")
            or "https://api.day.app"
        ),
        bark_device_key=rows.get("notification_bark_device_key", ""),
        webhook_enabled=_as_bool(rows.get("notification_webhook_enabled", "0")),
        webhook_url=rows.get("notification_webhook_url", "").strip(),
        webhook_headers_json=rows.get("notification_webhook_headers_json", "{}"),
        source="web",
    )


def save_notification_config(
    db: Session,
    *,
    enabled: bool,
    events: object,
    title_template: str = DEFAULT_TITLE_TEMPLATE,
    body_template: str = DEFAULT_BODY_TEMPLATE,
    telegram_enabled: bool,
    telegram_bot_token: str | None,
    clear_telegram_bot_token: bool,
    telegram_chat_id: str,
    bark_enabled: bool,
    bark_server_url: str,
    bark_device_key: str | None,
    clear_bark_device_key: bool,
    webhook_enabled: bool,
    webhook_url: str | None,
    clear_webhook_url: bool,
    webhook_headers_json: str | None,
    clear_webhook_headers: bool,
) -> NotificationConfig:
    current = load_notification_config(db)
    normalized_events = _normalize_events(events)
    normalized_title_template = validate_template(title_template, "通知标题模板", max_length=1000)
    normalized_body_template = validate_template(body_template, "通知正文模板", max_length=10000)
    token = "" if clear_telegram_bot_token else (
        current.telegram_bot_token if telegram_bot_token is None else telegram_bot_token.strip()
    )
    device_key = "" if clear_bark_device_key else (
        current.bark_device_key if bark_device_key is None else bark_device_key.strip()
    )
    target_webhook_url = "" if clear_webhook_url else (
        current.webhook_url if webhook_url is None else webhook_url.strip()
    )
    headers_raw = "{}" if clear_webhook_headers else (
        current.webhook_headers_json if webhook_headers_json is None else webhook_headers_json.strip() or "{}"
    )

    if len(token) > 1000:
        raise ValueError("Telegram Bot Token 过长")
    chat_id = telegram_chat_id.strip()
    if len(chat_id) > 300:
        raise ValueError("Telegram Chat ID 过长")
    if len(device_key) > 1000:
        raise ValueError("Bark Device Key 过长")
    bark_url = _valid_http_url(bark_server_url or "https://api.day.app", "Bark 服务地址", allow_empty=False)
    target_webhook_url = _valid_http_url(target_webhook_url, "Webhook 地址")
    try:
        headers = json.loads(headers_raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Webhook 请求头必须是 JSON 对象") from exc
    if not isinstance(headers, dict) or any(not isinstance(key, str) for key in headers):
        raise ValueError("Webhook 请求头必须是 JSON 对象")
    headers_raw = json.dumps(
        {str(key): str(value) for key, value in headers.items()},
        ensure_ascii=False,
        separators=(",", ":"),
    )

    if telegram_enabled and (not token or not chat_id):
        raise ValueError("启用 Telegram 时必须填写 Bot Token 和 Chat ID")
    if bark_enabled and not device_key:
        raise ValueError("启用 Bark 时必须填写 Device Key")
    if webhook_enabled and not target_webhook_url:
        raise ValueError("启用 Webhook 时必须填写地址")
    if enabled and not normalized_events:
        raise ValueError("启用通知中心时至少需要选择一个通知事件")
    if enabled and not any((telegram_enabled, bark_enabled, webhook_enabled)):
        raise ValueError("启用通知中心时至少需要启用一个通知渠道")

    values = {
        "notification_enabled": "1" if enabled else "0",
        "notification_events": ",".join(sorted(normalized_events)),
        "notification_title_template": normalized_title_template,
        "notification_body_template": normalized_body_template,
        "notification_telegram_enabled": "1" if telegram_enabled else "0",
        "notification_telegram_bot_token": token,
        "notification_telegram_chat_id": chat_id,
        "notification_bark_enabled": "1" if bark_enabled else "0",
        "notification_bark_server_url": bark_url,
        "notification_bark_device_key": device_key,
        "notification_webhook_enabled": "1" if webhook_enabled else "0",
        "notification_webhook_url": target_webhook_url,
        "notification_webhook_headers_json": headers_raw,
    }
    existing = {
        row.key: row
        for row in db.scalars(select(AppSetting).where(AppSetting.key.in_(_NOTIFICATION_KEYS)))
    }
    for key, value in values.items():
        row = existing.get(key)
        if row is None:
            db.add(AppSetting(key=key, value=value))
        else:
            row.value = value
    db.commit()
    return load_notification_config(db)


def reset_notification_config(db: Session) -> NotificationConfig:
    db.execute(delete(AppSetting).where(AppSetting.key.in_(_NOTIFICATION_KEYS)))
    db.commit()
    return load_notification_config(db)
