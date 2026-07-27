from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from sqlalchemy.orm import Session

from .anime_identity import normalize_title
from .catalog_providers import get_catalog_provider
from .discovery import DiscoveryService
from .mikan_cache import MikanCacheService
from .models import Subscription
from .subscription_sources import extract_source_bangumi_id, get_subscription_source

_SEASON_BY_MONTH = {
    1: "冬", 2: "冬", 3: "冬",
    4: "春", 5: "春", 6: "春",
    7: "夏", 8: "夏", 9: "夏",
    10: "秋", 11: "秋", 12: "秋",
}


def _identity_titles(subscription: Subscription, query: str = "") -> list[str]:
    values = [
        query,
        subscription.reference_title,
        subscription.tmdb_title,
        subscription.manual_title,
        subscription.name,
    ]
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = " ".join(str(value or "").split()).strip()
        normalized = normalize_title(text)
        if text and normalized and normalized not in seen:
            seen.add(normalized)
            result.append(text)
    return result


def _flatten_catalog(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for row in payload.get("rows", [])
        if isinstance(row, dict)
        for item in row.get("items", [])
        if isinstance(item, dict)
    ]


def _item_title_values(item: dict[str, Any]) -> list[str]:
    values = [
        item.get("title"),
        item.get("title_original"),
        item.get("title_english"),
        *(item.get("aliases") or []),
    ]
    return [str(value or "").strip() for value in values if str(value or "").strip()]


def _rank_item(item: dict[str, Any], titles: Iterable[str], bangumi_id: int) -> tuple[int, int, str]:
    subject_id = int(item.get("subject_id") or 0)
    if bangumi_id > 0 and subject_id == bangumi_id:
        return (0, 0, str(item.get("title") or ""))
    wanted = [normalize_title(value) for value in titles if normalize_title(value)]
    candidates = [normalize_title(value) for value in _item_title_values(item) if normalize_title(value)]
    if any(value in candidates for value in wanted):
        return (1, 0, str(item.get("title") or ""))
    if any(wanted_value in candidate or candidate in wanted_value for wanted_value in wanted for candidate in candidates):
        return (2, abs(len(candidates[0]) - len(wanted[0])) if candidates and wanted else 0, str(item.get("title") or ""))
    return (9, 9999, str(item.get("title") or ""))


def _candidate(
    *,
    source_id: str,
    anime_title: str,
    source_anime_id: str,
    rss_name: str,
    rss_url: str,
    group_name: str,
    detail_url: str,
    recent_count: int,
    bangumi_id: int = 0,
    match_reason: str = "标题匹配",
) -> dict[str, Any]:
    source = get_subscription_source(source_id)
    return {
        "source_id": source_id,
        "source_label": source.label,
        "anime_title": anime_title,
        "source_anime_id": source_anime_id,
        "bangumi_id": max(0, int(bangumi_id or 0)),
        "canonical_key": f"bgm:{int(bangumi_id)}" if int(bangumi_id or 0) > 0 else "",
        "rss_name": rss_name,
        "rss_url": rss_url,
        "group_name": group_name,
        "detail_url": detail_url,
        "recent_count": max(0, int(recent_count or 0)),
        "match_reason": match_reason,
    }


def _append_detail_candidates(
    target: list[dict[str, Any]],
    *,
    source_id: str,
    item: dict[str, Any],
    detail: dict[str, Any],
    match_reason: str,
) -> None:
    anime_title = str(detail.get("title") or item.get("title") or "未命名番剧").strip()
    actual_bangumi_id = int(item.get("subject_id") or 0) if source_id in {"anibt", "ag"} else 0
    source_anime_id = str(item.get("source_anime_id") or item.get("subject_id") or item.get("bangumi_id") or "")
    for group in detail.get("groups", []):
        if not isinstance(group, dict):
            continue
        rss_url = str(group.get("rss_url") or "").strip()
        if not rss_url:
            continue
        group_name = str(group.get("name") or "未知字幕组").strip()
        target.append(
            _candidate(
                source_id=source_id,
                anime_title=anime_title,
                source_anime_id=source_anime_id,
                bangumi_id=actual_bangumi_id,
                rss_name=f"{get_subscription_source(source_id).label} · {group_name}",
                rss_url=rss_url,
                group_name=group_name,
                detail_url=str(group.get("detail_url") or detail.get("detail_url") or ""),
                recent_count=len(group.get("entries") or []),
                match_reason=match_reason,
            )
        )


