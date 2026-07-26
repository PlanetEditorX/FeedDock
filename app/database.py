from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


_SUBSCRIPTION_COLUMNS: dict[str, str] = {
    "reference_title": "TEXT NOT NULL DEFAULT ''",
    "tmdb_title": "TEXT NOT NULL DEFAULT ''",
    "bgm_url": "TEXT NOT NULL DEFAULT ''",
    "air_date": "VARCHAR(10) NOT NULL DEFAULT ''",
    "season": "INTEGER NOT NULL DEFAULT 1",
    "season_mode": "VARCHAR(20) NOT NULL DEFAULT 'title'",
    "primary_rss_name": "VARCHAR(200) NOT NULL DEFAULT ''",
    "backup_rss_name": "VARCHAR(200) NOT NULL DEFAULT ''",
    "backup_rss_url": "TEXT NOT NULL DEFAULT ''",
    "episode_group": "INTEGER NOT NULL DEFAULT 0",
    "episode_offset": "INTEGER NOT NULL DEFAULT 0",
    "total_episodes": "INTEGER NOT NULL DEFAULT 0",
    "total_episodes_locked": "BOOLEAN NOT NULL DEFAULT 0",
    "total_episodes_source": "VARCHAR(32) NOT NULL DEFAULT ''",
    "naming_mode": "VARCHAR(20) NOT NULL DEFAULT 'auto'",
    "media_type": "VARCHAR(20) NOT NULL DEFAULT 'tv'",
    "manual_title": "TEXT NOT NULL DEFAULT ''",
    "tmdb_id": "INTEGER NOT NULL DEFAULT 0",
    "bangumi_id": "INTEGER NOT NULL DEFAULT 0",
    "anilist_id": "INTEGER NOT NULL DEFAULT 0",
    "metadata_year": "INTEGER NOT NULL DEFAULT 0",
    "metadata_source": "VARCHAR(32) NOT NULL DEFAULT ''",
    "metadata_overview": "TEXT NOT NULL DEFAULT ''",
    "poster_url": "TEXT NOT NULL DEFAULT ''",
    "backdrop_url": "TEXT NOT NULL DEFAULT ''",
    "metadata_last_synced_at": "DATETIME NULL",
    "auto_metadata": "BOOLEAN NOT NULL DEFAULT 0",
    "metadata_confirmed": "BOOLEAN NOT NULL DEFAULT 0",
    "metadata_review_skipped": "BOOLEAN NOT NULL DEFAULT 0",
    # Existing installs remain opt-in. New subscriptions receive the Pydantic
    # default from the request body.
    "rename_enabled": "BOOLEAN NOT NULL DEFAULT 0",
    "file_name_template": "TEXT NOT NULL DEFAULT '{title} - S{season:02}E{episode:02}'",
    # Legacy columns retained for upgrade compatibility; runtime no longer uses them.
    "scrape_enabled": "BOOLEAN NOT NULL DEFAULT 0",
    "scrape_mode": "VARCHAR(20) NOT NULL DEFAULT 'off'",
    "custom_download_path": "TEXT NOT NULL DEFAULT ''",
    "missing_detection": "BOOLEAN NOT NULL DEFAULT 0",
    "only_latest": "BOOLEAN NOT NULL DEFAULT 0",
}

_FEED_ITEM_COLUMNS: dict[str, str] = {
    "desired_name": "TEXT NOT NULL DEFAULT ''",
    "qbit_tag": "VARCHAR(120) NOT NULL DEFAULT ''",
    "torrent_hash": "VARCHAR(80) NOT NULL DEFAULT ''",
    "rename_status": "VARCHAR(32) NOT NULL DEFAULT ''",
    "rename_message": "TEXT NOT NULL DEFAULT ''",
    "download_progress": "INTEGER NOT NULL DEFAULT 0",
    "completed_at": "DATETIME NULL",
    "scrape_status": "VARCHAR(32) NOT NULL DEFAULT ''",
    "scrape_message": "TEXT NOT NULL DEFAULT ''",
    "scraped_at": "DATETIME NULL",
    "hidden": "BOOLEAN NOT NULL DEFAULT 0",
}


def _add_missing_columns(table: str, columns: dict[str, str]) -> None:
    inspector = inspect(engine)
    if table not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns(table)}
    missing = [(name, ddl) for name, ddl in columns.items() if name not in existing]
    if not missing:
        return
    with engine.begin() as connection:
        for name, ddl in missing:
            connection.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {ddl}'))


def ensure_schema() -> None:
    """Apply dependency-free additive migrations for existing SQLite installs."""

    if not settings.database_url.startswith("sqlite"):
        return
    _add_missing_columns("subscriptions", _SUBSCRIPTION_COLUMNS)
    _add_missing_columns("feed_items", _FEED_ITEM_COLUMNS)

    # Built-in scraping was removed in v1.10.1. Keep the legacy columns so old
    # SQLite files remain readable, but disable their values and erase stored
    # integration credentials that are no longer used.
    with engine.begin() as connection:
        connection.execute(text("UPDATE subscriptions SET scrape_enabled = 0, scrape_mode = 'off'"))
        connection.execute(text("UPDATE feed_items SET scrape_status = '', scrape_message = '', scraped_at = NULL"))
        connection.execute(text(
            "DELETE FROM app_settings WHERE key IN ("
            "'media_local_root','emby_url','emby_api_key',"
            "'tmm_url','tmm_api_key','tmm_enabled','automation_scrape_enabled'"
            ")"
        ))



def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
