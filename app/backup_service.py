from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import settings
from .models import AnimePreference, AppSetting, Subscription
from .notification_config import load_notification_config
from .runtime_config import (
    get_app_setting,
    load_automation_config,
    load_metadata_config,
    load_proxy_config,
    load_qbittorrent_config,
    load_rss_poll_config,
)
from .settings_config import load_application_preferences
from .schemas import SubscriptionCreate

BACKUP_FORMAT = "feeddock-system-backup"
BACKUP_VERSION = 1

_SENSITIVE_SETTING_KEYS = {
    "qbit_password",
    "tmdb_read_access_token",
    "bangumi_access_token",
    "emby_api_key",
    "tmm_api_key",
    "proxy_url",
    "notification_telegram_bot_token",
    "notification_bark_device_key",
    "notification_webhook_url",
    "notification_webhook_headers_json",
}

_TRANSIENT_SETTING_KEYS = {
    "automation_last_run_date",
    "trackers_cached_json",
    "trackers_updated_at",
    "update_api_last_checked_at",
    "update_manifest_cache_json",
    "update_manifest_checked_at",
    "update_manifest_etag",
    "update_manifest_last_modified",
    "update_manifest_source_url",
}


def is_exportable_setting(key: str) -> bool:
    normalized = str(key or "").strip()
    if not normalized or normalized.startswith("migration:"):
        return False
    return normalized not in _TRANSIENT_SETTING_KEYS


def is_sensitive_setting(key: str) -> bool:
    return str(key or "").strip() in _SENSITIVE_SETTING_KEYS




def _bool_text(value: bool) -> str:
    return "1" if value else "0"


def effective_setting_values(db: Session) -> dict[str, str]:
    qbit = load_qbittorrent_config(db)
    metadata = load_metadata_config(db)
    automation = load_automation_config(db)
    proxy = load_proxy_config(db)
    rss_poll = load_rss_poll_config(db)
    preferences = load_application_preferences(db)
    notifications = load_notification_config(db)
    return {
        "qbit_url": qbit.url,
        "qbit_username": qbit.username,
        "qbit_password": qbit.password,
        "qbit_category": qbit.category,
        "download_path": qbit.download_path,
        "page_theme_color": preferences.page.theme_color,
        "subscription_sort_mode": preferences.page.subscription_sort,
        "download_retry_count": str(preferences.download.retry_count),
        "download_concurrent_limit": str(preferences.download.concurrent_limit),
        "download_seeding_minutes": str(preferences.download.seeding_minutes),
        "download_cleanup_completed_enabled": _bool_text(
            preferences.download.cleanup_completed_enabled
        ),
        "download_cleanup_completed_delay_minutes": str(
            preferences.download.cleanup_completed_delay_minutes
        ),
        "rss_enabled": _bool_text(preferences.rss.enabled),
        "rss_timeout_seconds": str(preferences.rss.timeout_seconds),
        "rss_auto_skip_existing": _bool_text(preferences.rss.auto_skip_existing),
        "rss_auto_disable_complete": _bool_text(preferences.rss.auto_disable_complete),
        "trackers_enabled": _bool_text(preferences.trackers.enabled),
        "trackers_update_url": preferences.trackers.update_url,
        "rss_poll_interval_minutes": str(rss_poll.minutes),
        "tmdb_read_access_token": metadata.tmdb_read_access_token,
        "bangumi_access_token": metadata.bangumi_access_token,
        "metadata_language": metadata.language,
        "tmdb_api_base": metadata.tmdb_api_base,
        "tmdb_image_base": metadata.tmdb_image_base,
        "metadata_auto_scrape_enabled": _bool_text(metadata.auto_scrape_enabled),
        "metadata_follow_days": str(metadata.follow_days),
        "metadata_bangumi_ini_enabled": _bool_text(metadata.bangumi_ini_enabled),
        "media_local_root": metadata.media_local_root,
        "emby_url": metadata.emby_url,
        "emby_api_key": metadata.emby_api_key,
        "tmm_url": metadata.tmm_url,
        "tmm_api_key": metadata.tmm_api_key,
        "tmm_enabled": _bool_text(metadata.tmm_enabled),
        "automation_download_enabled": _bool_text(automation.download_enabled),
        "automation_scrape_enabled": "0",
        "automation_time": automation.daily_time,
        "automation_timezone": automation.timezone,
        "proxy_enabled": _bool_text(proxy.enabled),
        "proxy_url": proxy.url,
        "proxy_no_proxy": proxy.no_proxy,
        "notification_enabled": _bool_text(notifications.enabled),
        "notification_events": ",".join(sorted(notifications.events)),
        "notification_title_template": notifications.title_template,
        "notification_body_template": notifications.body_template,
        "notification_telegram_enabled": _bool_text(notifications.telegram_enabled),
        "notification_telegram_bot_token": notifications.telegram_bot_token,
        "notification_telegram_chat_id": notifications.telegram_chat_id,
        "notification_bark_enabled": _bool_text(notifications.bark_enabled),
        "notification_bark_server_url": notifications.bark_server_url,
        "notification_bark_device_key": notifications.bark_device_key,
        "notification_webhook_enabled": _bool_text(notifications.webhook_enabled),
        "notification_webhook_url": notifications.webhook_url,
        "notification_webhook_headers_json": notifications.webhook_headers_json,
        "global_exclude_rules": get_app_setting("global_exclude_rules", "", db),
        "log_level": get_app_setting("log_level", settings.log_level, db),
    }


