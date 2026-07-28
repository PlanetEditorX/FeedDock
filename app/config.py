"""Application configuration loaded from environment variables."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from .build_info import load_build_info


def _text(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _boolean(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _integer(name: str, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        value = int(os.getenv(name, str(default)).strip())
    except (AttributeError, ValueError):
        return default
    if minimum is not None and value < minimum:
        return default
    if maximum is not None and value > maximum:
        return default
    return value


def _optional_path(name: str, default: str = "") -> Path | None:
    value = os.getenv(name, default).strip()
    return Path(value).expanduser() if value else None


def _csv(name: str, default: str = "") -> tuple[str, ...]:
    values: list[str] = []
    seen: set[str] = set()
    for raw in os.getenv(name, default).split(","):
        value = raw.strip().rstrip("/")
        if value and value not in seen:
            seen.add(value)
            values.append(value)
    return tuple(values)


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str
    app_version: str
    app_revision: str
    app_created_at: str
    app_build_source: str

    data_dir: Path
    database_url: str
    admin_user: str
    admin_password: str
    session_days: int
    cookie_secure: bool
    allow_system_actions: bool
    timezone: str

    poll_interval_minutes: int
    request_timeout_seconds: int
    log_level: str
    rss_user_agent: str

    mikan_base_url: str
    mikan_fallback_urls: tuple[str, ...]
    mikan_cache_hours: int
    mikan_image_cache_days: int
    mikan_thumbnail_width: int
    mikan_thumbnail_height: int

    qbit_url: str
    qbit_username: str
    qbit_password: str
    qbit_category: str
    download_path: str

    metadata_language: str
    metadata_auto_sync_hours: int
    tmdb_api_base: str
    tmdb_image_base: str
    tmdb_read_access_token: str
    bangumi_api_base: str
    bangumi_access_token: str
    anilist_api_url: str
    media_local_root: Path | None
    emby_url: str
    emby_api_key: str
    tmm_url: str
    tmm_api_key: str

    automation_time: str
    automation_timezone: str
    outbound_proxy_url: str
    outbound_no_proxy: str

    update_check_cache_hours: int
    update_registry_username: str
    update_registry_token: str
    deployed_image: str
    watchtower_url: str
    watchtower_token: str


def load_settings():
    build = load_build_info()
    data_dir = _optional_path("DATA_DIR", "/data") or Path("/data")
    data_dir.mkdir(parents=True, exist_ok=True)
    database_url = _text("DATABASE_URL") or f"sqlite:///{data_dir / 'feeddock.db'}"

    return Settings(
        app_name=_text("APP_NAME", "FeedDock") or "FeedDock",
        app_version=build.version,
        app_revision=build.revision,
        app_created_at=build.created_at,
        app_build_source=build.source,
        data_dir=data_dir,
        database_url=database_url,
        admin_user=_text("ADMIN_USER", "admin") or "admin",
        admin_password=os.getenv("ADMIN_PASSWORD", "change-this-to-a-strong-password"),
        session_days=_integer("SESSION_DAYS", 7, minimum=1, maximum=3650),
        cookie_secure=_boolean("COOKIE_SECURE", False),
        allow_system_actions=_boolean("FEEDDOCK_ALLOW_SYSTEM_ACTIONS", False),
        timezone=_text("TZ", "Asia/Shanghai") or "Asia/Shanghai",
        poll_interval_minutes=_integer("POLL_INTERVAL_MINUTES", 30, minimum=1, maximum=10080),
        request_timeout_seconds=_integer("REQUEST_TIMEOUT_SECONDS", 20, minimum=1, maximum=600),
        log_level=(_text("LOG_LEVEL", "INFO") or "INFO").upper(),
        rss_user_agent=_text("RSS_USER_AGENT", "FeedDock (+self-hosted RSS automation)")
        or "FeedDock (+self-hosted RSS automation)",
        mikan_base_url=(_text("MIKAN_BASE_URL", "https://mikanime.tv") or "https://mikanime.tv").rstrip("/"),
        mikan_fallback_urls=_csv(
            "MIKAN_FALLBACK_URLS",
            "https://mikanani.me,https://mikanani.kas.pub",
        ),
        mikan_cache_hours=_integer("MIKAN_CACHE_HOURS", 6, minimum=1, maximum=8760),
        mikan_image_cache_days=_integer("MIKAN_IMAGE_CACHE_DAYS", 30, minimum=1, maximum=3650),
        mikan_thumbnail_width=_integer("MIKAN_THUMBNAIL_WIDTH", 240, minimum=32, maximum=4096),
        mikan_thumbnail_height=_integer("MIKAN_THUMBNAIL_HEIGHT", 320, minimum=32, maximum=4096),
        qbit_url=_text("QBIT_URL").rstrip("/"),
        qbit_username=_text("QBIT_USERNAME"),
        qbit_password=os.getenv("QBIT_PASSWORD", ""),
        qbit_category=_text("QBIT_CATEGORY", "rss") or "rss",
        download_path=_text("DOWNLOAD_PATH", "/media") or "/media",
        metadata_language=_text("METADATA_LANGUAGE", "zh-CN") or "zh-CN",
        metadata_auto_sync_hours=_integer("METADATA_AUTO_SYNC_HOURS", 24, minimum=1, maximum=8760),
        tmdb_api_base=(_text("TMDB_API_BASE", "https://api.themoviedb.org") or "https://api.themoviedb.org").rstrip("/"),
        tmdb_image_base=(_text("TMDB_IMAGE_BASE", "https://image.tmdb.org") or "https://image.tmdb.org").rstrip("/"),
        tmdb_read_access_token=os.getenv("TMDB_READ_ACCESS_TOKEN", "").strip(),
        bangumi_api_base=(_text("BANGUMI_API_BASE", "https://api.bgm.tv") or "https://api.bgm.tv").rstrip("/"),
        bangumi_access_token=os.getenv("BANGUMI_ACCESS_TOKEN", "").strip(),
        anilist_api_url=_text("ANILIST_API_URL", "https://graphql.anilist.co") or "https://graphql.anilist.co",
        media_local_root=_optional_path("MEDIA_LOCAL_ROOT", "/media"),
        emby_url=_text("EMBY_URL").rstrip("/"),
        emby_api_key=os.getenv("EMBY_API_KEY", "").strip(),
        tmm_url=_text("TMM_URL").rstrip("/"),
        tmm_api_key=os.getenv("TMM_API_KEY", "").strip(),
        automation_time=_text("AUTOMATION_TIME", "02:00") or "02:00",
        automation_timezone=_text("AUTOMATION_TIMEZONE", "Asia/Shanghai") or "Asia/Shanghai",
        outbound_proxy_url=_text("OUTBOUND_PROXY_URL"),
        outbound_no_proxy=_text(
            "OUTBOUND_NO_PROXY",
            "localhost,127.0.0.1,host.docker.internal",
        ),
        update_check_cache_hours=_integer("UPDATE_CHECK_CACHE_HOURS", 6, minimum=1, maximum=8760),
        update_registry_username=_text("UPDATE_REGISTRY_USERNAME"),
        update_registry_token=os.getenv("UPDATE_REGISTRY_TOKEN", "").strip(),
        deployed_image=_text("FEEDDOCK_IMAGE", "ghcr.io/planeteditorx/feeddock:latest")
        or "ghcr.io/planeteditorx/feeddock:latest",
        watchtower_url=_text("WATCHTOWER_URL", "http://watchtower:8080").rstrip("/"),
        watchtower_token=os.getenv("WATCHTOWER_TOKEN", "").strip(),
    )


settings = load_settings()