def search_subscription_rss_candidates(
    db: Session,
    subscription: Subscription,
    *,
    query: str = "",
    per_source_anime_limit: int = 2,
) -> dict[str, Any]:
    titles = _identity_titles(subscription, query)
    if not titles:
        raise ValueError("当前订阅缺少可用于搜索的标题")
    search_title = titles[0]
    candidates: list[dict[str, Any]] = []
    errors: list[str] = []
    searched_sources: list[str] = []

    # Mikan's bangumiId is a Mikan-local identifier, not Bangumi Subject ID.
    searched_sources.append("mikan")
    mikan_service = MikanCacheService(DiscoveryService())
    mikan_items: list[tuple[dict[str, Any], str]] = []
    direct_mikan_id = 0
    if subscription.source_type == "mikan":
        try:
            direct_mikan_id = int(subscription.source_anime_id or 0)
        except (TypeError, ValueError):
            direct_mikan_id = 0
    if direct_mikan_id <= 0:
        direct_mikan_id = extract_source_bangumi_id(subscription.rss_url)
    if direct_mikan_id > 0:
        mikan_items.append(({
            "title": subscription.name,
            "source_anime_id": str(direct_mikan_id),
            "bangumi_id": direct_mikan_id,
        }, "当前 Mikan 番剧 ID"))
    try:
        search_results = DiscoveryService().search_mikan(search_title, limit=8)
        wanted = {normalize_title(value) for value in titles}
        ranked = sorted(
            search_results,
            key=lambda row: (
                0 if normalize_title(str(row.get("title") or "")) in wanted else 1,
                str(row.get("title") or ""),
            ),
        )
        for row in ranked[:per_source_anime_limit]:
            mikan_id = int(row.get("bangumi_id") or 0)
            if mikan_id <= 0 or any(int(item.get("bangumi_id") or 0) == mikan_id for item, _ in mikan_items):
                continue
            mikan_items.append(({
                "title": row.get("title") or subscription.name,
                "source_anime_id": str(mikan_id),
                "bangumi_id": mikan_id,
                "base_url": row.get("base_url") or "",
            }, "标题搜索"))
    except Exception as exc:
        errors.append(f"Mikan 搜索失败：{exc}")

    for item, reason in mikan_items[:per_source_anime_limit + 1]:
        try:
            detail = mikan_service.detail(
                db,
                int(item["bangumi_id"]),
                str(item.get("base_url") or ""),
                str(item.get("title") or subscription.name),
            )
            _append_detail_candidates(candidates, source_id="mikan", item=item, detail=detail, match_reason=reason)
        except Exception as exc:
            errors.append(f"Mikan 资源读取失败：{exc}")

    now = datetime.now()
    season = _SEASON_BY_MONTH[now.month]
    for source_id in ("anibt", "ag"):
        searched_sources.append(source_id)
        provider = get_catalog_provider(source_id)
        items: list[dict[str, Any]] = []
        direct_subject_id = 0
        if subscription.source_type == source_id:
            try:
                direct_subject_id = int(subscription.source_anime_id or 0)
            except (TypeError, ValueError):
                direct_subject_id = 0
        exact_subject_id = subscription.bangumi_id if subscription.bangumi_id > 0 else direct_subject_id
        if exact_subject_id > 0:
            items.append({
                "title": subscription.reference_title or subscription.name,
                "title_original": subscription.reference_title or subscription.name,
                "aliases": titles,
                "subject_id": exact_subject_id,
                "source_anime_id": str(exact_subject_id),
            })
        try:
            catalog = provider.fetch_catalog(db, now.year, season, query=search_title)
            fetched = _flatten_catalog(catalog)
            fetched.sort(key=lambda item: _rank_item(item, titles, subscription.bangumi_id))
            for item in fetched:
                if _rank_item(item, titles, subscription.bangumi_id)[0] >= 9:
                    continue
                subject_id = int(item.get("subject_id") or 0)
                if subject_id > 0 and any(int(row.get("subject_id") or 0) == subject_id for row in items):
                    continue
                items.append(item)
                if len(items) >= per_source_anime_limit:
                    break
        except Exception as exc:
            errors.append(f"{get_subscription_source(source_id).label} 搜索失败：{exc}")

        for item in items[:per_source_anime_limit]:
            try:
                detail = provider.fetch_detail(db, item)
                item_subject_id = int(item.get("subject_id") or 0)
                if subscription.bangumi_id > 0 and item_subject_id == subscription.bangumi_id:
                    reason = "Bangumi ID 精确匹配"
                elif direct_subject_id > 0 and item_subject_id == direct_subject_id:
                    reason = "当前站点番剧 ID"
                else:
                    reason = "标题搜索"
                _append_detail_candidates(candidates, source_id=source_id, item=item, detail=detail, match_reason=reason)
            except Exception as exc:
                errors.append(f"{get_subscription_source(source_id).label} 资源读取失败：{exc}")

    deduplicated: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    current_url = str(subscription.rss_url or "").strip()
    for row in candidates:
        rss_url = row["rss_url"]
        if rss_url in seen_urls:
            continue
        seen_urls.add(rss_url)
        row["current"] = rss_url == current_url
        deduplicated.append(row)

    return {
        "subscription_id": subscription.id,
        "subscription_name": subscription.name,
        "query": search_title,
        "identity": {
            "bangumi_id": subscription.bangumi_id,
            "tmdb_id": subscription.tmdb_id,
            "anilist_id": subscription.anilist_id,
            "source_type": subscription.source_type,
            "source_anime_id": subscription.source_anime_id,
            "titles": titles,
        },
        "searched_sources": searched_sources,
        "candidates": deduplicated,
        "errors": errors,
    }
