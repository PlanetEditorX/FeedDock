from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from .config import settings
from .outbound import external_get

_ALLOWED_SEASONS = ("冬", "春", "夏", "秋")
_SEASON_START_MONTH = {"冬": 1, "春": 4, "夏": 7, "秋": 10}
_WEEKDAYS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


def _response_json(response) -> dict[str, Any]:
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("原站返回格式不是对象")
    return payload


def _timestamp(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds > 10_000_000_000:
            seconds /= 1000
        try:
            return datetime.fromtimestamp(seconds, timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return ""
    text = str(value).strip()
    if not text:
        return ""
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return text


def _human_size(value: Any) -> str:
    try:
        size = float(value or 0)
    except (TypeError, ValueError):
        return ""
    if size <= 0:
        return ""
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    index = 0
    while size >= 1024 and index < len(units) - 1:
        size /= 1024
        index += 1
    return f"{size:.1f} {units[index]}" if index else f"{int(size)} {units[index]}"


def _preset(
    *,
    title: str,
    source_type: str,
    source_anime_id: str,
    source_name: str,
    rss_url: str,
    bangumi_id: int = 0,
    include_keywords: str = "",
) -> dict[str, Any]:
    canonical_key = f"bgm:{bangumi_id}" if bangumi_id > 0 else ""
    return {
        "name": title,
        "source_type": source_type,
        "source_anime_id": source_anime_id,
        "canonical_key": canonical_key,
        "reference_title": title,
        "tmdb_title": "",
        "bgm_url": f"https://bgm.tv/subject/{bangumi_id}" if bangumi_id else "",
        "air_date": None,
        "season": 1,
        "season_mode": "title",
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


class CatalogProvider(ABC):
    source_id: str
    source_label: str

    @abstractmethod
    def fetch_catalog(self, db: Session, year: int, season: str, query: str = "") -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def fetch_detail(self, db: Session, item: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class AniBtCatalogProvider(CatalogProvider):
    source_id = "anibt"
    source_label = "ANI.BT"
    host = "https://anibt.net"

    def fetch_catalog(self, db: Session, year: int, season: str, query: str = "") -> dict[str, Any]:
        params: dict[str, str] = {}
        if query.strip():
            params["query"] = query.strip()
        else:
            params["season"] = f"{year}-{_SEASON_START_MONTH[season]:02d}"
        response = external_get(
            f"{self.host}/api/seasons/anime",
            db=db,
            timeout=settings.request_timeout_seconds,
            headers={"User-Agent": settings.rss_user_agent, "Accept": "application/json"},
            params=params,
        )
        envelope = _response_json(response)
        data = envelope.get("data") if isinstance(envelope.get("data"), dict) else envelope
        raw_rows = data.get("byWeekday") or []
        if not isinstance(raw_rows, list):
            raise ValueError("ANI.BT 返回的 byWeekday 格式无效")
        rows: list[dict[str, Any]] = []
        for raw_row in raw_rows:
            if not isinstance(raw_row, dict):
                continue
            items: list[dict[str, Any]] = []
            for raw in raw_row.get("animes") or []:
                if not isinstance(raw, dict):
                    continue
                if not query.strip() and int(raw.get("rssReleaseCount") or 0) <= 0:
                    continue
                title_data = raw.get("title") if isinstance(raw.get("title"), dict) else {}
                title = str(title_data.get("chinese") or title_data.get("primary") or title_data.get("romaji") or "").strip()
                original = str(title_data.get("primary") or title_data.get("romaji") or title).strip()
                english = str(title_data.get("english") or original).strip()
                aliases = []
                for value in (title_data.get("chinese"), title_data.get("chineseTraditional"), title_data.get("primary"), title_data.get("romaji"), title_data.get("english")):
                    value = str(value or "").strip()
                    if value and value not in aliases:
                        aliases.append(value)
                try:
                    subject_id = int(raw.get("bgmId") or 0)
                except (TypeError, ValueError):
                    subject_id = 0
                source_anime_id = str(raw.get("animeId") or raw.get("bgmId") or "").strip()
                items.append({
                    "catalog_id": source_anime_id or subject_id,
                    "source_type": self.source_id,
                    "source_anime_id": source_anime_id,
                    "subject_id": subject_id,
                    "title": title or original or f"ANI.BT 番剧 {source_anime_id}",
                    "title_original": original,
                    "title_english": english,
                    "aliases": aliases or [title or original],
                    "rating": float(raw.get("rating") or 0),
                    "cover_url": str(raw.get("cover") or ""),
                    "cover_proxy_url": "",
                    "overview": str(
                        raw.get("overview")
                        or raw.get("description")
                        or raw.get("summary")
                        or raw.get("introduction")
                        or raw.get("synopsis")
                        or ""
                    ).strip(),
                    "rss_release_count": int(raw.get("rssReleaseCount") or 0),
                    "official_url": f"{self.host}/anime/{subject_id}" if subject_id else self.host,
                    "air_time": str(raw.get("format") or ""),
                })
            items.sort(key=lambda item: (-float(item.get("rating") or 0), str(item.get("title", "")).casefold()))
            if not items:
                continue
            weekday = str(raw_row.get("weekdayLabel") or "").strip() or "其他"
            try:
                day_of_week = int(raw_row.get("weekday") or 0)
            except (TypeError, ValueError):
                day_of_week = 0
            rows.append({"weekday": weekday, "day_of_week": day_of_week, "items": items})
        rows.sort(key=lambda row: _WEEKDAYS.index(row["weekday"]) if row["weekday"] in _WEEKDAYS else 99)
        return {
            "provider": self.source_id,
            "source_id": self.source_id,
            "year": year,
            "season": season,
            "query": query.strip(),
            "requested_season": data.get("requestedSeason") or params.get("season", ""),
            "available_seasons": data.get("availableSeasons") or [],
            "rows": rows,
            "errors": [],
            "attribution": "目录来源：ANI.BT 原站 API",
        }

    def fetch_detail(self, db: Session, item: dict[str, Any]) -> dict[str, Any]:
        subject_id = int(item.get("subject_id") or 0)
        if subject_id <= 0:
            raise ValueError("ANI.BT 条目缺少 Bangumi ID")
        response = external_get(
            f"{self.host}/api/anime/groups",
            db=db,
            timeout=settings.request_timeout_seconds,
            headers={"User-Agent": settings.rss_user_agent, "Accept": "application/json"},
            params={"bgmId": subject_id},
        )
        envelope = _response_json(response)
        data = envelope.get("data") if isinstance(envelope.get("data"), dict) else envelope
        raw_groups = data.get("groups") or []
        groups: list[dict[str, Any]] = []
        for raw in raw_groups:
            if not isinstance(raw, dict):
                continue
            slug = str(raw.get("slug") or "").strip()
            name = str(raw.get("name") or slug or "未知字幕组").strip()
            if not slug:
                continue
            rss_url = f"{self.host}/rss/anime.xml?" + urlencode({"bgmId": subject_id, "groupSlug": slug})
            entries = []
            for release in raw.get("items") or []:
                if not isinstance(release, dict):
                    continue
                entries.append({
                    "title": str(release.get("title") or ""),
                    "published_at": _timestamp(release.get("publishedAt")),
                    "download_url": str(release.get("magnet") or ""),
                    "size": _human_size(release.get("size")),
                    "episode": str(release.get("episodeKey") or ""),
                })
            groups.append({
                "subgroup_id": str(raw.get("groupId") or slug),
                "name": name,
                "rss_url": rss_url,
                "detail_url": f"{self.host}/anime/{subject_id}",
                "preset": _preset(
                    title=str(item.get("title") or "未命名番剧"),
                    source_type=self.source_id,
                    source_anime_id=str(item.get("source_anime_id") or subject_id),
                    source_name=f"ANI.BT · {name}",
                    rss_url=rss_url,
                    bangumi_id=subject_id,
                ),
                "entries": entries[:20],
                "preview_error": "",
                "updated_at": _timestamp(raw.get("lastUpdatedAt")),
            })
        return {
            "provider": self.source_id,
            "title": str(item.get("title") or "ANI.BT 番剧"),
            "subject_id": subject_id,
            "detail_url": f"{self.host}/anime/{subject_id}",
            "groups": groups,
        }


class AnimeGardenCatalogProvider(CatalogProvider):
    source_id = "ag"
    source_label = "Anime Garden"
    host = "https://api.animes.garden"

    def fetch_catalog(self, db: Session, year: int, season: str, query: str = "") -> dict[str, Any]:
        response = external_get(
            f"{self.host}/subjects",
            db=db,
            timeout=settings.request_timeout_seconds,
            headers={"User-Agent": settings.rss_user_agent, "Accept": "application/json"},
        )
        payload = _response_json(response)
        raw_subjects = payload.get("subjects") or []
        if not isinstance(raw_subjects, list):
            raise ValueError("Anime Garden 返回的 subjects 格式无效")
        all_items: list[dict[str, Any]] = []
        folded = query.strip().casefold()
        for raw in raw_subjects:
            if not isinstance(raw, dict):
                continue
            title = str(raw.get("name") or "").strip()
            keywords = [str(value).strip() for value in raw.get("keywords") or [] if str(value).strip()]
            aliases = [title, *keywords]
            if folded and not any(folded in value.casefold() for value in aliases):
                continue
            try:
                subject_id = int(raw.get("id") or 0)
            except (TypeError, ValueError):
                subject_id = 0
            active_text = str(raw.get("activedAt") or "").strip()
            try:
                active = datetime.fromisoformat(active_text.replace("Z", "+00:00"))
                if active.tzinfo is None:
                    active = active.replace(tzinfo=timezone.utc)
            except ValueError:
                active = None
            if active is not None:
                local = active.astimezone(ZoneInfo("Asia/Shanghai"))
                weekday = _WEEKDAYS[local.weekday()]
                air_time = local.strftime("%m-%d %H:%M")
            else:
                weekday = "其他"
                air_time = ""
            item = {
                "catalog_id": subject_id or str(raw.get("id") or title),
                "source_type": self.source_id,
                "source_anime_id": str(raw.get("id") or ""),
                "subject_id": subject_id,
                "title": title or f"Anime Garden 番剧 {subject_id}",
                "title_original": title,
                "title_english": "",
                "aliases": aliases or [title],
                "rating": float(raw.get("score") or 0),
                "cover_url": str(raw.get("cover") or ""),
                "cover_proxy_url": "",
                "overview": str(
                    raw.get("overview")
                    or raw.get("description")
                    or raw.get("summary")
                    or raw.get("introduction")
                    or raw.get("synopsis")
                    or ""
                ).strip(),
                "official_url": f"https://animes.garden/subject/{subject_id}" if subject_id else "https://animes.garden",
                "air_time": air_time,
                "weekday": weekday,
                "day_of_week": _WEEKDAYS.index(weekday) + 1 if weekday in _WEEKDAYS else 0,
                "actived_at": active.isoformat() if active else active_text,
            }
            all_items.append(item)
        selected = all_items
        rows: list[dict[str, Any]] = []
        for index, weekday in enumerate(_WEEKDAYS, start=1):
            items = [item for item in selected if item["weekday"] == weekday]
            items.sort(key=lambda item: (-float(item.get("rating") or 0), str(item.get("title", "")).casefold()))
            if items:
                rows.append({"weekday": weekday, "day_of_week": index, "items": items})
        other = [item for item in selected if item["weekday"] not in _WEEKDAYS]
        if other:
            rows.append({"weekday": "其他", "day_of_week": 0, "items": other})
        return {
            "provider": self.source_id,
            "source_id": self.source_id,
            "year": year,
            "season": season,
            "query": query.strip(),
            "rows": rows,
            "errors": [],
            "period_fallback": True,
            "period_notice": "Anime Garden 原站提供当前活跃周历，年份和季度仅用于保持统一界面",
            "attribution": "目录来源：Anime Garden 原站 API",
        }

    def fetch_detail(self, db: Session, item: dict[str, Any]) -> dict[str, Any]:
        subject_id = int(item.get("subject_id") or 0)
        if subject_id <= 0:
            raise ValueError("Anime Garden 条目缺少 Bangumi ID")
        response = external_get(
            f"{self.host}/resources",
            db=db,
            timeout=settings.request_timeout_seconds,
            headers={"User-Agent": settings.rss_user_agent, "Accept": "application/json"},
            params={"subject": subject_id, "pageSize": 200, "duplicate": "false"},
        )
        payload = _response_json(response)
        resources = payload.get("resources") or []
        grouped: dict[str, dict[str, Any]] = {}
        for resource in resources:
            if not isinstance(resource, dict):
                continue
            fansub = resource.get("fansub") if isinstance(resource.get("fansub"), dict) else None
            if not fansub:
                continue
            group_id = str(fansub.get("id") or fansub.get("name") or "").strip()
            name = str(fansub.get("name") or group_id or "未知字幕组").strip()
            if not group_id:
                continue
            group = grouped.setdefault(group_id, {"name": name, "entries": [], "updated_at": ""})
            created_at = _timestamp(resource.get("createdAt"))
            group["entries"].append({
                "title": str(resource.get("title") or ""),
                "published_at": created_at,
                "download_url": str(resource.get("magnet") or resource.get("href") or ""),
                "size": _human_size(resource.get("size")),
                "episode": "",
            })
            if created_at > group["updated_at"]:
                group["updated_at"] = created_at
        groups: list[dict[str, Any]] = []
        for group_id, group in sorted(grouped.items(), key=lambda pair: pair[1]["updated_at"], reverse=True):
            name = group["name"]
            rss_url = f"{self.host}/feed.xml?" + urlencode({"subject": subject_id, "fansub": name})
            groups.append({
                "subgroup_id": group_id,
                "name": name,
                "rss_url": rss_url,
                "detail_url": f"https://animes.garden/subject/{subject_id}",
                "preset": _preset(
                    title=str(item.get("title") or "未命名番剧"),
                    source_type=self.source_id,
                    source_anime_id=str(item.get("source_anime_id") or subject_id),
                    source_name=f"Anime Garden · {name}",
                    rss_url=rss_url,
                    bangumi_id=subject_id,
                ),
                "entries": group["entries"][:20],
                "preview_error": "",
                "updated_at": group["updated_at"],
            })
        return {
            "provider": self.source_id,
            "title": str(item.get("title") or "Anime Garden 番剧"),
            "subject_id": subject_id,
            "detail_url": f"https://animes.garden/subject/{subject_id}",
            "groups": groups,
        }


_PROVIDERS: dict[str, CatalogProvider] = {
    "anibt": AniBtCatalogProvider(),
    "ag": AnimeGardenCatalogProvider(),
}


def get_catalog_provider(source_id: str) -> CatalogProvider:
    provider = _PROVIDERS.get(str(source_id or "").strip().lower())
    if provider is None:
        raise ValueError("该站点没有可用的原生番剧目录")
    return provider


def native_catalog_sources() -> tuple[str, ...]:
    return tuple(_PROVIDERS)
