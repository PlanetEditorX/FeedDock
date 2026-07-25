from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int, minimum: int = 1) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(minimum, value)


@dataclass(frozen=True)
class Settings:
    app_name: str = "FeedDock"
    version: str = os.getenv("APP_VERSION", "1.8.0")
    data_dir: Path = Path(os.getenv("DATA_DIR", "/data"))
    database_path: Path = Path(os.getenv("DATABASE_PATH", "/data/feeddock.db"))
    admin_user: str = os.getenv("ADMIN_USER", "admin")
    admin_password: str = os.getenv("ADMIN_PASSWORD", "password")
    session_days: int = _int("SESSION_DAYS", 7)
    cookie_secure: bool = _bool("COOKIE_SECURE", False)
    poll_interval_minutes: int = _int("POLL_INTERVAL_MINUTES", 10)
    request_timeout_seconds: int = _int("REQUEST_TIMEOUT_SECONDS", 20)
    mikan_cache_hours: int = _int("MIKAN_CACHE_HOURS", 6)
    mikan_base_url: str = os.getenv("MIKAN_BASE_URL", "https://mikanani.me").rstrip("/")
    mikan_fallback_urls: tuple[str, ...] = tuple(
        url.strip().rstrip("/")
        for url in os.getenv(
            "MIKAN_FALLBACK_URLS",
            "https://mikanime.tv,https://mikanani.kas.pub",
        ).split(",")
        if url.strip()
    )
    update_repository: str = os.getenv("UPDATE_REPOSITORY", "planeteditorx/feeddock")
    update_api_url: str = os.getenv("UPDATE_API_URL", "https://api.github.com").rstrip("/")
    update_github_token: str = os.getenv("UPDATE_GITHUB_TOKEN", "")
    watchtower_url: str = os.getenv("WATCHTOWER_URL", "").rstrip("/")
    watchtower_token: str = os.getenv("WATCHTOWER_TOKEN", "")
    testing: bool = _bool("TESTING", False)

    @property
    def image_cache_dir(self) -> Path:
        return self.data_dir / "mikan-image-cache"

    @property
    def allowed_mikan_hosts(self) -> set[str]:
        from urllib.parse import urlparse

        urls = (self.mikan_base_url, *self.mikan_fallback_urls)
        return {urlparse(url).hostname or "" for url in urls if url}


settings = Settings()
