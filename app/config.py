from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _as_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        return max(minimum, int(raw))
    except ValueError:
        return default


def _as_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _optional_path(name: str) -> Path | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str
    app_version: str
    data_dir: Path
    database_url: str
    admin_user: str
    admin_password: str
    session_days: int
    cookie_secure: bool
    poll_interval_minutes: int
    request_timeout_seconds: int
    rss_user_agent: str
    qbit_url: str
    qbit_username: str
    qbit_password: str
    qbit_category: str
    download_path: str
    timezone: str
    update_repository: str
    update_api_url: str
    watchtower_url: str
    watchtower_token: str
    deployed_image: str
    update_github_token: str
    mikan_base_url: str
    mikan_fallback_urls: tuple[str, ...]
    mikan_cache_hours: int
    mikan_image_cache_days: int
    mikan_thumbnail_width: int
    mikan_thumbnail_height: int
    metadata_language: str
    tmdb_api_base: str
    tmdb_image_base: str
    tmdb_read_access_token: str
    bangumi_api_base: str
    bangumi_access_token: str
    anilist_api_url: str
    metadata_auto_sync_hours: int
    media_local_root: Path | None
    emby_url: str
    emby_api_key: str
    tmm_url: str
    tmm_api_key: str
    automation_time: str
    automation_timezone: str
    outbound_proxy_url: str
    outbound_no_proxy: str
    log_level: str
    allow_system_actions: bool


def load_settings() -> Settings:
    data_dir = Path(os.getenv("DATA_DIR", "/data")).expanduser().resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "feeddock.db"

    return Settings(
        app_name=os.getenv("APP_NAME", "FeedDock"),
        app_version=os.getenv("APP_VERSION", "1.17.2"),
        data_dir=data_dir,
        database_url=os.getenv("DATABASE_URL", f"sqlite:///{db_path}"),
        admin_user=os.getenv("ADMIN_USER", "admin").strip() or "admin",
        admin_password=os.getenv("ADMIN_PASSWORD", "change-me-now"),
        session_days=_as_int("SESSION_DAYS", 7),
        cookie_secure=_as_bool("COOKIE_SECURE", False),
        poll_interval_minutes=_as_int("POLL_INTERVAL_MINUTES", 30, minimum=5),
        request_timeout_seconds=_as_int("REQUEST_TIMEOUT_SECONDS", 20),
        rss_user_agent=os.getenv(
            "RSS_USER_AGENT",
            "FeedDock/1.17.2 (+self-hosted RSS automation)",
        ),
        qbit_url=os.getenv("QBIT_URL", "").strip().rstrip("/"),
        qbit_username=os.getenv("QBIT_USERNAME", "admin").strip(),
        qbit_password=os.getenv("QBIT_PASSWORD", ""),
        qbit_category=os.getenv("QBIT_CATEGORY", "rss").strip(),
        download_path=os.getenv("DOWNLOAD_PATH", "/media").strip(),
        timezone=os.getenv("TZ", "Asia/Shanghai"),
        update_repository=os.getenv("UPDATE_REPOSITORY", "planeteditorx/feeddock").strip().strip("/"),
        update_api_url=os.getenv("UPDATE_API_URL", "https://api.github.com").strip().rstrip("/"),
        watchtower_url=os.getenv("WATCHTOWER_URL", "").strip().rstrip("/"),
        watchtower_token=os.getenv("WATCHTOWER_TOKEN", ""),
        deployed_image=os.getenv("FEEDDOCK_IMAGE", "ghcr.io/planeteditorx/feeddock:latest").strip(),
        update_github_token=os.getenv("UPDATE_GITHUB_TOKEN", "").strip(),
        mikan_base_url=os.getenv("MIKAN_BASE_URL", "https://mikanime.tv").strip().rstrip("/"),
        mikan_fallback_urls=tuple(
            value.strip().rstrip("/")
            for value in os.getenv(
                "MIKAN_FALLBACK_URLS",
                "https://mikanani.me,https://mikanani.kas.pub",
            ).split(",")
            if value.strip()
        ),
        mikan_cache_hours=_as_int("MIKAN_CACHE_HOURS", 6),
        mikan_image_cache_days=_as_int("MIKAN_IMAGE_CACHE_DAYS", 30),
        mikan_thumbnail_width=_as_int("MIKAN_THUMBNAIL_WIDTH", 240, minimum=80),
        mikan_thumbnail_height=_as_int("MIKAN_THUMBNAIL_HEIGHT", 320, minimum=80),
        metadata_language=os.getenv("METADATA_LANGUAGE", "zh-CN").strip() or "zh-CN",
        tmdb_api_base=os.getenv("TMDB_API_BASE", "https://api.themoviedb.org").strip().rstrip("/"),
        tmdb_image_base=os.getenv("TMDB_IMAGE_BASE", "https://image.tmdb.org").strip().rstrip("/"),
        tmdb_read_access_token=os.getenv("TMDB_READ_ACCESS_TOKEN", "").strip(),
        bangumi_api_base=os.getenv("BANGUMI_API_BASE", "https://api.bgm.tv").strip().rstrip("/"),
        bangumi_access_token=os.getenv("BANGUMI_ACCESS_TOKEN", "").strip(),
        anilist_api_url=os.getenv("ANILIST_API_URL", "https://graphql.anilist.co").strip().rstrip("/"),
        metadata_auto_sync_hours=_as_int("METADATA_AUTO_SYNC_HOURS", 24),
        media_local_root=_optional_path("MEDIA_LOCAL_ROOT"),
        emby_url=os.getenv("EMBY_URL", "").strip().rstrip("/"),
        emby_api_key=os.getenv("EMBY_API_KEY", "").strip(),
        tmm_url=os.getenv("TMM_URL", "").strip().rstrip("/"),
        tmm_api_key=os.getenv("TMM_API_KEY", "").strip(),
        automation_time=os.getenv("AUTOMATION_TIME", "02:00").strip() or "02:00",
        automation_timezone=os.getenv("AUTOMATION_TIMEZONE", os.getenv("TZ", "Asia/Shanghai")).strip() or "Asia/Shanghai",
        outbound_proxy_url=os.getenv("OUTBOUND_PROXY_URL", "").strip(),
        outbound_no_proxy=os.getenv("OUTBOUND_NO_PROXY", "localhost,127.0.0.1,host.docker.internal").strip(),
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO",
        allow_system_actions=_as_bool("FEEDDOCK_ALLOW_SYSTEM_ACTIONS", False),
    )


settings = load_settings()
