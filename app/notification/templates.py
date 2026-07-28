"""Notification template validation and rendering.

Templates deliberately expose only flat, documented placeholder names.  This
keeps rendering deterministic and prevents attribute/index traversal through
``str.format`` expressions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from string import Formatter
from typing import Any, Mapping


EVENT_LABELS: dict[str, str] = {
    "download_started": "开始下载",
    "download_completed": "下载完成",
    "missing_episodes": "发现遗漏",
    "subscription_completed": "订阅完结",
    "rss_error": "RSS 或推送错误",
    "stale_subscription": "长期未更新",
}

DEFAULT_TITLE_TEMPLATE = "{title}"
DEFAULT_BODY_TEMPLATE = "{message}"

TEMPLATE_FIELDS = frozenset({
    "event",
    "event_label",
    "title",
    "message",
    "subscription_name",
    "subscription_id",
    "item_title",
    "item_episode",
    "item_status",
    "timestamp",
})


class _TemplateValues(dict[str, Any]):
    """Return an empty string for optional values missing from the context."""

    def __missing__(self, key: str) -> str:
        return ""


def validate_template(value: str, field_name: str, *, max_length: int) -> str:
    """Validate a user-supplied notification template and return it trimmed.

    Only simple field names are accepted. Format specifications, conversions,
    dotted attributes, and index expressions are rejected to keep templates
    predictable and safe.
    """

    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError(f"{field_name}不能为空")
    if len(cleaned) > max_length:
        raise ValueError(f"{field_name}过长")

    try:
        parts = list(Formatter().parse(cleaned))
    except ValueError as exc:
        raise ValueError(f"{field_name}格式无效：花括号不匹配") from exc

    for _, field, format_spec, conversion in parts:
        if field is None:
            continue
        if field not in TEMPLATE_FIELDS:
            raise ValueError(f"{field_name}包含未知变量：{field}")
        if format_spec or conversion:
            raise ValueError(f"{field_name}不支持格式说明或类型转换：{field}")
    return cleaned


def template_context(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Flatten the delivery payload into the documented template variables."""

    subscription = payload.get("subscription") or {}
    item = payload.get("item") or {}
    event = str(payload.get("event") or "")
    return {
        "event": event,
        "event_label": EVENT_LABELS.get(event, event),
        "title": str(payload.get("title") or ""),
        "message": str(payload.get("message") or ""),
        "subscription_name": str(subscription.get("name") or ""),
        "subscription_id": subscription.get("id") or "",
        "item_title": str(item.get("title") or ""),
        "item_episode": item.get("episode") or "",
        "item_status": str(item.get("status") or ""),
        "timestamp": str(payload.get("timestamp") or ""),
    }


def render_template(template: str, payload: Mapping[str, Any]) -> str:
    """Render a previously validated template against a notification payload."""

    return template.format_map(_TemplateValues(template_context(payload))).strip()


def render_notification(
    payload: Mapping[str, Any],
    *,
    title_template: str,
    body_template: str,
) -> tuple[str, str]:
    """Render title and body exactly as delivery channels will receive them."""

    title = render_template(title_template, payload) or "FeedDock"
    body = render_template(body_template, payload)
    return title, body


def sample_payload(event: str) -> dict[str, Any]:
    """Build stable sample data used by the settings-page preview."""

    normalized_event = event if event in EVENT_LABELS else "download_started"
    samples = {
        "download_started": ("开始下载", "示例番剧第 1 集已推送到下载器。"),
        "download_completed": ("下载完成", "示例番剧第 1 集已完成下载和命名。"),
        "missing_episodes": ("发现遗漏", "示例番剧缺少第 2 集。"),
        "subscription_completed": ("订阅完结", "示例番剧已全部下载，订阅已自动停用。"),
        "rss_error": ("RSS 检查失败", "示例 RSS 请求返回异常，请检查地址或网络。"),
        "stale_subscription": ("订阅长期未更新", "示例番剧已连续 14 天没有新条目。"),
    }
    title, message = samples[normalized_event]
    return {
        "event": normalized_event,
        "title": title,
        "message": message,
        "subscription": {
            "id": 1001,
            "name": "示例番剧",
            "enabled": True,
            "total_episodes": 12,
        },
        "item": {
            "id": 2001,
            "title": "[字幕组] 示例番剧 [01][1080P]",
            "episode": 1,
            "status": "queued",
            "save_path": "/media/示例番剧/Season 01",
        },
        "details": {"preview": True},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
