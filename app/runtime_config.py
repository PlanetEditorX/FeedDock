from __future__ import annotations

from dataclasses import dataclass
import json
from urllib.parse import urlparse

from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from .config import settings
from .database import SessionLocal
from .models import AppSetting


QBIT_SETTING_KEYS = {
    "qbit_url",
    "qbit_username",
    "qbit_password",
    "qbit_category",
    "download_path",
}


@dataclass(frozen=True, slots=True)
class QBittorrentConfig:
    url: str
    username: str
    password: str
    category: str
    download_path: str
    source: str

    @property
    def configured(self) -> bool:
        return bool(self.url and self.username and self.password)

    def public_dict(self) -> dict[str, str | bool]:
        return {
            "qbit_url": self.url,
            "qbit_username": self.username,
            "qbit_password_configured": bool(self.password),
            "qbit_category": self.category,
            "download_path": self.download_path,
            "source": self.source,
            "configured": self.configured,
        }


def _environment_config() -> QBittorrentConfig:
    return QBittorrentConfig(
        url=settings.qbit_url,
        username=settings.qbit_username,
        password=settings.qbit_password,
        category=settings.qbit_category,
        download_path=settings.download_path,
        source="compose",
    )


def _load_with_session(db: Session) -> QBittorrentConfig:
    fallback = _environment_config()
    try:
        rows = {
            row.key: row.value
            for row in db.scalars(select(AppSetting).where(AppSetting.key.in_(QBIT_SETTING_KEYS)))
        }
    except (OperationalError, ProgrammingError):
        # Standalone helpers and pre-migration startup checks may run before
        # Base.metadata.create_all() has created app_settings.
        return fallback
    if not rows:
        return fallback
    return QBittorrentConfig(
        url=rows.get("qbit_url", fallback.url).strip().rstrip("/"),
        username=rows.get("qbit_username", fallback.username).strip(),
        password=rows.get("qbit_password", fallback.password),
        category=rows.get("qbit_category", fallback.category).strip(),
        download_path=rows.get("download_path", fallback.download_path).strip(),
        source="web",
    )


def load_qbittorrent_config(db: Session | None = None) -> QBittorrentConfig:
    if db is not None:
        return _load_with_session(db)
    with SessionLocal() as session:
        return _load_with_session(session)


def validate_qbittorrent_values(
    *,
    qbit_url: str,
    qbit_username: str,
    qbit_category: str,
    download_path: str,
) -> tuple[str, str, str, str]:
    url = qbit_url.strip().rstrip("/")
    username = qbit_username.strip()
    category = qbit_category.strip()
    path = download_path.strip()

    if url:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("qBittorrent 地址必须是有效的 HTTP 或 HTTPS 地址")
    if len(url) > 2000:
        raise ValueError("qBittorrent 地址过长")
    if len(username) > 200:
        raise ValueError("qBittorrent 用户名过长")
    if len(category) > 200:
        raise ValueError("qBittorrent 分类名称过长")
    if not path:
        raise ValueError("下载保存路径不能为空")
    if not path.startswith("/"):
        raise ValueError("下载保存路径必须是以 / 开头的绝对路径")
    if len(path) > 2000:
        raise ValueError("下载保存路径过长")
    return url, username, category, path


def save_qbittorrent_config(
    db: Session,
    *,
    qbit_url: str,
    qbit_username: str,
    qbit_password: str | None,
    clear_password: bool,
    qbit_category: str,
    download_path: str,
) -> QBittorrentConfig:
    url, username, category, path = validate_qbittorrent_values(
        qbit_url=qbit_url,
        qbit_username=qbit_username,
        qbit_category=qbit_category,
        download_path=download_path,
    )
    current = load_qbittorrent_config(db)
    password = "" if clear_password else (current.password if qbit_password is None else qbit_password)
    if len(password) > 500:
        raise ValueError("qBittorrent 密码过长")

    values = {
        "qbit_url": url,
        "qbit_username": username,
        "qbit_password": password,
        "qbit_category": category,
        "download_path": path,
    }
    existing = {
        row.key: row
        for row in db.scalars(select(AppSetting).where(AppSetting.key.in_(QBIT_SETTING_KEYS)))
    }
    for key, value in values.items():
        row = existing.get(key)
        if row:
            row.value = value
        else:
            db.add(AppSetting(key=key, value=value))
    db.commit()
    return load_qbittorrent_config(db)


def reset_qbittorrent_config(db: Session) -> QBittorrentConfig:
    db.execute(delete(AppSetting).where(AppSetting.key.in_(QBIT_SETTING_KEYS)))
    db.commit()
    return load_qbittorrent_config(db)


def get_app_setting(key: str, default: str = "", db: Session | None = None) -> str:
    def _read(session: Session) -> str:
        try:
            row = session.get(AppSetting, key)
        except (OperationalError, ProgrammingError):
            return default
        return row.value if row else default

    if db is not None:
        return _read(db)
    with SessionLocal() as session:
        return _read(session)


def set_app_setting(db: Session, key: str, value: str) -> str:
    row = db.get(AppSetting, key)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    db.commit()
    return value


_MIKAN_HIDDEN_FILTER_PREFIX = "mikan_hidden_catalog"


def _mikan_hidden_filter_key(year: int, season: str) -> str:
    return f"{_MIKAN_HIDDEN_FILTER_PREFIX}:{year}:{season}"


def load_mikan_hidden_filters(
    db: Session,
    *,
    year: int,
    season: str,
) -> dict[str, set[int]]:
    """Load locally hidden Mikan titles grouped by weekday.

    The value is stored in the existing app_settings table, so existing fnOS
    installations need no schema migration. Invalid or manually damaged JSON is
    ignored instead of preventing the catalog from loading.
    """

    raw = get_app_setting(_mikan_hidden_filter_key(year, season), "{}", db)
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(parsed, dict):
        return {}

    result: dict[str, set[int]] = {}
    for weekday, values in parsed.items():
        if not isinstance(weekday, str) or not isinstance(values, list):
            continue
        ids: set[int] = set()
        for value in values:
            try:
                bangumi_id = int(value)
            except (TypeError, ValueError):
                continue
            if bangumi_id > 0:
                ids.add(bangumi_id)
        if ids:
            result[weekday] = ids
    return result


def save_mikan_weekday_hidden_filter(
    db: Session,
    *,
    year: int,
    season: str,
    weekday: str,
    hidden_bangumi_ids: list[int] | set[int],
) -> set[int]:
    """Replace one weekday's hidden list while preserving every other weekday."""

    cleaned_weekday = " ".join((weekday or "").split()).strip()
    if not cleaned_weekday or len(cleaned_weekday) > 40:
        raise ValueError("星期名称无效")

    cleaned_ids = {int(value) for value in hidden_bangumi_ids if int(value) > 0}
    if len(cleaned_ids) > 2000:
        raise ValueError("单个星期最多保存 2000 个隐藏番剧")

    filters = load_mikan_hidden_filters(db, year=year, season=season)
    if cleaned_ids:
        filters[cleaned_weekday] = cleaned_ids
    else:
        filters.pop(cleaned_weekday, None)

    serializable = {
        name: sorted(values)
        for name, values in sorted(filters.items())
        if values
    }
    set_app_setting(
        db,
        _mikan_hidden_filter_key(year, season),
        json.dumps(serializable, ensure_ascii=False, separators=(",", ":")),
    )
    return cleaned_ids
