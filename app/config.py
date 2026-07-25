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
    dmhy_base_url: str


def load_settings() -> Settings:
    data_dir = Path(os.getenv("DATA_DIR", "/data")).expanduser().resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "feeddock.db"

    return Settings(
        app_name=os.getenv("APP_NAME", "FeedDock"),
        app_version=os.getenv("APP_VERSION", "1.5.0"),
        data_dir=data_dir,
        database_url=os.getenv("DATABASE_URL", f"sqlite:///{db_path}"),
        admin_user=os.getenv("ADMIN_USER", "admin").strip() or "admin",
        admin_password=os.getenv("ADMIN_PASSWORD", "change-me-now"),
        session_days=_as_int("SESSION_DAYS", 7),
        cookie_secure=_as_bool("COOKIE_SECURE", False),
        poll_interval_minutes=_as_int("POLL_INTERVAL_MINUTES", 10),
        request_timeout_seconds=_as_int("REQUEST_TIMEOUT_SECONDS", 20),
        rss_user_agent=os.getenv(
            "RSS_USER_AGENT",
            "FeedDock/1.5 (+self-hosted RSS automation)",
        ),
        qbit_url=os.getenv("QBIT_URL", "").strip().rstrip("/"),
        qbit_username=os.getenv("QBIT_USERNAME", "admin").strip(),
        qbit_password=os.getenv("QBIT_PASSWORD", ""),
        qbit_category=os.getenv("QBIT_CATEGORY", "rss").strip(),
        download_path=os.getenv("DOWNLOAD_PATH", "/downloads/rss").strip(),
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
        dmhy_base_url=os.getenv("DMHY_BASE_URL", "https://share.dmhy.org").strip().rstrip("/"),
    )


settings = load_settings()
