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
    "source_type": "VARCHAR(32) NOT NULL DEFAULT ''",
    "source_anime_id": "VARCHAR(120) NOT NULL DEFAULT ''",
    "canonical_key": "VARCHAR(255) NOT NULL DEFAULT ''",
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
    "total_episodes_checked_at": "DATETIME NULL",
    "naming_mode": "VARCHAR(20) NOT NULL DEFAULT 'auto'",
    "media_type": "VARCHAR(20) NOT NULL DEFAULT 'tv'",
    "manual_title": "TEXT NOT NULL DEFAULT ''",
    "tmdb_id": "INTEGER NOT NULL DEFAULT 0",
    "bangumi_id": "INTEGER NOT NULL DEFAULT 0",
    "anilist_id": "INTEGER NOT NULL DEFAULT 0",
    "metadata_year": "INTEGER NOT NULL DEFAULT 0",
    "metadata_rating": "FLOAT NOT NULL DEFAULT 0",
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
    "scrape_enabled": "BOOLEAN NOT NULL DEFAULT 0",
    "scrape_mode": "VARCHAR(20) NOT NULL DEFAULT 'off'",
    "custom_download_path": "TEXT NOT NULL DEFAULT ''",
    "missing_detection": "BOOLEAN NOT NULL DEFAULT 0",
    "only_latest": "BOOLEAN NOT NULL DEFAULT 0",
    "auto_disable_when_complete": "BOOLEAN NOT NULL DEFAULT 0",
    "stale_days": "INTEGER NOT NULL DEFAULT 0",
    "last_new_item_at": "DATETIME NULL",
    "last_stale_notified_at": "DATETIME NULL",
    "completion_notified_at": "DATETIME NULL",
    "last_missing_signature": "TEXT NOT NULL DEFAULT ''",
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
    "trackers_status": "VARCHAR(32) NOT NULL DEFAULT ''",
    "trackers_message": "TEXT NOT NULL DEFAULT ''",
    "trackers_applied_at": "DATETIME NULL",
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

    # Historical migration from the release that removed the original scraper.
    # Keep the marker so older databases upgrade deterministically; FeedDock
    # 1.17.5 introduces a new confined NFO/artwork writer below.
    marker = "migration:1.11.0:scrape-disabled"
    with engine.begin() as connection:
        existing = connection.execute(
            text("SELECT value FROM app_settings WHERE key = :key"), {"key": marker}
        ).scalar_one_or_none()
        if existing is None:
            connection.execute(text("UPDATE subscriptions SET scrape_enabled = 0, scrape_mode = 'off'"))
            connection.execute(
                text(
                    "UPDATE feed_items SET scrape_status = 'skipped', scrape_message = 'FeedDock 已移除刮削功能' "
                    "WHERE scrape_status IN ('', 'pending', 'retry', 'error', 'waiting_completion')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO app_settings (key, value, updated_at) "
                    "VALUES (:key, '1', CURRENT_TIMESTAMP)"
                ),
                {"key": marker},
            )

    # Upgrade the previous built-in directory template to media_folder. The
    # latter includes [tmdbid=...] after metadata confirmation, while custom
    # user templates are intentionally preserved.
    marker = "migration:1.11.1:media-folder-paths"
    with engine.begin() as connection:
        existing = connection.execute(
            text("SELECT value FROM app_settings WHERE key = :key"), {"key": marker}
        ).scalar_one_or_none()
        if existing is None:
            connection.execute(
                text(
                    "UPDATE subscriptions SET save_path_template = :new_template "
                    "WHERE save_path_template IN (:legacy_template, :legacy_padded_template)"
                ),
                {
                    "new_template": "{base}/{media_folder}/Season {season:02}",
                    "legacy_template": "{base}/{subscription}/Season {season}",
                    "legacy_padded_template": "{base}/{subscription}/Season {season:02}",
                },
            )
            connection.execute(
                text(
                    "INSERT INTO app_settings (key, value, updated_at) "
                    "VALUES (:key, '1', CURRENT_TIMESTAMP)"
                ),
                {"key": marker},
            )

    # Releases through 1.17.4 used the word “scrape” for database-only metadata
    # synchronization. Mark completed downloads once so the new local scraper
    # can backfill NFO and artwork after upgrade.
    marker = "migration:1.17.5:local-scrape-backfill"
    with engine.begin() as connection:
        existing = connection.execute(
            text("SELECT value FROM app_settings WHERE key = :key"), {"key": marker}
        ).scalar_one_or_none()
        if existing is None:
            connection.execute(
                text(
                    "UPDATE feed_items SET scrape_status = 'pending', "
                    "scrape_message = '等待写入 NFO 与图片' "
                    "WHERE completed_at IS NOT NULL"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO app_settings (key, value, updated_at) "
                    "VALUES (:key, '1', CURRENT_TIMESTAMP)"
                ),
                {"key": marker},
            )


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
