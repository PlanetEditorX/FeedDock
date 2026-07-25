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
    "primary_rss_name": "VARCHAR(200) NOT NULL DEFAULT ''",
    "backup_rss_name": "VARCHAR(200) NOT NULL DEFAULT ''",
    "backup_rss_url": "TEXT NOT NULL DEFAULT ''",
    "episode_group": "INTEGER NOT NULL DEFAULT 0",
    "episode_offset": "INTEGER NOT NULL DEFAULT 0",
    "total_episodes": "INTEGER NOT NULL DEFAULT 0",
    "custom_download_path": "TEXT NOT NULL DEFAULT ''",
    "missing_detection": "BOOLEAN NOT NULL DEFAULT 0",
    "only_latest": "BOOLEAN NOT NULL DEFAULT 0",
}


def ensure_schema() -> None:
    """Apply small additive migrations for existing self-hosted SQLite installs.

    FeedDock intentionally keeps migrations dependency-free. New subscription
    options are nullable/defaulted additions, so ALTER TABLE is sufficient and
    existing subscriptions remain usable.
    """

    if not settings.database_url.startswith("sqlite"):
        return
    inspector = inspect(engine)
    if "subscriptions" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("subscriptions")}
    missing = [(name, ddl) for name, ddl in _SUBSCRIPTION_COLUMNS.items() if name not in existing]
    if not missing:
        return
    with engine.begin() as connection:
        for name, ddl in missing:
            connection.execute(text(f'ALTER TABLE subscriptions ADD COLUMN "{name}" {ddl}'))


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
