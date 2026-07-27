from __future__ import annotations

import hashlib
import json
import threading
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .config import settings
from .database import SessionLocal
from .models import MikanCacheEntry, Subscription, SystemLog, utcnow
from .outbound import external_get
from .rss_parser import parse_feed
from .rss_service import extract_download_url
from .subscription_sources import classify_subscription_source

_ALLOWED_SEASONS = ("冬", "春", "夏", "秋")
_SEASON_MONTHS = {
    "冬": (1, 2, 3),
    "春": (4, 5, 6),
    "夏": (7, 8, 9),
    "秋": (10, 11, 12),
}
_WEEKDAYS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")
_CATALOG_KIND = "anime_catalog"
_DETAIL_KIND = "source_detail"
_SCHEMA_VERSION = 1
_DATA_BASE = "https://raw.githubusercontent.com/bangumi-data/bangumi-data/master/data/items"
_MAX_RESPONSE_BYTES = 16 * 1024 * 1024
_SUPPORTED_SOURCES = {"anibt", "ag", "nyaa", "subsplease"}
_SOURCE_LABELS = {"anibt": "ANI.BT", "ag": "Anime Garden", "nyaa": "Nyaa", "subsplease": "SubsPlease"}
_refresh_lock = threading.Lock()


def _loads(value: str) -> dict[str, Any]:
    payload = json.loads(value or "{}")
    if not isinstance(payload, dict):
        raise ValueError("番剧目录缓存格式无效")
    return payload


