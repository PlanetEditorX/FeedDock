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


METADATA_SETTING_KEYS = {
    "tmdb_read_access_token",
    "bangumi_access_token",
    "metadata_language",
    "media_local_root",
    "emby_url",
    "emby_api_key",
}


@dataclass(frozen=True, slots=True)
class MetadataConfig:
    tmdb_read_access_token: str
    bangumi_access_token: str
    language: str
    media_local_root: str
    emby_url: str
    emby_api_key: str
    source: str

    @property
    def tmdb_configured(self) -> bool:
        return bool(self.tmdb_read_access_token)

    @property
    def bangumi_configured(self) -> bool:
        # Most public Bangumi reads work without a token. A token is still
        # supported for administrators who need authenticated access.
        return True

    @property
    def scraper_configured(self) -> bool:
        return bool(self.media_local_root)

    @property
    def emby_configured(self) -> bool:
        return bool(self.emby_url and self.emby_api_key)

    def public_dict(self) -> dict[str, str | bool]:
        return {
            "tmdb_token_configured": self.tmdb_configured,
            "bangumi_token_configured": bool(self.bangumi_access_token),
            "metadata_language": self.language,
            "media_local_root": self.media_local_root,
            "emby_url": self.emby_url,
            "emby_api_key_configured": bool(self.emby_api_key),
            "scraper_configured": self.scraper_configured,
            "emby_configured": self.emby_configured,
            "source": self.source,
        }


def _environment_metadata_config() -> MetadataConfig:
    return MetadataConfig(
        tmdb_read_access_token=settings.tmdb_read_access_token,
        bangumi_access_token=settings.bangumi_access_token,
        language=settings.metadata_language,
        media_local_root=str(settings.media_local_root or ""),
        emby_url=settings.emby_url,
        emby_api_key=settings.emby_api_key,
        source="compose",
    )


def _load_metadata_with_session(db: Session) -> MetadataConfig:
    fallback = _environment_metadata_config()
    try:
        rows = {
            row.key: row.value
            for row in db.scalars(select(AppSetting).where(AppSetting.key.in_(METADATA_SETTING_KEYS)))
        }
    except (OperationalError, ProgrammingError):
        return fallback
    if not rows:
        return fallback
    return MetadataConfig(
        tmdb_read_access_token=rows.get(
            "tmdb_read_access_token", fallback.tmdb_read_access_token
        ),
        bangumi_access_token=rows.get("bangumi_access_token", fallback.bangumi_access_token),
        language=rows.get("metadata_language", fallback.language).strip() or "zh-CN",
        media_local_root=rows.get("media_local_root", fallback.media_local_root).strip(),
        emby_url=rows.get("emby_url", fallback.emby_url).strip().rstrip("/"),
        emby_api_key=rows.get("emby_api_key", fallback.emby_api_key),
        source="web",
    )


def load_metadata_config(db: Session | None = None) -> MetadataConfig:
    if db is not None:
        return _load_metadata_with_session(db)
    with SessionLocal() as session:
        return _load_metadata_with_session(session)


def _validate_optional_http_url(value: str, label: str) -> str:
    cleaned = value.strip().rstrip("/")
    if not cleaned:
        return ""
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{label}必须是有效的 HTTP 或 HTTPS 地址")
    if len(cleaned) > 2000:
        raise ValueError(f"{label}过长")
    return cleaned


def save_metadata_config(
    db: Session,
    *,
    tmdb_read_access_token: str | None,
    clear_tmdb_token: bool,
    bangumi_access_token: str | None,
    clear_bangumi_token: bool,
    metadata_language: str,
    media_local_root: str,
    emby_url: str,
    emby_api_key: str | None,
    clear_emby_api_key: bool,
) -> MetadataConfig:
    current = load_metadata_config(db)
    language = metadata_language.strip() or "zh-CN"
    if len(language) > 20:
        raise ValueError("元数据语言代码过长")

    local_root = media_local_root.strip().rstrip("/")
    if local_root and not local_root.startswith("/"):
        raise ValueError("本地媒体挂载目录必须是以 / 开头的绝对路径")
    if len(local_root) > 2000:
        raise ValueError("本地媒体挂载目录过长")

    clean_emby_url = _validate_optional_http_url(emby_url, "Emby 地址")
    tmdb_token = "" if clear_tmdb_token else (
        current.tmdb_read_access_token
        if tmdb_read_access_token is None
        else tmdb_read_access_token.strip()
    )
    bangumi_token = "" if clear_bangumi_token else (
        current.bangumi_access_token
        if bangumi_access_token is None
        else bangumi_access_token.strip()
    )
    emby_key = "" if clear_emby_api_key else (
        current.emby_api_key if emby_api_key is None else emby_api_key.strip()
    )
    for value, label, limit in (
        (tmdb_token, "TMDB Token", 2000),
        (bangumi_token, "Bangumi Token", 2000),
        (emby_key, "Emby API Key", 1000),
    ):
        if len(value) > limit:
            raise ValueError(f"{label}过长")

    values = {
        "tmdb_read_access_token": tmdb_token,
        "bangumi_access_token": bangumi_token,
        "metadata_language": language,
        "media_local_root": local_root,
        "emby_url": clean_emby_url,
        "emby_api_key": emby_key,
    }
    existing = {
        row.key: row
        for row in db.scalars(select(AppSetting).where(AppSetting.key.in_(METADATA_SETTING_KEYS)))
    }
    for key, value in values.items():
        row = existing.get(key)
        if row:
            row.value = value
        else:
            db.add(AppSetting(key=key, value=value))
    db.commit()
    return load_metadata_config(db)


def reset_metadata_config(db: Session) -> MetadataConfig:
    db.execute(delete(AppSetting).where(AppSetting.key.in_(METADATA_SETTING_KEYS)))
    db.commit()
    return load_metadata_config(db)
