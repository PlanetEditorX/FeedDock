from __future__ import annotations

import hashlib
import json
import threading
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .config import settings
from .database import SessionLocal
from .discovery import DiscoveryService
from .models import MikanCacheEntry, SystemLog, utcnow


_CATALOG_KIND = "catalog"
_DETAIL_KIND = "detail"
_CATALOG_SCHEMA_VERSION = 2
_DETAIL_SCHEMA_VERSION = 2
_refresh_lock = threading.Lock()
_image_lock = threading.Lock()


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _catalog_key(year: int, season: str) -> str:
    return f"mikan:catalog:{year}:{season}"


def _detail_key(bangumi_id: int) -> str:
    return f"mikan:detail:{bangumi_id}"


def _loads(value: str) -> dict[str, Any]:
    parsed = json.loads(value or "{}")
    if not isinstance(parsed, dict):
        raise ValueError("Mikan 缓存数据格式无效")
    return parsed


def _dumps(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))




def _entry_schema(entry: MikanCacheEntry | None) -> int:
    if entry is None:
        return 0
    try:
        return int(_loads(entry.params_json).get("schema_version", 0))
    except (TypeError, ValueError, json.JSONDecodeError):
        return 0

def _filter_catalog(payload: dict[str, Any], query: str) -> dict[str, Any]:
    result = deepcopy(payload)
    cleaned_query = " ".join((query or "").split()).strip()
    result["query"] = cleaned_query
    if not cleaned_query:
        return result

    folded = cleaned_query.casefold()
    rows: list[dict[str, Any]] = []
    for row in result.get("rows", []):
        items = [
            item
            for item in row.get("items", [])
            if folded in str(item.get("title", "")).casefold()
        ]
        if items:
            copied = dict(row)
            copied["items"] = items
            rows.append(copied)
    result["rows"] = rows
    return result