def _dumps(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _catalog_key(year: int, season: str) -> str:
    return f"anime:catalog:{year}:{season}"


def _detail_key(source_id: str, subject_id: int, title: str) -> str:
    digest = hashlib.sha256(title.encode("utf-8")).hexdigest()[:12]
    return f"anime:detail:{source_id}:{subject_id}:{digest}"


def _site_id(item: dict[str, Any], site_name: str) -> str:
    for site in item.get("sites") or []:
        if str(site.get("site", "")).casefold() == site_name.casefold():
            return str(site.get("id", "")).strip()
    return ""


def _titles(item: dict[str, Any]) -> tuple[str, str, list[str], str]:
    original = str(item.get("title", "")).strip()
    translated = item.get("titleTranslate") if isinstance(item.get("titleTranslate"), dict) else {}
    zh = [str(value).strip() for value in translated.get("zh-Hans", []) if str(value).strip()]
    en = [str(value).strip() for value in translated.get("en", []) if str(value).strip()]
    aliases: list[str] = []
    for value in [*zh, original, *en]:
        if value and value not in aliases:
            aliases.append(value)
    title = zh[0] if zh else original or (en[0] if en else "未命名番剧")
    english = en[0] if en else original
    return title, original, aliases, english


def _begin_datetime(raw: str) -> datetime | None:
    value = str(raw or "").strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _normalize_item(item: dict[str, Any]) -> dict[str, Any] | None:
    if str(item.get("type", "")).lower() not in {"tv", "web"}:
        return None
    begin = _begin_datetime(str(item.get("begin", "")))
    broadcast = str(item.get("broadcast", "")).strip()
    if begin is None or not broadcast:
        return None
    title, original, aliases, english = _titles(item)
    bangumi_raw = _site_id(item, "bangumi")
    mikan_raw = _site_id(item, "mikan")
    try:
        subject_id = int(bangumi_raw)
    except ValueError:
        subject_id = 0
    try:
        mikan_id = int(mikan_raw)
    except ValueError:
        mikan_id = 0
    stable_id = subject_id or int(hashlib.sha256(f"{original}\n{begin.isoformat()}".encode()).hexdigest()[:12], 16)
    local_begin = begin.astimezone(ZoneInfo("Asia/Tokyo"))
    return {
        "catalog_id": stable_id,
        "subject_id": subject_id,
        "mikan_id": mikan_id,
        "title": title,
        "title_original": original,
        "title_english": english,
        "aliases": aliases,
        "begin": begin.isoformat(),
        "air_time": local_begin.strftime("%m-%d %H:%M"),
        "weekday": _WEEKDAYS[local_begin.weekday()],
        "day_of_week": local_begin.weekday() + 1,
        "official_url": str(item.get("officialSite", "") or ""),
        "cover_url": "",
        "cover_proxy_url": "",
    }


def parse_bangumi_data_items(payloads: list[list[dict[str, Any]]], *, year: int, season: str) -> dict[str, Any]:
    by_key: dict[tuple[int, str], dict[str, Any]] = {}
    for payload in payloads:
        for raw in payload:
            if not isinstance(raw, dict):
                continue
            normalized = _normalize_item(raw)
            if normalized is None:
                continue
            key = (int(normalized["subject_id"]), str(normalized["title_original"]))
            by_key.setdefault(key, normalized)
    rows = []
    for index, weekday in enumerate(_WEEKDAYS, start=1):
        items = sorted(
            (item for item in by_key.values() if item["weekday"] == weekday),
            key=lambda item: (item["air_time"], item["title"].casefold()),
        )
        if items:
            rows.append({"weekday": weekday, "day_of_week": index, "items": items})
    return {
        "provider": "bangumi-data",
        "year": year,
        "season": season,
        "query": "",
        "base_url": _DATA_BASE,
        "rows": rows,
        "errors": [],
        "attribution": "番剧周历数据：bangumi-data（CC BY 4.0）",
    }


def _preset(*, title: str, source_name: str, rss_url: str, include_keywords: str = "", bangumi_id: int = 0) -> dict[str, Any]:
    return {
        "name": title,
        "reference_title": title,
        "tmdb_title": "",
        "bgm_url": f"https://bgm.tv/subject/{bangumi_id}" if bangumi_id else "",
        "air_date": None,
        "season": 1,
        "primary_rss_name": source_name,
        "rss_url": rss_url,
        "backup_rss_name": "",
        "backup_rss_url": None,
        "include_keywords": include_keywords,
        "exclude_keywords": "",
        "episode_regex": "",
        "episode_group": 0,
        "episode_offset": 0,
        "total_episodes": 0,
        "save_path_template": "{base}/{media_folder}/Season {season:02}",
        "custom_download_path": "",
        "missing_detection": False,
        "only_latest": False,
        "enabled": True,
        "sample_title": title,
        "bangumi_id": bangumi_id,
    }


def source_groups(source_id: str, item: dict[str, Any]) -> list[dict[str, Any]]:
    title = str(item.get("title", "")).strip()
    original = str(item.get("title_original", "")).strip() or title
    english = str(item.get("title_english", "")).strip() or original
    subject_id = int(item.get("subject_id") or 0)
    groups: list[dict[str, Any]] = []

    def add(name: str, rss_url: str, include: str = "") -> None:
        groups.append({
            "subgroup_id": len(groups) + 1,
            "name": name,
            "rss_url": rss_url,
            "detail_url": "",
            "preset": _preset(
                title=title,
                source_name=f"{_SOURCE_LABELS.get(source_id, source_id)} · {name}",
                rss_url=rss_url,
                include_keywords=include,
                bangumi_id=subject_id,
            ),
            "entries": [],
            "preview_error": "",
        })

    if source_id == "anibt":
        if not subject_id:
            return []
        base = f"https://anibt.net/rss/anime.xml?{urlencode({'bgmId': subject_id})}"
        add("全部发布", base)
        add("1080p", base + "&resolution=1080p")
        add("720p", base + "&resolution=720p")
    elif source_id == "ag":
        filter_value = json.dumps([{"type": "動畫", "include": [title]}], ensure_ascii=False, separators=(",", ":"))
        add("标题过滤 RSS", "https://api.animes.garden/feed.xml?" + urlencode({"filter": filter_value}))
    elif source_id == "nyaa":
        query = original or english or title
        base_params = {"page": "rss", "q": query, "c": "1_2", "f": "0"}
        add("英文字幕动画", "https://nyaa.si/?" + urlencode(base_params))
        trusted = dict(base_params); trusted["f"] = "2"
        add("可信发布", "https://nyaa.si/?" + urlencode(trusted))
        raw = dict(base_params); raw["c"] = "1_4"
        add("日文原盘", "https://nyaa.si/?" + urlencode(raw))
    elif source_id == "subsplease":
        keyword = english or original or title
        add("1080p", "https://subsplease.org/rss/?r=1080&t=", keyword)
        add("720p", "https://subsplease.org/rss/?r=720&t=", keyword)
        add("SD", "https://subsplease.org/rss/?r=sd&t=", keyword)
        add("全部分辨率", "https://subsplease.org/rss?t=", keyword)
    return groups


def _subscription_matches(source_id: str, item: dict[str, Any], subscriptions: list[Subscription]) -> bool:
    aliases = {str(value).strip().casefold() for value in item.get("aliases", []) if str(value).strip()}
    subject_id = int(item.get("subject_id") or 0)
    for subscription in subscriptions:
        if classify_subscription_source(subscription.rss_url) != source_id:
            continue
        if source_id == "anibt" and subject_id and subscription.bangumi_id == subject_id:
            return True
        candidate_values = {
            subscription.name.casefold(),
            subscription.reference_title.casefold(),
            subscription.manual_title.casefold(),
        }
        if aliases & {value for value in candidate_values if value}:
            return True
        include = subscription.include_keywords.casefold()
        if include and any(alias and alias in include for alias in aliases):
            return True
    return False


def decorate_catalog(payload: dict[str, Any], source_id: str, subscriptions: list[Subscription], query: str = "") -> dict[str, Any]:
    if source_id not in _SUPPORTED_SOURCES:
        raise ValueError("该站点不支持番剧周历")
    result = deepcopy(payload)
    folded = " ".join((query or "").split()).strip().casefold()
    result["provider"] = source_id
    result["source_id"] = source_id
    result["query"] = " ".join((query or "").split()).strip()
    rows = []
    for row in result.get("rows", []):
        items = []
        for raw in row.get("items", []):
            aliases = [str(value) for value in raw.get("aliases", [])]
            if folded and not any(folded in value.casefold() for value in aliases):
                continue
            item = dict(raw)
            item["bangumi_id"] = int(item.get("subject_id") or 0)
            groups = source_groups(source_id, item)
            item["available"] = bool(groups)
            item["subscribed"] = _subscription_matches(source_id, item, subscriptions)
            item["detail_url"] = item.get("official_url", "")
            item["base_url"] = ""
            item["update_at"] = item.get("air_time", "")
            item["action_text"] = "点击查看 RSS 与资源" if groups else "该站点暂不支持此条目"
            items.append(item)
        if items:
            copied = dict(row)
            copied["items"] = items
            rows.append(copied)
    result["rows"] = rows
    return result


class AnimeCatalogCacheService:
    def __init__(self) -> None:
        self.interval = timedelta(hours=settings.mikan_cache_hours)

    def _metadata(self, payload: dict[str, Any], entry: MikanCacheEntry, status: str) -> dict[str, Any]:
        fetched_at = _aware(entry.fetched_at)
        result = deepcopy(payload)
        result.update({
            "cache_status": status,
            "cached_at": fetched_at.isoformat(),
            "next_refresh_at": (fetched_at + self.interval).isoformat(),
            "refresh_interval_hours": settings.mikan_cache_hours,
            "is_stale": fetched_at + self.interval <= datetime.now(timezone.utc),
            "refresh_error": entry.last_error,
        })
        return result

    def _store(self, db: Session, key: str, kind: str, params: dict[str, Any], payload: dict[str, Any]) -> MikanCacheEntry:
        row = db.get(MikanCacheEntry, key)
        if row is None:
            row = MikanCacheEntry(cache_key=key, kind=kind, params_json=_dumps(params), payload_json=_dumps(payload), fetched_at=utcnow(), last_error="")
            db.add(row)
        else:
            row.kind = kind
            row.params_json = _dumps(params)
            row.payload_json = _dumps(payload)
            row.fetched_at = utcnow()
            row.last_error = ""
        db.commit(); db.refresh(row)
        return row

    def _fetch_catalog(self, year: int, season: str, *, db: Session | None = None) -> dict[str, Any]:
        payloads: list[list[dict[str, Any]]] = []
        errors: list[str] = []
        for month in _SEASON_MONTHS[season]:
            url = f"{_DATA_BASE}/{year}/{month:02}.json"
            try:
                response = external_get(url, db=db, timeout=settings.request_timeout_seconds, headers={"User-Agent": settings.rss_user_agent, "Accept": "application/json"})
                response.raise_for_status()
                if len(response.content) > _MAX_RESPONSE_BYTES:
                    raise ValueError("单月数据超过 16 MiB")
                parsed = response.json()
                if not isinstance(parsed, list):
                    raise ValueError("返回格式不是数组")
                payloads.append(parsed)
            except Exception as exc:
                errors.append(f"{month:02} 月：{exc}")
        if not payloads:
            raise RuntimeError("；".join(errors) or "无法读取番剧周历")
        result = parse_bangumi_data_items(payloads, year=year, season=season)
        result["errors"] = errors
        return result

    def catalog(self, db: Session, year: int, season: str, *, force_refresh: bool = False) -> dict[str, Any]:
        if not 2000 <= year <= 2100:
            raise ValueError("年份必须在 2000 到 2100 之间")
        if season not in _ALLOWED_SEASONS:
            raise ValueError("季度仅支持冬、春、夏、秋")
        key = _catalog_key(year, season)
        entry = db.get(MikanCacheEntry, key)
        needs_refresh = entry is None or force_refresh
        if entry is not None:
            try:
                needs_refresh = needs_refresh or int(_loads(entry.params_json).get("schema_version", 0)) < _SCHEMA_VERSION
            except Exception:
                needs_refresh = True
        status = "cache"
        if needs_refresh:
            try:
                payload = self._fetch_catalog(year, season, db=db)
            except Exception as exc:
                if entry is None:
                    raise
                entry.last_error = str(exc)[:4000]; db.commit()
                payload = _loads(entry.payload_json)
                status = "stale_cache_refresh_failed"
            else:
                entry = self._store(db, key, _CATALOG_KIND, {"year": year, "season": season, "schema_version": _SCHEMA_VERSION}, payload)
                status = "force_refreshed" if force_refresh else "cache_miss_fetched"
        else:
            payload = _loads(entry.payload_json)
        return self._metadata(payload, entry, status)

    def detail(self, db: Session, source_id: str, item: dict[str, Any], *, force_refresh: bool = False) -> dict[str, Any]:
        if source_id not in _SUPPORTED_SOURCES:
            raise ValueError("该站点不支持资源详情")
        subject_id = int(item.get("subject_id") or 0)
        title = str(item.get("title", "")).strip()
        if not title:
            raise ValueError("番剧标题不能为空")
        key = _detail_key(source_id, subject_id, title)
        entry = db.get(MikanCacheEntry, key)
        if entry is None or force_refresh:
            groups = source_groups(source_id, item)
            aliases = [str(value).casefold() for value in item.get("aliases", []) if str(value).strip()]
            for group in groups:
                try:
                    response = external_get(
                        group["rss_url"],
                        db=db,
                        timeout=settings.request_timeout_seconds,
                        headers={
                            "User-Agent": settings.rss_user_agent,
                            "Accept": "application/rss+xml, application/xml, text/xml, */*",
                        },
                    )
                    response.raise_for_status()
                    entries = parse_feed(response.content)
                    preview = []
                    for feed_item in entries:
                        feed_title = str(feed_item.get("title", "") or "").strip()
                        if source_id == "subsplease" and aliases and not any(alias in feed_title.casefold() for alias in aliases):
                            continue
                        preview.append({
                            "title": feed_title,
                            "published_at": str(feed_item.get("published", "") or ""),
                            "source_url": str(feed_item.get("link", "") or ""),
                            "download_url": extract_download_url(feed_item),
                        })
                        if len(preview) >= 8:
                            break
                    group["entries"] = preview
                except Exception as exc:
                    group["preview_error"] = str(exc)[:500]
            payload = {
                "provider": source_id,
                "bangumi_id": subject_id,
                "title": title,
                "base_url": "",
                "detail_url": str(item.get("official_url", "") or ""),
                "groups": groups,
            }
            entry = self._store(db, key, _DETAIL_KIND, {"source_id": source_id, "subject_id": subject_id, "title": title, "schema_version": _SCHEMA_VERSION}, payload)
            status = "force_refreshed" if force_refresh else "cache_miss_fetched"
        else:
            payload = _loads(entry.payload_json)
            status = "cache"
        return self._metadata(payload, entry, status)


def refresh_due_anime_catalogs(*, limit: int = 4) -> dict[str, int]:
    """Refresh stale shared weekly catalog pages without request bursts.

    Only catalog pages that users have already opened are refreshed. Resource
    detail previews remain on-demand because refreshing every title for every
    provider would create unnecessary traffic. Failed entries are retried at
    most once per hour.
    """

    if not _refresh_lock.acquire(blocking=False):
        return {"checked": 0, "refreshed": 0, "failed": 0}
    try:
        now = datetime.now(timezone.utc)
        due_before = now - timedelta(hours=settings.mikan_cache_hours)
        retry_before = now - timedelta(hours=1)
        with SessionLocal() as db:
            rows = list(
                db.scalars(
                    select(MikanCacheEntry)
                    .where(
                        MikanCacheEntry.kind == _CATALOG_KIND,
                        MikanCacheEntry.fetched_at <= due_before,
                        or_(
                            MikanCacheEntry.last_error == "",
                            MikanCacheEntry.updated_at <= retry_before,
                        ),
                    )
                    .order_by(MikanCacheEntry.fetched_at.asc())
                    .limit(limit)
                )
            )
            jobs = [(row.cache_key, _loads(row.params_json)) for row in rows]

        refreshed = 0
        failed = 0
        service = AnimeCatalogCacheService()
        for cache_key, params in jobs:
            with SessionLocal() as db:
                entry = db.get(MikanCacheEntry, cache_key)
                if entry is None:
                    continue
                try:
                    payload = service._fetch_catalog(int(params["year"]), str(params["season"]), db=db)
                    params["schema_version"] = _SCHEMA_VERSION
                    service._store(db, cache_key, _CATALOG_KIND, params, payload)
                    refreshed += 1
                except Exception as exc:
                    entry.last_error = str(exc)[:4000]
                    db.commit()
                    failed += 1

        if refreshed or failed:
            with SessionLocal() as db:
                db.add(
                    SystemLog(
                        level="INFO" if not failed else "WARNING",
                        message="多站点番剧周历后台刷新完成",
                        details=f"检查 {len(jobs)}，成功 {refreshed}，失败 {failed}",
                    )
                )
                db.commit()
        return {"checked": len(jobs), "refreshed": refreshed, "failed": failed}
    finally:
        _refresh_lock.release()
