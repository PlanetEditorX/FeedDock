from __future__ import annotations

from dataclasses import dataclass
import json
from urllib.parse import urlparse

from sqlalchemy import delete, select, update
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from .config import settings
from .database import SessionLocal
from .models import AppSetting, Subscription


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
    old_download_path = current.download_path
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

    # Every subscription uses the same qBittorrent-visible download root. Folder
    # customization belongs in save_path_template, not in a second root path.
    db.execute(update(Subscription).values(custom_download_path=path))
    db.commit()
    return load_qbittorrent_config(db)


def reset_qbittorrent_config(db: Session) -> QBittorrentConfig:
    db.execute(delete(AppSetting).where(AppSetting.key.in_(QBIT_SETTING_KEYS)))
    fallback = _environment_config()
    db.execute(update(Subscription).values(custom_download_path=fallback.download_path))
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
}


@dataclass(frozen=True, slots=True)
class MetadataConfig:
    tmdb_read_access_token: str
    bangumi_access_token: str
    language: str
    source: str

    @property
    def tmdb_configured(self) -> bool:
        return bool(self.tmdb_read_access_token)

    @property
    def bangumi_configured(self) -> bool:
        return True

    def public_dict(self) -> dict[str, str | bool]:
        return {
            "tmdb_token_configured": self.tmdb_configured,
            "bangumi_token_configured": bool(self.bangumi_access_token),
            "anilist_configured": True,
            "metadata_language": self.language,
            "source": self.source,
        }