class MikanCacheService:
    """Persistent Mikan cache shared by the UI and background refresher.

    Normal reads never revalidate an existing cache entry. This guarantees that
    repeatedly opening the page or changing a local title filter does not create
    additional Mikan requests. The scheduler refreshes known catalog entries at
    the configured interval, and explicit force-refresh endpoints bypass cache.
    """

    def __init__(self, discovery: DiscoveryService | None = None) -> None:
        self.discovery = discovery or DiscoveryService()
        self.interval = timedelta(hours=settings.mikan_cache_hours)

    def _metadata(
        self,
        payload: dict[str, Any],
        entry: MikanCacheEntry,
        *,
        cache_status: str,
    ) -> dict[str, Any]:
        fetched_at = _aware(entry.fetched_at)
        next_refresh = fetched_at + self.interval
        now = datetime.now(timezone.utc)
        result = deepcopy(payload)
        result.update(
            {
                "cache_status": cache_status,
                "cached_at": fetched_at.isoformat(),
                "next_refresh_at": next_refresh.isoformat(),
                "refresh_interval_hours": settings.mikan_cache_hours,
                "is_stale": next_refresh <= now,
                "refresh_error": entry.last_error,
            }
        )
        return result

    def _store(
        self,
        db: Session,
        *,
        cache_key: str,
        kind: str,
        params: dict[str, Any],
        payload: dict[str, Any],
    ) -> MikanCacheEntry:
        row = db.get(MikanCacheEntry, cache_key)
        now = utcnow()
        if row is None:
            row = MikanCacheEntry(
                cache_key=cache_key,
                kind=kind,
                params_json=_dumps(params),
                payload_json=_dumps(payload),
                fetched_at=now,
                last_error="",
            )
            db.add(row)
        else:
            row.kind = kind
            row.params_json = _dumps(params)
            row.payload_json = _dumps(payload)
            row.fetched_at = now
            row.last_error = ""
        db.commit()
        db.refresh(row)
        return row

    @staticmethod
    def _remember_error(db: Session, entry: MikanCacheEntry | None, message: str) -> None:
        if entry is None:
            return
        entry.last_error = message[:4000]
        entry.updated_at = utcnow()
        db.commit()

    def catalog(
        self,
        db: Session,
        year: int,
        season: str,
        query: str = "",
        *,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        key = _catalog_key(year, season)
        entry = db.get(MikanCacheEntry, key)
        status = "cache"
        needs_migration = entry is not None and _entry_schema(entry) < _CATALOG_SCHEMA_VERSION
        old_payload = _loads(entry.payload_json) if entry is not None else None

        if entry is None or force_refresh or needs_migration:
            try:
                # Always cache the full quarter. Search is applied locally so
                # changing the title filter never creates another remote call.
                payload = self.discovery.catalog(year, season, "")
            except Exception as exc:
                self._remember_error(db, entry, str(exc))
                if needs_migration and old_payload is not None:
                    payload = old_payload
                    status = "legacy_cache_refresh_failed"
                else:
                    raise
            else:
                entry = self._store(
                    db,
                    cache_key=key,
                    kind=_CATALOG_KIND,
                    params={
                        "year": year,
                        "season": season,
                        "schema_version": _CATALOG_SCHEMA_VERSION,
                    },
                    payload=payload,
                )
                if force_refresh:
                    status = "force_refreshed"
                elif needs_migration:
                    status = "cache_migrated"
                else:
                    status = "cache_miss_fetched"
        else:
            payload = old_payload or {}

        filtered = _filter_catalog(payload, query)
        return self._metadata(filtered, entry, cache_status=status)

    def detail(
        self,
        db: Session,
        bangumi_id: int,
        preferred_base: str = "",
        title: str = "",
        *,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        key = _detail_key(bangumi_id)
        entry = db.get(MikanCacheEntry, key)
        status = "cache"
        needs_migration = entry is not None and _entry_schema(entry) < _DETAIL_SCHEMA_VERSION
        old_payload = _loads(entry.payload_json) if entry is not None else None

        if entry is None or force_refresh or needs_migration:
            try:
                payload = self.discovery.mikan_detail(bangumi_id, preferred_base, title)
            except Exception as exc:
                self._remember_error(db, entry, str(exc))
                if needs_migration and old_payload is not None:
                    payload = old_payload
                    status = "legacy_cache_refresh_failed"
                else:
                    raise
            else:
                entry = self._store(
                    db,
                    cache_key=key,
                    kind=_DETAIL_KIND,
                    params={
                        "bangumi_id": bangumi_id,
                        "preferred_base": preferred_base,
                        "title": title,
                        "schema_version": _DETAIL_SCHEMA_VERSION,
                    },
                    payload=payload,
                )
                if force_refresh:
                    status = "force_refreshed"
                elif needs_migration:
                    status = "cache_migrated"
                else:
                    status = "cache_miss_fetched"
        else:
            payload = old_payload or {}

        return self._metadata(payload, entry, cache_status=status)


def refresh_due_mikan_catalogs(*, limit: int = 4) -> dict[str, int]:
    """Refresh stale catalog entries without creating request bursts.

    Only catalog pages are refreshed automatically. Detail pages are cached on
    first open and can be explicitly refreshed from their modal. This prevents a
    large library from turning into hundreds of background requests every cycle.
    Failed entries are retried no more than once per hour.
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
            jobs = [
                (row.cache_key, _loads(row.params_json))
                for row in rows
            ]

        refreshed = 0
        failed = 0
        service = MikanCacheService()
        for cache_key, params in jobs:
            with SessionLocal() as db:
                entry = db.get(MikanCacheEntry, cache_key)
                if entry is None:
                    continue
                try:
                    payload = service.discovery.catalog(
                        int(params["year"]),
                        str(params["season"]),
                        "",
                    )
                    params["schema_version"] = _CATALOG_SCHEMA_VERSION
                    service._store(
                        db,
                        cache_key=cache_key,
                        kind=_CATALOG_KIND,
                        params=params,
                        payload=payload,
                    )
                    refreshed += 1
                except Exception as exc:
                    service._remember_error(db, entry, str(exc))
                    failed += 1

        if refreshed or failed:
            with SessionLocal() as db:
                db.add(
                    SystemLog(
                        level="INFO" if not failed else "WARNING",
                        message="Mikan 缓存后台刷新完成",
                        details=f"检查 {len(jobs)}，成功 {refreshed}，失败 {failed}",
                    )
                )
                db.commit()
        return {"checked": len(jobs), "refreshed": refreshed, "failed": failed}
    finally:
        _refresh_lock.release()


def fetch_cached_mikan_image(
    base_url: str,
    image_url: str,
    *,
    discovery: DiscoveryService | None = None,
) -> tuple[bytes, str, bool]:
    """Cache cover bytes on disk so browsers do not repeatedly hit Mikan."""

    cache_dir = settings.data_dir / "mikan-image-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(f"{base_url}\n{image_url}".encode("utf-8")).hexdigest()
    data_path = cache_dir / f"{digest}.bin"
    meta_path = cache_dir / f"{digest}.json"
    max_age = timedelta(days=settings.mikan_image_cache_days)

    def read_cache() -> tuple[bytes, str, bool] | None:
        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            cached_at = datetime.fromisoformat(str(metadata["cached_at"]))
            if _aware(cached_at) + max_age <= datetime.now(timezone.utc):
                return None
            content_type = str(metadata.get("content_type", ""))
            content = data_path.read_bytes()
            if not content or not content_type.startswith("image/"):
                return None
            return content, content_type, True
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            return None

    cached = read_cache()
    if cached is not None:
        return cached

    # Avoid duplicate downloads when several browser requests for the same
    # catalog arrive at once. A single process-wide lock is sufficient because
    # images are small and only misses reach this path.
    with _image_lock:
        cached = read_cache()
        if cached is not None:
            return cached
        service = discovery or DiscoveryService()
        content, content_type = service.fetch_image(base_url, image_url)
        temporary_data = data_path.with_name(data_path.name + ".tmp")
        temporary_meta = meta_path.with_name(meta_path.name + ".tmp")
        temporary_data.write_bytes(content)
        temporary_meta.write_text(
            json.dumps(
                {
                    "cached_at": datetime.now(timezone.utc).isoformat(),
                    "content_type": content_type,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        temporary_data.replace(data_path)
        temporary_meta.replace(meta_path)
        return content, content_type, False