def subscription_export_values(subscription: Subscription) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for field_name in SubscriptionCreate.model_fields:
        value = getattr(subscription, field_name)
        if isinstance(value, (date, datetime)):
            value = value.isoformat()
        if field_name in {"air_date", "backup_rss_url"}:
            value = value or None
        values[field_name] = value
    return values


def export_subscriptions_payload(
    db: Session,
    *,
    ids: list[int] | None = None,
) -> dict[str, Any]:
    query = select(Subscription).order_by(Subscription.id)
    if ids:
        query = query.where(Subscription.id.in_(ids))
    subscriptions = list(db.scalars(query))
    return {
        "format": "feeddock-subscriptions",
        "version": 2,
        "app_version": settings.app_version,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "subscriptions": [subscription_export_values(item) for item in subscriptions],
    }


def export_system_backup(
    db: Session,
    *,
    include_secrets: bool = False,
) -> dict[str, Any]:
    settings_payload = effective_setting_values(db)
    for row in db.scalars(select(AppSetting).order_by(AppSetting.key)):
        if is_exportable_setting(row.key):
            settings_payload[row.key] = row.value
    omitted_secrets: list[str] = []
    if not include_secrets:
        for key in sorted(_SENSITIVE_SETTING_KEYS):
            if key in settings_payload and settings_payload[key]:
                omitted_secrets.append(key)
            settings_payload.pop(key, None)

    subscriptions = list(db.scalars(select(Subscription).order_by(Subscription.id)))
    preferences = list(db.scalars(select(AnimePreference).order_by(AnimePreference.canonical_key)))
    return {
        "format": BACKUP_FORMAT,
        "version": BACKUP_VERSION,
        "app_version": settings.app_version,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "secrets_included": bool(include_secrets),
        "omitted_secret_keys": omitted_secrets,
        "settings": settings_payload,
        "subscriptions": [subscription_export_values(item) for item in subscriptions],
        "anime_preferences": [
            {
                "canonical_key": row.canonical_key,
                "bangumi_id": row.bangumi_id,
                "title_normalized": row.title_normalized,
                "hidden": row.hidden,
                "reason": row.reason,
            }
            for row in preferences
        ],
    }


def validate_system_backup(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("系统备份必须是 JSON 对象")
    if payload.get("format") != BACKUP_FORMAT:
        raise ValueError("不是 FeedDock 系统备份文件")
    try:
        version = int(payload.get("version") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("系统备份版本无效") from exc
    if version <= 0 or version > BACKUP_VERSION:
        raise ValueError(f"暂不支持该系统备份版本：{version}")
    if not isinstance(payload.get("settings", {}), dict):
        raise ValueError("系统备份中的 settings 必须是对象")
    if not isinstance(payload.get("subscriptions", []), list):
        raise ValueError("系统备份中的 subscriptions 必须是数组")
    if not isinstance(payload.get("anime_preferences", []), list):
        raise ValueError("系统备份中的 anime_preferences 必须是数组")
    return payload


def import_app_settings(
    db: Session,
    values: dict[str, Any],
    *,
    replace: bool = False,
    preserve_sensitive: bool = False,
) -> int:
    normalized: dict[str, str] = {}
    for raw_key, raw_value in values.items():
        key = str(raw_key or "").strip()
        if not is_exportable_setting(key):
            continue
        if len(key) > 120:
            raise ValueError(f"配置键过长：{key[:60]}")
        value = "" if raw_value is None else str(raw_value)
        if len(value) > 1_000_000:
            raise ValueError(f"配置值过大：{key}")
        normalized[key] = value

    if replace:
        current_keys = [
            row.key
            for row in db.scalars(select(AppSetting))
            if is_exportable_setting(row.key)
            and not (preserve_sensitive and is_sensitive_setting(row.key))
        ]
        if current_keys:
            db.execute(delete(AppSetting).where(AppSetting.key.in_(current_keys)))

    for key, value in normalized.items():
        row = db.get(AppSetting, key)
        if row is None:
            db.add(AppSetting(key=key, value=value))
        else:
            row.value = value
    return len(normalized)


def import_anime_preferences(
    db: Session,
    values: list[Any],
    *,
    replace: bool = False,
) -> int:
    if replace:
        db.execute(delete(AnimePreference))
    imported = 0
    for raw in values:
        if not isinstance(raw, dict):
            continue
        canonical_key = str(raw.get("canonical_key") or "").strip()
        if not canonical_key or len(canonical_key) > 255:
            continue
        row = db.get(AnimePreference, canonical_key)
        if row is None:
            row = AnimePreference(canonical_key=canonical_key)
            db.add(row)
        try:
            bangumi_id = max(0, int(raw.get("bangumi_id") or 0))
        except (TypeError, ValueError):
            bangumi_id = 0
        row.bangumi_id = bangumi_id
        row.title_normalized = str(raw.get("title_normalized") or "")[:255]
        row.hidden = bool(raw.get("hidden", True))
        row.reason = str(raw.get("reason") or "")[:1000]
        imported += 1
    return imported
