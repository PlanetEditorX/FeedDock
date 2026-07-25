from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

import httpx
from sqlalchemy.orm import Session

from .config import settings
from .models import Subscription
from .naming import canonical_title
from .runtime_config import MetadataConfig, load_metadata_config


@dataclass(slots=True)
class MetadataCandidate:
    provider: str
    id: int
    media_type: str
    title: str
    original_title: str = ""
    year: int = 0
    overview: str = ""
    poster_url: str = ""
    detail_url: str = ""
    score: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MetadataRecord(MetadataCandidate):
    total_episodes: int = 0
    backdrop_url: str = ""
    season: int = 1
    air_date: str = ""


class MetadataService:
    def __init__(self, *, timeout: int | None = None) -> None:
        self.timeout = timeout or settings.request_timeout_seconds

    @staticmethod
    def _normalized(value: str) -> str:
        return re.sub(r"[^0-9a-z\u3040-\u30ff\u3400-\u9fff]+", "", (value or "").casefold())

    def _score(self, query: str, title: str, original_title: str, year: int, wanted_year: int) -> float:
        normalized_query = self._normalized(query)
        candidates = [self._normalized(title), self._normalized(original_title)]
        similarity = max(
            (SequenceMatcher(None, normalized_query, candidate).ratio() for candidate in candidates if candidate),
            default=0.0,
        )
        if normalized_query and normalized_query in candidates:
            similarity = 1.0
        if wanted_year and year:
            difference = abs(wanted_year - year)
            similarity += 0.08 if difference == 0 else (-0.04 if difference > 1 else 0.0)
        return round(max(0.0, min(1.0, similarity)), 4)

    @staticmethod
    def _headers(token: str = "") -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": settings.rss_user_agent,
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def search(
        self,
        db: Session,
        *,
        provider: str,
        query: str,
        media_type: str = "tv",
        year: int = 0,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        provider = provider.strip().lower()
        query = query.strip()
        if not query:
            raise ValueError("元数据搜索关键词不能为空")
        config = load_metadata_config(db)
        if provider == "tmdb":
            candidates = self._search_tmdb(config, query, media_type, year, limit)
        elif provider == "bangumi":
            candidates = self._search_bangumi(config, query, year, limit)
        else:
            raise ValueError("元数据来源必须是 tmdb 或 bangumi")
        for candidate in candidates:
            candidate.score = self._score(
                query, candidate.title, candidate.original_title, candidate.year, year
            )
        candidates.sort(key=lambda item: item.score, reverse=True)
        return [candidate.as_dict() for candidate in candidates[:limit]]

    def get(
        self,
        db: Session,
        *,
        provider: str,
        metadata_id: int,
        media_type: str = "tv",
        season: int = 1,
    ) -> MetadataRecord:
        if metadata_id <= 0:
            raise ValueError("元数据 ID 必须大于 0")
        config = load_metadata_config(db)
        provider = provider.strip().lower()
        if provider == "tmdb":
            return self._get_tmdb(config, metadata_id, media_type, season)
        if provider == "bangumi":
            return self._get_bangumi(config, metadata_id, season)
        raise ValueError("元数据来源必须是 tmdb 或 bangumi")

    def apply(
        self,
        db: Session,
        subscription: Subscription,
        *,
        provider: str,
        metadata_id: int,
        media_type: str | None = None,
        season: int | None = None,
    ) -> MetadataRecord:
        record = self.get(
            db,
            provider=provider,
            metadata_id=metadata_id,
            media_type=media_type or subscription.media_type,
            season=subscription.season if season is None else season,
        )
        provider = record.provider
        subscription.media_type = record.media_type
        subscription.metadata_year = record.year
        subscription.metadata_source = provider
        subscription.metadata_overview = record.overview
        subscription.poster_url = record.poster_url
        subscription.backdrop_url = record.backdrop_url
        subscription.metadata_last_synced_at = datetime.now(timezone.utc)
        if record.air_date:
            subscription.air_date = record.air_date

        if provider == "tmdb":
            subscription.tmdb_id = record.id
            subscription.tmdb_title = record.title
        else:
            subscription.bangumi_id = record.id
            subscription.reference_title = record.title
            subscription.bgm_url = record.detail_url

        if record.total_episodes > 0 and not subscription.total_episodes_locked:
            subscription.total_episodes = record.total_episodes
            subscription.total_episodes_source = provider
        db.commit()
        db.refresh(subscription)
        return record

    def sync(self, db: Session, subscription: Subscription, provider: str = "auto") -> MetadataRecord:
        requested = provider.strip().lower()
        if requested not in {"auto", "tmdb", "bangumi"}:
            raise ValueError("同步来源必须是 auto、tmdb 或 bangumi")

        if requested in {"auto", "tmdb"} and subscription.tmdb_id:
            return self.apply(
                db,
                subscription,
                provider="tmdb",
                metadata_id=subscription.tmdb_id,
            )
        if requested in {"auto", "bangumi"} and subscription.bangumi_id:
            return self.apply(
                db,
                subscription,
                provider="bangumi",
                metadata_id=subscription.bangumi_id,
            )

        providers = [requested] if requested != "auto" else ["tmdb", "bangumi"]
        query = canonical_title(subscription)
        year = subscription.metadata_year or (
            int(subscription.air_date[:4]) if subscription.air_date[:4].isdigit() else 0
        )
        errors: list[str] = []
        for candidate_provider in providers:
            try:
                results = self.search(
                    db,
                    provider=candidate_provider,
                    query=query,
                    media_type=subscription.media_type,
                    year=year,
                    limit=5,
                )
            except Exception as exc:
                errors.append(f"{candidate_provider}: {exc}")
                continue
            if not results:
                continue
            best = results[0]
            if float(best.get("score", 0)) < 0.62:
                errors.append(f"{candidate_provider}: 最佳匹配置信度过低")
                continue
            return self.apply(
                db,
                subscription,
                provider=candidate_provider,
                metadata_id=int(best["id"]),
                media_type=str(best.get("media_type") or subscription.media_type),
            )
        raise ValueError("自动匹配失败；请手动搜索并选择条目。" + ("；".join(errors) if errors else ""))

    def _search_tmdb(
        self,
        config: MetadataConfig,
        query: str,
        media_type: str,
        year: int,
        limit: int,
    ) -> list[MetadataCandidate]:
        if not config.tmdb_read_access_token:
            raise ValueError("尚未配置 TMDB Read Access Token")
        kind = "movie" if media_type == "movie" else "tv"
        params: dict[str, Any] = {
            "query": query,
            "language": config.language,
            "include_adult": "false",
            "page": 1,
        }
        if year:
            params["primary_release_year" if kind == "movie" else "first_air_date_year"] = year
        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            response = client.get(
                f"{settings.tmdb_api_base}/search/{kind}",
                params=params,
                headers=self._headers(config.tmdb_read_access_token),
            )
            response.raise_for_status()
            payload = response.json()
        candidates: list[MetadataCandidate] = []
        for item in (payload.get("results") or [])[:limit]:
            title = str(item.get("title") or item.get("name") or "").strip()
            original = str(item.get("original_title") or item.get("original_name") or "").strip()
            date_value = str(item.get("release_date") or item.get("first_air_date") or "")
            item_year = int(date_value[:4]) if len(date_value) >= 4 and date_value[:4].isdigit() else 0
            poster_path = str(item.get("poster_path") or "")
            candidates.append(
                MetadataCandidate(
                    provider="tmdb",
                    id=int(item.get("id") or 0),
                    media_type=kind,
                    title=title or original,
                    original_title=original,
                    year=item_year,
                    overview=str(item.get("overview") or "").strip(),
                    poster_url=(f"{settings.tmdb_image_base}/w342{poster_path}" if poster_path else ""),
                    detail_url=f"https://www.themoviedb.org/{kind}/{int(item.get('id') or 0)}",
                )
            )
        return candidates

    def _get_tmdb(
        self,
        config: MetadataConfig,
        metadata_id: int,
        media_type: str,
        season: int,
    ) -> MetadataRecord:
        if not config.tmdb_read_access_token:
            raise ValueError("尚未配置 TMDB Read Access Token")
        kind = "movie" if media_type == "movie" else "tv"
        headers = self._headers(config.tmdb_read_access_token)
        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            detail_response = client.get(
                f"{settings.tmdb_api_base}/{kind}/{metadata_id}",
                params={"language": config.language},
                headers=headers,
            )
            detail_response.raise_for_status()
            detail = detail_response.json()
            season_detail: dict[str, Any] = {}
            if kind == "tv":
                season_response = client.get(
                    f"{settings.tmdb_api_base}/tv/{metadata_id}/season/{season}",
                    params={"language": config.language},
                    headers=headers,
                )
                if season_response.status_code == 200:
                    season_detail = season_response.json()
                elif season_response.status_code not in {404}:
                    season_response.raise_for_status()

        title = str(detail.get("title") or detail.get("name") or "").strip()
        original = str(detail.get("original_title") or detail.get("original_name") or "").strip()
        date_value = str(detail.get("release_date") or detail.get("first_air_date") or "")
        year = int(date_value[:4]) if len(date_value) >= 4 and date_value[:4].isdigit() else 0
        poster_path = str(season_detail.get("poster_path") or detail.get("poster_path") or "")
        backdrop_path = str(detail.get("backdrop_path") or "")
        total = 1 if kind == "movie" else len(season_detail.get("episodes") or [])
        return MetadataRecord(
            provider="tmdb",
            id=metadata_id,
            media_type=kind,
            title=title or original,
            original_title=original,
            year=year,
            overview=str(detail.get("overview") or "").strip(),
            poster_url=(f"{settings.tmdb_image_base}/original{poster_path}" if poster_path else ""),
            backdrop_url=(f"{settings.tmdb_image_base}/original{backdrop_path}" if backdrop_path else ""),
            detail_url=f"https://www.themoviedb.org/{kind}/{metadata_id}",
            total_episodes=total,
            season=season,
            air_date=date_value[:10],
        )

    def _search_bangumi(
        self,
        config: MetadataConfig,
        query: str,
        year: int,
        limit: int,
    ) -> list[MetadataCandidate]:
        body = {
            "keyword": query,
            "sort": "match",
            "filter": {"type": [2], "nsfw": False},
        }
        headers = self._headers(config.bangumi_access_token)
        headers["Content-Type"] = "application/json"
        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            response = client.post(
                f"{settings.bangumi_api_base}/v0/search/subjects",
                params={"limit": min(limit, 20), "offset": 0},
                json=body,
                headers=headers,
            )
            response.raise_for_status()
            payload = response.json()
        candidates: list[MetadataCandidate] = []
        for item in (payload.get("data") or [])[:limit]:
            date_value = str(item.get("date") or "")
            item_year = int(date_value[:4]) if len(date_value) >= 4 and date_value[:4].isdigit() else 0
            images = item.get("images") or {}
            title = str(item.get("name_cn") or item.get("name") or "").strip()
            original = str(item.get("name") or "").strip()
            subject_id = int(item.get("id") or 0)
            candidates.append(
                MetadataCandidate(
                    provider="bangumi",
                    id=subject_id,
                    media_type="tv",
                    title=title or original,
                    original_title=original,
                    year=item_year,
                    overview=str(item.get("summary") or "").strip(),
                    poster_url=str(images.get("large") or images.get("common") or ""),
                    detail_url=f"https://bangumi.tv/subject/{subject_id}",
                )
            )
        return candidates

    def _get_bangumi(
        self,
        config: MetadataConfig,
        metadata_id: int,
        season: int,
    ) -> MetadataRecord:
        headers = self._headers(config.bangumi_access_token)
        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            response = client.get(
                f"{settings.bangumi_api_base}/v0/subjects/{metadata_id}",
                headers=headers,
            )
            response.raise_for_status()
            detail = response.json()
            total = int(detail.get("total_episodes") or detail.get("eps") or 0)
            if total <= 0:
                episodes = client.get(
                    f"{settings.bangumi_api_base}/v0/episodes",
                    params={"subject_id": metadata_id, "limit": 1, "offset": 0},
                    headers=headers,
                )
                if episodes.status_code == 200:
                    total = int((episodes.json() or {}).get("total") or 0)
        date_value = str(detail.get("date") or "")
        year = int(date_value[:4]) if len(date_value) >= 4 and date_value[:4].isdigit() else 0
        images = detail.get("images") or {}
        title = str(detail.get("name_cn") or detail.get("name") or "").strip()
        original = str(detail.get("name") or "").strip()
        return MetadataRecord(
            provider="bangumi",
            id=metadata_id,
            media_type="tv",
            title=title or original,
            original_title=original,
            year=year,
            overview=str(detail.get("summary") or "").strip(),
            poster_url=str(images.get("large") or images.get("common") or ""),
            backdrop_url="",
            detail_url=f"https://bangumi.tv/subject/{metadata_id}",
            total_episodes=total,
            season=season,
            air_date=date_value[:10],
        )