def _bool_value(value: str | bool | None, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _environment_metadata_config() -> MetadataConfig:
    return MetadataConfig(
        tmdb_read_access_token=settings.tmdb_read_access_token,
        bangumi_access_token=settings.bangumi_access_token,
        language=settings.metadata_language,
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
        tmdb_read_access_token=rows.get("tmdb_read_access_token", fallback.tmdb_read_access_token),
        bangumi_access_token=rows.get("bangumi_access_token", fallback.bangumi_access_token),
        language=rows.get("metadata_language", fallback.language).strip() or "zh-CN",
        source="web",
    )


def load_metadata_config(db: Session | None = None) -> MetadataConfig:
    if db is not None:
        return _load_metadata_with_session(db)
    with SessionLocal() as session:
        return _load_metadata_with_session(session)


def save_metadata_config(
    db: Session,
    *,
    tmdb_read_access_token: str | None,
    clear_tmdb_token: bool,
    bangumi_access_token: str | None,
    clear_bangumi_token: bool,
    metadata_language: str,
) -> MetadataConfig:
    current = load_metadata_config(db)
    language = metadata_language.strip() or "zh-CN"
    if len(language) > 20:
        raise ValueError("元数据语言代码过长")

    tmdb_token = "" if clear_tmdb_token else (
        current.tmdb_read_access_token if tmdb_read_access_token is None else tmdb_read_access_token.strip()
    )
    bangumi_token = "" if clear_bangumi_token else (
        current.bangumi_access_token if bangumi_access_token is None else bangumi_access_token.strip()
    )
    if len(tmdb_token) > 2000:
        raise ValueError("TMDB Token 过长")
    if len(bangumi_token) > 2000:
        raise ValueError("Bangumi Token 过长")

    values = {
        "tmdb_read_access_token": tmdb_token,
        "bangumi_access_token": bangumi_token,
        "metadata_language": language,
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


AUTOMATION_SETTING_KEYS = {
    "automation_download_enabled",
    "automation_time",
    "automation_timezone",
    "automation_last_run_date",
}


@dataclass(frozen=True, slots=True)
class AutomationConfig:
    download_enabled: bool
    daily_time: str
    timezone: str
    last_run_date: str
    source: str

    @property
    def enabled(self) -> bool:
        return self.download_enabled

    def public_dict(self) -> dict[str, str | bool]:
        return {
            "download_enabled": self.download_enabled,
            "daily_time": self.daily_time,
            "timezone": self.timezone,
            "last_run_date": self.last_run_date,
            "enabled": self.enabled,
            "source": self.source,
        }


def _valid_daily_time(value: str) -> str:
    cleaned = value.strip()
    parts = cleaned.split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ValueError("执行时间必须是 HH:MM 格式")
    hour, minute = map(int, parts)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("执行时间必须在 00:00 到 23:59 之间")
    return f"{hour:02d}:{minute:02d}"


def load_automation_config(db: Session | None = None) -> AutomationConfig:
    def _load(session: Session) -> AutomationConfig:
        fallback = AutomationConfig(
            download_enabled=False,
            daily_time=_valid_daily_time(settings.automation_time),
            timezone=settings.automation_timezone,
            last_run_date="",
            source="compose",
        )
        try:
            rows = {
                row.key: row.value
                for row in session.scalars(select(AppSetting).where(AppSetting.key.in_(AUTOMATION_SETTING_KEYS)))
            }
        except (OperationalError, ProgrammingError):
            return fallback
        if not rows:
            return fallback
        try:
            daily_time = _valid_daily_time(rows.get("automation_time", fallback.daily_time))
        except ValueError:
            daily_time = fallback.daily_time
        return AutomationConfig(
            download_enabled=_bool_value(rows.get("automation_download_enabled"), fallback.download_enabled),
            daily_time=daily_time,
            timezone=rows.get("automation_timezone", fallback.timezone).strip() or fallback.timezone,
            last_run_date=rows.get("automation_last_run_date", "").strip(),
            source="web",
        )
    if db is not None:
        return _load(db)
    with SessionLocal() as session:
        return _load(session)


def save_automation_config(
    db: Session,
    *,
    download_enabled: bool,
    daily_time: str,
    timezone: str,
) -> AutomationConfig:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    valid_time = _valid_daily_time(daily_time)
    timezone = timezone.strip() or settings.timezone
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("无效的 IANA 时区，例如 Asia/Shanghai") from exc
    values = {
        "automation_download_enabled": "1" if download_enabled else "0",
        "automation_time": valid_time,
        "automation_timezone": timezone,
    }
    for key, value in values.items():
        row = db.get(AppSetting, key)
        if row:
            row.value = value
        else:
            db.add(AppSetting(key=key, value=value))
    db.commit()
    return load_automation_config(db)


def mark_automation_run(db: Session, local_date: str) -> None:
    set_app_setting(db, "automation_last_run_date", local_date)


def reset_automation_config(db: Session) -> AutomationConfig:
    db.execute(delete(AppSetting).where(AppSetting.key.in_(AUTOMATION_SETTING_KEYS)))
    db.commit()
    return load_automation_config(db)


PROXY_SETTING_KEYS = {"proxy_enabled", "proxy_url", "proxy_no_proxy"}


@dataclass(frozen=True, slots=True)
class ProxyConfig:
    enabled: bool
    url: str
    no_proxy: str
    source: str

    @property
    def configured(self) -> bool:
        return bool(self.enabled and self.url)

    def public_dict(self) -> dict[str, str | bool]:
        return {
            "enabled": self.enabled,
            "url_configured": bool(self.url),
            "no_proxy": self.no_proxy,
            "configured": self.configured,
            "source": self.source,
        }


def _validate_proxy_url(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return ""
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https", "socks5", "socks5h"} or not parsed.hostname:
        raise ValueError("代理地址必须是 http://、https://、socks5:// 或 socks5h://")
    if len(cleaned) > 2000:
        raise ValueError("代理地址过长")
    return cleaned


def load_proxy_config(db: Session | None = None) -> ProxyConfig:
    def _load(session: Session) -> ProxyConfig:
        fallback = ProxyConfig(
            enabled=bool(settings.outbound_proxy_url),
            url=settings.outbound_proxy_url,
            no_proxy=settings.outbound_no_proxy,
            source="compose",
        )
        try:
            rows = {
                row.key: row.value
                for row in session.scalars(select(AppSetting).where(AppSetting.key.in_(PROXY_SETTING_KEYS)))
            }
        except (OperationalError, ProgrammingError):
            return fallback
        if not rows:
            return fallback
        return ProxyConfig(
            enabled=_bool_value(rows.get("proxy_enabled"), fallback.enabled),
            url=rows.get("proxy_url", fallback.url),
            no_proxy=rows.get("proxy_no_proxy", fallback.no_proxy),
            source="web",
        )
    if db is not None:
        return _load(db)
    with SessionLocal() as session:
        return _load(session)


def save_proxy_config(
    db: Session,
    *,
    enabled: bool,
    proxy_url: str | None,
    clear_proxy_url: bool,
    no_proxy: str,
) -> ProxyConfig:
    current = load_proxy_config(db)
    url = "" if clear_proxy_url else (
        current.url if proxy_url is None else _validate_proxy_url(proxy_url)
    )
    if enabled and not url:
        raise ValueError("启用代理时必须填写代理地址")
    cleaned_no_proxy = ",".join(part.strip() for part in no_proxy.split(",") if part.strip())
    if len(cleaned_no_proxy) > 4000:
        raise ValueError("不使用代理的地址列表过长")
    values = {
        "proxy_enabled": "1" if enabled else "0",
        "proxy_url": url,
        "proxy_no_proxy": cleaned_no_proxy,
    }
    for key, value in values.items():
        row = db.get(AppSetting, key)
        if row:
            row.value = value
        else:
            db.add(AppSetting(key=key, value=value))
    db.commit()
    return load_proxy_config(db)


def reset_proxy_config(db: Session) -> ProxyConfig:
    db.execute(delete(AppSetting).where(AppSetting.key.in_(PROXY_SETTING_KEYS)))
    db.commit()
    return load_proxy_config(db)
