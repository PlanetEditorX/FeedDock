from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from urllib.parse import urlparse

from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from .config import settings
from .models import AppSetting, Subscription


PAGE_THEME_COLORS = {"blue", "indigo", "green", "orange", "rose"}
SUBSCRIPTION_SORT_MODES = {"rating", "pinyin", "updated", "created", "weekday"}

_SETTING_KEYS = {
    "page_theme_color",
    "subscription_sort_mode",
    "download_retry_count",
    "download_concurrent_limit",
    "download_seeding_minutes",
    "download_cleanup_completed_enabled",
    "download_cleanup_completed_delay_minutes",
    "rss_enabled",
    "rss_timeout_seconds",
    "rss_auto_skip_existing",
    "rss_auto_disable_complete",
    "trackers_enabled",
    "trackers_update_url",
    "trackers_cached_json",
    "trackers_updated_at",
}


@dataclass(frozen=True, slots=True)
class PagePreferences:
    theme_color: str = "blue"
    subscription_sort: str = "updated"

    def public_dict(self) -> dict[str, str]:
        return {
            "theme_color": self.theme_color,
            "subscription_sort": self.subscription_sort,
        }


@dataclass(frozen=True, slots=True)
class DownloadPolicy:
    retry_count: int = 2
    concurrent_limit: int = 3
    seeding_minutes: int = -1
    cleanup_completed_enabled: bool = False
    cleanup_completed_delay_minutes: int = 1

    def public_dict(self) -> dict[str, int | bool]:
        return {
            "retry_count": self.retry_count,
            "concurrent_limit": self.concurrent_limit,
            "seeding_minutes": self.seeding_minutes,
            "cleanup_completed_enabled": self.cleanup_completed_enabled,
            "cleanup_completed_delay_minutes": self.cleanup_completed_delay_minutes,
        }


@dataclass(frozen=True, slots=True)
class RssPolicy:
    enabled: bool = True
    timeout_seconds: int = 20
    auto_skip_existing: bool = True
    auto_disable_complete: bool = False

    def public_dict(self) -> dict[str, int | bool]:
        return {
            "enabled": self.enabled,
            "timeout_seconds": self.timeout_seconds,
            "auto_skip_existing": self.auto_skip_existing,
            "auto_disable_complete": self.auto_disable_complete,
        }


@dataclass(frozen=True, slots=True)
class TrackerPolicy:
    enabled: bool = True
    update_url: str = "https://cf.trackerslist.com/best.txt"
    trackers: tuple[str, ...] = ()
    updated_at: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.enabled and self.update_url)

    def public_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "update_url": self.update_url,
            "tracker_count": len(self.trackers),
            "updated_at": self.updated_at,
            "configured": self.configured,
        }


@dataclass(frozen=True, slots=True)
class ApplicationPreferences:
    page: PagePreferences
    download: DownloadPolicy
    rss: RssPolicy
    trackers: TrackerPolicy
    source: str = "web"

    def public_dict(self) -> dict[str, object]:
        return {
            "page": self.page.public_dict(),
            "download": self.download.public_dict(),
            "rss": self.rss.public_dict(),
            "trackers": self.trackers.public_dict(),
            "source": self.source,
        }


