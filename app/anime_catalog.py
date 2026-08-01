from __future__ import annotations

import hashlib
import json
import threading
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .anime_identity import build_subscription_index, decorate_item, item_aliases, item_identity
from .catalog_providers import get_catalog_provider, native_catalog_sources
from .config import settings
from .database import SessionLocal
from .models import AnimePreference, MikanCacheEntry, Subscription, SystemLog, utcnow

_CATALOG_KIND = "source_catalog"
_DETAIL_KIND = "source_detail"
_SCHEMA_VERSION = 3
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


def _catalog_key(source_id: str, year: int, season: str) -> str:
    return f"source:catalog:{source_id}:{year}:{season}"


def _detail_key(source_id: str, item: dict[str, Any]) -> str:
    identity = str(item.get("source_anime_id") or item.get("subject_id") or item_identity(item) or item.get("title") or "")
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    return f"source:detail:{source_id}:{digest}"


def decorate_catalog(
    payload: dict[str, Any],
    source_id: str,
    subscriptions: list[Subscription],
    preferences: list[AnimePreference] | None = None,
    query: str = "",
) -> dict[str, Any]:
    get_catalog_provider(source_id)
    result = deepcopy(payload)
    folded = " ".join((query or "").split()).strip().casefold()
    result["provider"] = source_id
    result["source_id"] = source_id
    result["query"] = " ".join((query or "").split()).strip()
    subscription_index, alias_index = build_subscription_index(subscriptions)
    preference_rows = preferences or []
    rows: list[dict[str, Any]] = []
    hidden_count = 0
    for row in result.get("rows", []):
        items: list[dict[str, Any]] = []
        row_hidden = 0
        for raw in row.get("items", []):
            aliases = item_aliases(raw)
            if folded and not any(folded in value for value in aliases):
                continue
            item = decorate_item(
                raw,
                current_source=source_id,
                subscription_index=subscription_index,
                alias_index=alias_index,
                preferences=preference_rows,
            )
            item["bangumi_id"] = int(item.get("subject_id") or 0)
            item["available"] = True
            item["detail_url"] = item.get("official_url", "")
            item["base_url"] = ""
            item["update_at"] = item.get("air_time", "")
            item["action_text"] = "点击查看原站字幕组、资源和 RSS"
            if item["hidden"]:
                row_hidden += 1
            items.append(item)
        if items:
            copied = dict(row)
            copied["items"] = items
            copied["hidden_count"] = row_hidden
            rows.append(copied)
            hidden_count += row_hidden
    result["rows"] = rows
    result["hidden_count"] = hidden_count
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

    def _store(
        self,
        db: Session,
        entry: MikanCacheEntry,
    ) -> MikanCacheEntry:
        row = db.merge(entry)
        db.commit()
        db.refresh(row)
        return row

    @staticmethod
    def _remember_error(db: Session, entry: MikanCacheEntry | None, message: str) -> None:
        if entry is None:
            return
        entry.last_error = str(message)[:4000]
        db.commit()

    def catalog(
        self,
        db: Session,
        source_id: str,
        year: int,
        season: str,
        *,
        query: str = "",
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        provider = get_catalog_provider(source_id)
        key = _catalog_key(source_id, year, season)
        entry = db.get(MikanCacheEntry, key)
        cached = _loads(entry.payload_json) if entry is not None else None
        status = "cache"
        schema_version = 0
        if entry is not None:
            try:
                schema_version = int(json.loads(entry.params_json or "{}").get("schema_version") or 0)
            except (TypeError, ValueError, json.JSONDecodeError):
                schema_version = 0
        needs_refresh = entry is None or force_refresh or schema_version < _SCHEMA_VERSION
        if needs_refresh:
            try:
                payload = provider.fetch_catalog(db, year, season, query="")
            except Exception as exc:
                self._remember_error(db, entry, str(exc))
                if cached is None:
                    raise
                payload = cached
                status = "stale_cache_after_error"
            else:
                entry = self._store(
                    db,
                    MikanCacheEntry(
                        cache_key=key,
                        kind=_CATALOG_KIND,
                        params_json=_dumps({
                            "source_id": source_id,
                            "year": year,
                            "season": season,
                            "schema_version": _SCHEMA_VERSION,
                        }),
                        payload_json=_dumps(payload),
                        fetched_at=utcnow(),
                        last_error="",
                    )
                )
                status = "force_refreshed" if force_refresh else "cache_miss_fetched"
        else:
            payload = cached or {}
        if entry is None:
            raise RuntimeError("目录缓存保存失败")
        result = self._metadata(payload, entry, status)
        result["query"] = query.strip()
        return result

    def detail(
        self,
        db: Session,
        source_id: str,
        item: dict[str, Any],
        *,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        provider = get_catalog_provider(source_id)
        key = _detail_key(source_id, item)
        entry = db.get(MikanCacheEntry, key)
        cached = _loads(entry.payload_json) if entry is not None else None
        status = "cache"
        if entry is None or force_refresh:
            try:
                payload = provider.fetch_detail(db, item)
            except Exception as exc:
                self._remember_error(db, entry, str(exc))
                if cached is None:
                    raise
                payload = cached
                status = "stale_cache_after_error"
            else:
                entry = self._store(
                    db,
                    MikanCacheEntry(
                        cache_key=key,
                        kind=_DETAIL_KIND,
                        params_json=_dumps({
                            "source_id": source_id,
                            "source_anime_id": str(item.get("source_anime_id") or ""),
                            "subject_id": int(item.get("subject_id") or 0),
                            "title": str(item.get("title") or ""),
                            "schema_version": _SCHEMA_VERSION,
                        }),
                        payload_json=_dumps(payload),
                        fetched_at=utcnow(),
                        last_error="",
                    )
                )
                status = "force_refreshed" if force_refresh else "cache_miss_fetched"
        else:
            payload = cached or {}
        if entry is None:
            raise RuntimeError("资源详情缓存保存失败")
        return self._metadata(payload, entry, status)


def refresh_due_anime_catalogs(*, limit: int = 4) -> dict[str, int]:
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
                        or_(MikanCacheEntry.last_error == "", MikanCacheEntry.updated_at <= retry_before),
                    )
                    .order_by(MikanCacheEntry.fetched_at.asc())
                    .limit(limit)
                )
            )
        checked = refreshed = failed = 0
        service = AnimeCatalogCacheService()
        for row in rows:
            checked += 1
            try:
                params = json.loads(row.params_json or "{}")
                source_id = str(params.get("source_id") or "")
                if source_id not in native_catalog_sources():
                    continue
                with SessionLocal() as db:
                    service.catalog(
                        db,
                        source_id,
                        int(params["year"]),
                        str(params["season"]),
                        force_refresh=True,
                    )
                refreshed += 1
            except Exception as exc:
                failed += 1
                with SessionLocal() as db:
                    db.add(SystemLog(level="WARNING", message="原站番剧目录后台更新失败", details=str(exc)))
                    db.commit()
        return {"checked": checked, "refreshed": refreshed, "failed": failed}
    finally:
        _refresh_lock.release()
