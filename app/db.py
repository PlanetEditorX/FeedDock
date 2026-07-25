from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import settings


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(path: Path | None = None) -> sqlite3.Connection:
    db_path = path or settings.database_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def transaction(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(path: Path | None = None) -> None:
    with transaction(path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                must_change_password INTEGER NOT NULL DEFAULT 1,
                session_version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                session_version INTEGER NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                reference_title TEXT NOT NULL DEFAULT '',
                tmdb_title TEXT NOT NULL DEFAULT '',
                bgm_url TEXT NOT NULL DEFAULT '',
                release_date TEXT NOT NULL DEFAULT '',
                season INTEGER NOT NULL DEFAULT 1,
                primary_rss_name TEXT NOT NULL DEFAULT '',
                primary_rss_url TEXT NOT NULL,
                backup_rss_name TEXT NOT NULL DEFAULT '',
                backup_rss_url TEXT NOT NULL DEFAULT '',
                include_rules TEXT NOT NULL DEFAULT '',
                exclude_rules TEXT NOT NULL DEFAULT '',
                global_exclude_rules TEXT NOT NULL DEFAULT '',
                episode_regex TEXT NOT NULL DEFAULT '',
                episode_group INTEGER NOT NULL DEFAULT 0,
                episode_offset REAL NOT NULL DEFAULT 0,
                total_episodes INTEGER NOT NULL DEFAULT 0,
                download_path TEXT NOT NULL DEFAULT '',
                missing_check INTEGER NOT NULL DEFAULT 0,
                latest_only INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER NOT NULL DEFAULT 1,
                last_checked_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS rss_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subscription_id INTEGER NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
                fingerprint TEXT NOT NULL,
                title TEXT NOT NULL,
                link TEXT NOT NULL DEFAULT '',
                download_url TEXT NOT NULL DEFAULT '',
                published_at TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'seen',
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE(subscription_id, fingerprint)
            );

            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                context TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS mikan_cache (
                cache_key TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                source_url TEXT NOT NULL DEFAULT '',
                schema_version INTEGER NOT NULL DEFAULT 5
            );

            CREATE TABLE IF NOT EXISTS mikan_hidden (
                year INTEGER NOT NULL,
                season TEXT NOT NULL,
                weekday INTEGER NOT NULL,
                bangumi_id INTEGER NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (year, season, weekday, bangumi_id)
            );
            CREATE INDEX IF NOT EXISTS idx_mikan_hidden_scope
                ON mikan_hidden(year, season, weekday);
            """
        )


def get_setting(key: str, default: Any = None, *, path: Path | None = None) -> Any:
    with connect(path) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    try:
        return json.loads(row["value"])
    except json.JSONDecodeError:
        return row["value"]


def set_setting(key: str, value: Any, *, path: Path | None = None) -> None:
    encoded = json.dumps(value, ensure_ascii=False)
    with transaction(path) as conn:
        conn.execute(
            """
            INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (key, encoded, utcnow_iso()),
        )


def add_log(level: str, message: str, context: dict[str, Any] | None = None) -> None:
    with transaction() as conn:
        conn.execute(
            "INSERT INTO logs(level, message, context, created_at) VALUES (?, ?, ?, ?)",
            (level, message, json.dumps(context or {}, ensure_ascii=False), utcnow_iso()),
        )