def _bool(value: object, default: bool) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _integer(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return parsed if minimum <= parsed <= maximum else default


def _valid_http_url(value: str, label: str, *, required: bool = True) -> str:
    cleaned = (value or "").strip().rstrip("/")
    if not cleaned:
        if required:
            raise ValueError(f"{label}不能为空")
        return ""
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{label}必须是有效的 HTTP 或 HTTPS 地址")
    if len(cleaned) > 4000:
        raise ValueError(f"{label}过长")
    return cleaned


def _parse_trackers(raw: object) -> tuple[str, ...]:
    if not raw:
        return ()
    try:
        values = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return ()
    if not isinstance(values, list):
        return ()
    trackers: list[str] = []
    seen: set[str] = set()
    for value in values:
        tracker = str(value or "").strip()
        if not tracker or tracker in seen or len(tracker) > 2000:
            continue
        parsed = urlparse(tracker)
        if parsed.scheme not in {"http", "https", "udp", "ws", "wss"}:
            continue
        seen.add(tracker)
        trackers.append(tracker)
        if len(trackers) >= 500:
            break
    return tuple(trackers)


def load_application_preferences(db: Session) -> ApplicationPreferences:
    fallback = ApplicationPreferences(
        page=PagePreferences(),
        download=DownloadPolicy(),
        rss=RssPolicy(timeout_seconds=settings.request_timeout_seconds),
        trackers=TrackerPolicy(),
        source="default",
    )
    try:
        rows = {
            row.key: row.value
            for row in db.scalars(select(AppSetting).where(AppSetting.key.in_(_SETTING_KEYS)))
        }
    except (OperationalError, ProgrammingError):
        return fallback
    if not rows:
        return fallback

    theme = rows.get("page_theme_color", fallback.page.theme_color).strip().lower()
    sort_mode = rows.get("subscription_sort_mode", fallback.page.subscription_sort).strip().lower()
    page = PagePreferences(
        theme_color=theme if theme in PAGE_THEME_COLORS else fallback.page.theme_color,
        subscription_sort=sort_mode if sort_mode in SUBSCRIPTION_SORT_MODES else fallback.page.subscription_sort,
    )
    download = DownloadPolicy(
        retry_count=_integer(rows.get("download_retry_count"), fallback.download.retry_count, 0, 10),
        concurrent_limit=_integer(rows.get("download_concurrent_limit"), fallback.download.concurrent_limit, 0, 100),
        seeding_minutes=_integer(rows.get("download_seeding_minutes"), fallback.download.seeding_minutes, -1, 525600),
        cleanup_completed_enabled=_bool(
            rows.get("download_cleanup_completed_enabled"),
            fallback.download.cleanup_completed_enabled,
        ),
        cleanup_completed_delay_minutes=_integer(
            rows.get("download_cleanup_completed_delay_minutes"),
            fallback.download.cleanup_completed_delay_minutes,
            1,
            525600,
        ),
    )
    rss = RssPolicy(
        enabled=_bool(rows.get("rss_enabled"), fallback.rss.enabled),
        timeout_seconds=_integer(rows.get("rss_timeout_seconds"), fallback.rss.timeout_seconds, 5, 300),
        auto_skip_existing=_bool(rows.get("rss_auto_skip_existing"), fallback.rss.auto_skip_existing),
        auto_disable_complete=_bool(rows.get("rss_auto_disable_complete"), fallback.rss.auto_disable_complete),
    )
    trackers = TrackerPolicy(
        enabled=_bool(rows.get("trackers_enabled"), fallback.trackers.enabled),
        update_url=rows.get("trackers_update_url", fallback.trackers.update_url).strip() or fallback.trackers.update_url,
        trackers=_parse_trackers(rows.get("trackers_cached_json")),
        updated_at=rows.get("trackers_updated_at", "").strip(),
    )
    return ApplicationPreferences(page=page, download=download, rss=rss, trackers=trackers, source="web")


def _write_values(db: Session, values: dict[str, str]) -> None:
    existing = {
        row.key: row
        for row in db.scalars(select(AppSetting).where(AppSetting.key.in_(values)))
    }
    for key, value in values.items():
        row = existing.get(key)
        if row is None:
            db.add(AppSetting(key=key, value=value))
        else:
            row.value = value


def save_application_preferences(
    db: Session,
    *,
    theme_color: str,
    subscription_sort: str,
    retry_count: int,
    concurrent_limit: int,
    seeding_minutes: int,
    cleanup_completed_enabled: bool,
    cleanup_completed_delay_minutes: int,
    rss_enabled: bool,
    rss_timeout_seconds: int,
    auto_skip_existing: bool,
    auto_disable_complete: bool,
    trackers_enabled: bool,
    trackers_update_url: str,
) -> ApplicationPreferences:
    theme = theme_color.strip().lower()
    if theme not in PAGE_THEME_COLORS:
        raise ValueError("主题色无效")
    sort_mode = subscription_sort.strip().lower()
    if sort_mode not in SUBSCRIPTION_SORT_MODES:
        raise ValueError("订阅排序方式无效")
    if not 0 <= retry_count <= 10:
        raise ValueError("失败重试次数必须在 0 到 10 之间")
    if not 0 <= concurrent_limit <= 100:
        raise ValueError("同时下载限制必须在 0 到 100 之间，0 表示不限")
    if not -1 <= seeding_minutes <= 525600:
        raise ValueError("做种时长必须是 -1 或 0 到 525600 分钟")
    if not 1 <= cleanup_completed_delay_minutes <= 525600:
        raise ValueError("完成任务清理等待时间必须在 1 到 525600 分钟之间")
    if not 5 <= rss_timeout_seconds <= 300:
        raise ValueError("RSS 超时必须在 5 到 300 秒之间")
    tracker_url = _valid_http_url(trackers_update_url, "Trackers 更新地址")

    if auto_skip_existing:
        disabled_rename = db.scalar(
            select(Subscription.id)
            .where(Subscription.enabled.is_(True), Subscription.rename_enabled.is_(False))
            .limit(1)
        )
        if disabled_rename is not None:
            raise ValueError("启用“文件已下载自动跳过”前，请先为全部启用订阅开启自动重命名")

    _write_values(db, {
        "page_theme_color": theme,
        "subscription_sort_mode": sort_mode,
        "download_retry_count": str(retry_count),
        "download_concurrent_limit": str(concurrent_limit),
        "download_seeding_minutes": str(seeding_minutes),
        "download_cleanup_completed_enabled": "1" if cleanup_completed_enabled else "0",
        "download_cleanup_completed_delay_minutes": str(cleanup_completed_delay_minutes),
        "rss_enabled": "1" if rss_enabled else "0",
        "rss_timeout_seconds": str(rss_timeout_seconds),
        "rss_auto_skip_existing": "1" if auto_skip_existing else "0",
        "rss_auto_disable_complete": "1" if auto_disable_complete else "0",
        "trackers_enabled": "1" if trackers_enabled else "0",
        "trackers_update_url": tracker_url,
    })
    db.commit()
    return load_application_preferences(db)


def reset_application_preferences(db: Session) -> ApplicationPreferences:
    db.execute(delete(AppSetting).where(AppSetting.key.in_(_SETTING_KEYS)))
    db.commit()
    return load_application_preferences(db)


def normalize_tracker_text(content: str) -> tuple[str, ...]:
    trackers: list[str] = []
    seen: set[str] = set()
    for raw_line in (content or "").replace("\r", "\n").split("\n"):
        tracker = raw_line.strip()
        if not tracker or tracker.startswith("#") or tracker in seen:
            continue
        parsed = urlparse(tracker)
        if parsed.scheme not in {"http", "https", "udp", "ws", "wss"}:
            continue
        if len(tracker) > 2000:
            continue
        seen.add(tracker)
        trackers.append(tracker)
        if len(trackers) >= 500:
            break
    return tuple(trackers)


def save_tracker_cache(db: Session, trackers: tuple[str, ...], *, updated_at: datetime | None = None) -> TrackerPolicy:
    timestamp = (updated_at or datetime.now(timezone.utc)).isoformat()
    _write_values(db, {
        "trackers_cached_json": json.dumps(list(trackers), ensure_ascii=False, separators=(",", ":")),
        "trackers_updated_at": timestamp,
    })
    db.commit()
    return load_application_preferences(db).trackers
