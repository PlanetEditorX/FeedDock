from __future__ import annotations

import html
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from typing import Any

import httpx
from sqlalchemy.orm import Session

from .config import settings
from .models import Subscription
from .naming import canonical_title, title_with_year
from .outbound import external_client
from .runtime_config import MetadataConfig, load_metadata_config


@dataclass(slots=True)
class MetadataFetchArgs:
    metadata_id: int
    media_type: str = "tv"
    season: int = 1
    season_mode: str = "title"
    query_title: str = ""


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
    rating: float = 0.0
    requested_query: str = ""
    search_query: str = ""
    search_attempts: list[str] = field(default_factory=list)
    fallback_level: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MetadataRecord(MetadataCandidate):
    total_episodes: int = 0
    backdrop_url: str = ""
    season: int = 1
    air_date: str = ""
    available_seasons: list[dict[str, Any]] = field(default_factory=list)
    recommended_season: int = 1


def _tmdb_api_root(config: MetadataConfig) -> str:
    root = (getattr(config, "tmdb_api_base", "") or settings.tmdb_api_base).rstrip("/")
    return root if root.endswith("/3") else f"{root}/3"


def _tmdb_image_root(config: MetadataConfig) -> str:
    root = (getattr(config, "tmdb_image_base", "") or settings.tmdb_image_base).rstrip("/")
    return root if root.endswith("/t/p") else f"{root}/t/p"


_CHINESE_NUMBERS = {
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    "十一": 11, "十二": 12, "十三": 13, "十四": 14, "十五": 15,
}

_METADATA_YEAR_SUFFIX = re.compile(r"\s*[\(（]\s*(?:19|20)\d{2}\s*[\)）]\s*$")
_METADATA_SEASON_PATTERNS = (
    re.compile(r"\s*第\s*(?:\d{1,3}|[一二两三四五六七八九十]{1,3})\s*[季期部]\s*", re.IGNORECASE),
    re.compile(r"\s*(?:season|series)\s*\d{1,3}\s*", re.IGNORECASE),
    re.compile(r"\s*\bS\d{1,3}\b\s*", re.IGNORECASE),
    re.compile(r"\s*\b\d{1,2}(?:st|nd|rd|th)\s+season\b\s*", re.IGNORECASE),
)


def _clean_metadata_query(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _metadata_base_title(value: str) -> str:
    text = _clean_metadata_query(value)
    for separator in ("：", ":", "—", "–", "～", "~"):
        if separator in text:
            prefix = text.split(separator, 1)[0].strip()
            if len(re.sub(r"\W+", "", prefix)) >= 2:
                return prefix
    parts = text.split()
    if len(parts) >= 2:
        prefix = " ".join(parts[:-1]).strip()
        suffix = parts[-1].strip("!！?？。·")
        if re.search(r"[\u3400-\u9fff]", prefix) and 0 < len(suffix) <= 12:
            return prefix
    return text


def metadata_query_fallbacks(value: str) -> list[str]:
    """Build increasingly broad metadata queries while preserving their order."""

    original = _clean_metadata_query(value)
    if not original:
        return []
    queries = [original]
    without_year = _clean_metadata_query(_METADATA_YEAR_SUFFIX.sub("", original))
    queries.append(without_year)
    without_season = without_year
    for pattern in _METADATA_SEASON_PATTERNS:
        without_season = pattern.sub(" ", without_season)
    without_season = _clean_metadata_query(without_season)
    queries.append(without_season)
    queries.append(_metadata_base_title(without_season))
    return list(dict.fromkeys(query for query in queries if query))


def infer_season_from_title(value: str) -> int:
    text = value or ""
    patterns = (
        r"第\s*(\d{1,3})\s*[季期部]",
        r"(?:season|series)\s*(\d{1,3})",
        r"\bS(\d{1,3})\b",
        r"\b(\d{1,2})(?:st|nd|rd|th)\s+season\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return max(0, int(match.group(1)))
    match = re.search(r"第\s*([一二两三四五六七八九十]{1,3})\s*[季期部]", text)
    if match:
        return _CHINESE_NUMBERS.get(match.group(1), 0)
    return 0


def _strip_markup(value: str) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


class MetadataService:
    def __init__(self, *, timeout: int | None = None) -> None:
        self.timeout = timeout or settings.request_timeout_seconds

    @staticmethod
    def _normalized(value: str) -> str:
        return re.sub(r"[^0-9a-z\u3040-\u30ff\u3400-\u9fff]+", "", (value or "").casefold())

    def _score(self, query: str, candidate_obj: MetadataCandidate, wanted_year: int) -> float:
        normalized_query = self._normalized(query)
        title = _METADATA_YEAR_SUFFIX.sub("", candidate_obj.title)
        original_title = candidate_obj.original_title
        year = candidate_obj.year
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
        headers = {"Accept": "application/json", "User-Agent": settings.rss_user_agent}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    @staticmethod
    def _tmdb_auth(token: str) -> tuple[dict[str, str], dict[str, str]]:
        """Support both TMDB v3 API keys and v4 Read Access Tokens."""

        value = (token or "").strip()
        headers = {"Accept": "application/json", "User-Agent": settings.rss_user_agent}
        params: dict[str, str] = {}
        if re.fullmatch(r"[0-9a-fA-F]{32}", value):
            params["api_key"] = value
        elif value:
            headers["Authorization"] = f"Bearer {value}"
        return headers, params

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
        if provider not in {"tmdb", "bangumi", "anilist"}:
            raise ValueError("元数据来源必须是 tmdb、bangumi 或 anilist")

        queries = metadata_query_fallbacks(query)
        attempted: list[str] = []
        query_had_year = bool(_METADATA_YEAR_SUFFIX.search(query))
        for level, search_query in enumerate(queries):
            attempted.append(search_query)
            effective_year = 0 if query_had_year and level > 0 else year
            if provider == "tmdb":
                candidates = self._search_tmdb(db, config, search_query, media_type, effective_year, limit)
            elif provider == "bangumi":
                candidates = self._search_bangumi(db, config, search_query, effective_year, limit)
            else:
                candidates = self._search_anilist(db, search_query, effective_year, limit)
            for candidate in candidates:
                candidate.score = self._score(
                    search_query,
                    candidate,
                    year,
                )
            candidates.sort(key=lambda item: item.score, reverse=True)
            reliable = candidates and candidates[0].score >= 0.84
            if reliable or (level == len(queries) - 1 and candidates):
                for candidate in candidates:
                    candidate.requested_query = query
                    candidate.search_query = search_query
                    candidate.search_attempts = attempted.copy()
                    candidate.fallback_level = level
                return [candidate.as_dict() for candidate in candidates[:limit]]
        return []

    def get(
        self,
        db: Session,
        *,
        provider: str,
        metadata_id: int,
        media_type: str = "tv",
        season: int = 1,
        season_mode: str = "title",
        query_title: str = "",
    ) -> MetadataRecord:
        if metadata_id <= 0:
            raise ValueError("元数据 ID 必须大于 0")
        config = load_metadata_config(db)
        provider = provider.strip().lower()
        if provider == "tmdb":
            args = MetadataFetchArgs(
                metadata_id=metadata_id,
                media_type=media_type,
                season=season,
                season_mode=season_mode,
                query_title=query_title,
            )
            return self._get_tmdb(db, config, args)
        if provider == "bangumi":
            return self._get_bangumi(db, config, metadata_id, season)
        if provider == "anilist":
            return self._get_anilist(db, metadata_id, season)
        raise ValueError("元数据来源必须是 tmdb、bangumi 或 anilist")

    def apply(
        self,
        db: Session,
        subscription: Subscription,
        *,
        provider: str,
        metadata_id: int,
        media_type: str | None = None,
        season: int | None = None,
        season_mode: str | None = None,
    ) -> MetadataRecord:
        selected_mode = (season_mode or getattr(subscription, "season_mode", "title") or "title").strip().lower()
        requested_season = getattr(subscription, "season", 1) if season is None else season
        record = self.get(
            db,
            provider=provider,
            metadata_id=metadata_id,
            media_type=media_type or subscription.media_type,
            season=requested_season,
            season_mode=selected_mode,
            query_title=getattr(subscription, "name", "") or getattr(subscription, "reference_title", ""),
        )
        provider = record.provider
        subscription.media_type = record.media_type
        subscription.season = record.season
        subscription.season_mode = selected_mode
        subscription.metadata_year = record.year
        subscription.metadata_rating = max(0.0, min(10.0, float(record.rating or 0.0)))
        subscription.metadata_source = provider
        subscription.metadata_overview = record.overview
        subscription.poster_url = record.poster_url
        subscription.backdrop_url = record.backdrop_url
        subscription.metadata_last_synced_at = datetime.now(timezone.utc)
        subscription.metadata_confirmed = True
        subscription.metadata_review_skipped = False
        if record.air_date:
            subscription.air_date = record.air_date

        display_title = title_with_year(record.title, record.year)
        subscription.name = display_title or subscription.name
        if provider == "tmdb":
            subscription.tmdb_id = record.id
            subscription.tmdb_title = display_title
            if subscription.naming_mode == "auto":
                subscription.naming_mode = "tmdb"
        elif provider == "bangumi":
            subscription.bangumi_id = record.id
            subscription.reference_title = display_title
            subscription.bgm_url = record.detail_url
            if subscription.naming_mode == "auto" and not subscription.tmdb_id:
                subscription.naming_mode = "bangumi"
        else:
            subscription.anilist_id = record.id
            subscription.reference_title = display_title
            if subscription.naming_mode == "auto" and not subscription.tmdb_id and not subscription.bangumi_id:
                subscription.naming_mode = "anilist"

        if record.total_episodes > 0 and not subscription.total_episodes_locked:
            subscription.total_episodes = record.total_episodes
            subscription.total_episodes_source = provider
        db.commit()
        db.refresh(subscription)
        return record

    def sync(self, db: Session, subscription: Subscription, provider: str = "auto") -> MetadataRecord:
        requested = provider.strip().lower()
        if requested not in {"auto", "tmdb", "bangumi", "anilist"}:
            raise ValueError("同步来源必须是 auto、tmdb、bangumi 或 anilist")
        ids = {
            "tmdb": int(subscription.tmdb_id or 0),
            "bangumi": int(subscription.bangumi_id or 0),
            "anilist": int(subscription.anilist_id or 0),
        }
        if requested != "auto" and ids[requested]:
            return self.apply(db, subscription, provider=requested, metadata_id=ids[requested])
        if requested == "auto":
            for source in ("tmdb", "bangumi", "anilist"):
                if ids[source]:
                    return self.apply(db, subscription, provider=source, metadata_id=ids[source])

        providers = [requested] if requested != "auto" else ["tmdb", "bangumi", "anilist"]
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
        self, db: Session, config: MetadataConfig, query: str, media_type: str, year: int, limit: int
    ) -> list[MetadataCandidate]:
        if not config.tmdb_read_access_token:
            raise ValueError("尚未配置 TMDB API Key 或 Read Access Token")
        kind = "movie" if media_type == "movie" else "tv"
        headers, auth_params = self._tmdb_auth(config.tmdb_read_access_token)
        params: dict[str, Any] = {
            "query": query, "language": config.language, "include_adult": "false", "page": 1,
            **auth_params,
        }
        if year:
            params["primary_release_year" if kind == "movie" else "year"] = year
        url = f"{_tmdb_api_root(config)}/search/{kind}"
        with external_client(url, db=db, timeout=self.timeout) as client:
            response = client.get(url, params=params, headers=headers)
            response.raise_for_status()
            payload = response.json()
        candidates: list[MetadataCandidate] = []
        for item in (payload.get("results") or [])[:limit]:
            title = str(item.get("title") or item.get("name") or "").strip()
            original = str(item.get("original_title") or item.get("original_name") or "").strip()
            date_value = str(item.get("release_date") or item.get("first_air_date") or "")
            item_year = int(date_value[:4]) if len(date_value) >= 4 and date_value[:4].isdigit() else 0
            poster_path = str(item.get("poster_path") or "")
            candidates.append(MetadataCandidate(
                provider="tmdb", id=int(item.get("id") or 0), media_type=kind,
                title=title_with_year(title or original, item_year), original_title=original,
                year=item_year, overview=str(item.get("overview") or "").strip(),
                poster_url=(f"{_tmdb_image_root(config)}/w342{poster_path}" if poster_path else ""),
                detail_url=f"https://www.themoviedb.org/{kind}/{int(item.get('id') or 0)}",
                rating=round(float(item.get("vote_average") or 0.0), 2),
            ))
        return candidates

    @staticmethod
    def _available_tmdb_seasons(detail: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for item in detail.get("seasons") or []:
            try:
                number = int(item.get("season_number"))
            except (TypeError, ValueError):
                continue
            rows.append({
                "season_number": number,
                "name": str(item.get("name") or ("Specials" if number == 0 else f"Season {number}")),
                "episode_count": int(item.get("episode_count") or 0),
                "air_date": str(item.get("air_date") or ""),
                "poster_path": str(item.get("poster_path") or ""),
            })
        return sorted(rows, key=lambda row: row["season_number"])

    @staticmethod
    def _latest_tmdb_season(rows: list[dict[str, Any]]) -> int:
        regular = [row for row in rows if row["season_number"] > 0 and row["episode_count"] > 0]
        if not regular:
            return 1
        today = date.today().isoformat()
        aired = [row for row in regular if not row["air_date"] or row["air_date"] <= today]
        source = aired or regular
        return max(int(row["season_number"]) for row in source)

    def _resolve_tmdb_season(
        self, rows: list[dict[str, Any]], requested: int, mode: str, query_title: str
    ) -> int:
        valid = {int(row["season_number"]) for row in rows}
        if mode == "latest":
            return self._latest_tmdb_season(rows)
        if mode == "title":
            inferred = infer_season_from_title(query_title)
            if inferred in valid:
                return inferred
        if requested in valid or not valid:
            return max(0, requested)
        return self._latest_tmdb_season(rows)

    def _get_tmdb(
        self, db: Session, config: MetadataConfig, args: MetadataFetchArgs
    ) -> MetadataRecord:
        if not config.tmdb_read_access_token:
            raise ValueError("尚未配置 TMDB API Key 或 Read Access Token")
        kind = "movie" if args.media_type == "movie" else "tv"
        headers, auth_params = self._tmdb_auth(config.tmdb_read_access_token)
        detail_url = f"{_tmdb_api_root(config)}/{kind}/{args.metadata_id}"
        with external_client(detail_url, db=db, timeout=self.timeout) as client:
            detail_response = client.get(
                detail_url, params={"language": config.language, **auth_params}, headers=headers
            )
            detail_response.raise_for_status()
            detail = detail_response.json()
            rows = self._available_tmdb_seasons(detail) if kind == "tv" else []
            resolved_season = self._resolve_tmdb_season(
                rows, args.season, args.season_mode, args.query_title
            ) if kind == "tv" else 1
            season_detail: dict[str, Any] = {}
            if kind == "tv":
                season_url = f"{_tmdb_api_root(config)}/tv/{args.metadata_id}/season/{resolved_season}"
                response = client.get(season_url, params={"language": config.language, **auth_params}, headers=headers)
                if response.status_code == 200:
                    season_detail = response.json()
                elif response.status_code != 404:
                    response.raise_for_status()

        title = str(detail.get("title") or detail.get("name") or "").strip()
        original = str(detail.get("original_title") or detail.get("original_name") or "").strip()
        date_value = str(detail.get("release_date") or detail.get("first_air_date") or "")
        year = int(date_value[:4]) if len(date_value) >= 4 and date_value[:4].isdigit() else 0
        poster_path = str(season_detail.get("poster_path") or detail.get("poster_path") or "")
        backdrop_path = str(detail.get("backdrop_path") or "")
        matched_season = next(
            (row for row in rows if row["season_number"] == resolved_season),
            None,
        )
        if kind == "movie":
            total = 1
        else:
            total = len(season_detail.get("episodes") or [])
            if total <= 0:
                total = int(matched_season["episode_count"]) if matched_season else 0
        selected_air_date = (
            str(season_detail.get("air_date") or "")
            or (str(matched_season.get("air_date") or "") if matched_season else "")
            or date_value
        )
        return MetadataRecord(
            provider="tmdb", id=args.metadata_id, media_type=kind, title=title or original,
            original_title=original, year=year, overview=str(detail.get("overview") or "").strip(),
            poster_url=(f"{_tmdb_image_root(config)}/original{poster_path}" if poster_path else ""),
            backdrop_url=(f"{_tmdb_image_root(config)}/original{backdrop_path}" if backdrop_path else ""),
            detail_url=f"https://www.themoviedb.org/{kind}/{args.metadata_id}", total_episodes=total,
            season=resolved_season, air_date=selected_air_date[:10], available_seasons=rows,
            recommended_season=resolved_season, rating=round(float(detail.get("vote_average") or 0.0), 2),
        )

    def _search_bangumi(
        self, db: Session, config: MetadataConfig, query: str, year: int, limit: int
    ) -> list[MetadataCandidate]:
        body = {"keyword": query, "sort": "match", "filter": {"type": [2], "nsfw": False}}
        headers = self._headers(config.bangumi_access_token)
        headers["Content-Type"] = "application/json"
        url = f"{settings.bangumi_api_base}/v0/search/subjects"
        with external_client(url, db=db, timeout=self.timeout) as client:
            response = client.post(url, params={"limit": min(limit, 20), "offset": 0}, json=body, headers=headers)
            response.raise_for_status()
            payload = response.json()
        candidates: list[MetadataCandidate] = []
        for item in (payload.get("data") or [])[:limit]:
            date_value = str(item.get("date") or "")
            item_year = int(date_value[:4]) if len(date_value) >= 4 and date_value[:4].isdigit() else 0
            if year and item_year and abs(item_year - year) > 2:
                continue
            images = item.get("images") or {}
            title = str(item.get("name_cn") or item.get("name") or "").strip()
            original = str(item.get("name") or "").strip()
            subject_id = int(item.get("id") or 0)
            candidates.append(MetadataCandidate(
                provider="bangumi", id=subject_id, media_type="tv",
                title=title_with_year(title or original, item_year), original_title=original,
                year=item_year, overview=str(item.get("summary") or "").strip(),
                poster_url=str(images.get("large") or images.get("common") or ""),
                detail_url=f"https://bangumi.tv/subject/{subject_id}",
                rating=round(float((item.get("rating") or {}).get("score") or 0.0), 2),
            ))
        return candidates

    def _get_bangumi(
        self, db: Session, config: MetadataConfig, metadata_id: int, season: int
    ) -> MetadataRecord:
        headers = self._headers(config.bangumi_access_token)
        url = f"{settings.bangumi_api_base}/v0/subjects/{metadata_id}"
        with external_client(url, db=db, timeout=self.timeout) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            detail = response.json()
            total = int(detail.get("total_episodes") or detail.get("eps") or 0)
            if total <= 0:
                episodes = client.get(
                    f"{settings.bangumi_api_base}/v0/episodes",
                    params={"subject_id": metadata_id, "limit": 1, "offset": 0}, headers=headers,
                )
                if episodes.status_code == 200:
                    total = int((episodes.json() or {}).get("total") or 0)
        date_value = str(detail.get("date") or "")
        year = int(date_value[:4]) if len(date_value) >= 4 and date_value[:4].isdigit() else 0
        images = detail.get("images") or {}
        title = str(detail.get("name_cn") or detail.get("name") or "").strip()
        original = str(detail.get("name") or "").strip()
        return MetadataRecord(
            provider="bangumi", id=metadata_id, media_type="tv", title=title or original,
            original_title=original, year=year, overview=str(detail.get("summary") or "").strip(),
            poster_url=str(images.get("large") or images.get("common") or ""), backdrop_url="",
            detail_url=f"https://bangumi.tv/subject/{metadata_id}", total_episodes=total,
            season=max(0, season), air_date=date_value[:10], recommended_season=max(0, season),
            rating=round(float((detail.get("rating") or {}).get("score") or 0.0), 2),
        )

    def _anilist_request(self, db: Session, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        url = settings.anilist_api_url
        with external_client(url, db=db, timeout=self.timeout) as client:
            response = client.post(
                url,
                json={"query": query, "variables": variables},
                headers={"Accept": "application/json", "Content-Type": "application/json", "User-Agent": settings.rss_user_agent},
            )
            response.raise_for_status()
            payload = response.json()
        if payload.get("errors"):
            raise ValueError(str(payload["errors"][0].get("message") or "AniList 查询失败"))
        return payload.get("data") or {}

    def _search_anilist(self, db: Session, query_text: str, year: int, limit: int) -> list[MetadataCandidate]:
        query = """
        query ($search: String!, $perPage: Int!) {
          Page(page: 1, perPage: $perPage) {
            media(search: $search, type: ANIME, sort: SEARCH_MATCH) {
              id title { romaji english native } description(asHtml: false)
              episodes startDate { year month day } coverImage { extraLarge large }
              bannerImage siteUrl format averageScore
            }
          }
        }
        """
        data = self._anilist_request(db, query, {"search": query_text, "perPage": min(limit, 20)})
        candidates: list[MetadataCandidate] = []
        for item in ((data.get("Page") or {}).get("media") or []):
            start = item.get("startDate") or {}
            item_year = int(start.get("year") or 0)
            if year and item_year and abs(item_year - year) > 2:
                continue
            titles = item.get("title") or {}
            title = str(titles.get("english") or titles.get("romaji") or titles.get("native") or "").strip()
            original = str(titles.get("native") or titles.get("romaji") or "").strip()
            cover = item.get("coverImage") or {}
            media_id = int(item.get("id") or 0)
            candidates.append(MetadataCandidate(
                provider="anilist", id=media_id, media_type="movie" if item.get("format") == "MOVIE" else "tv",
                title=title_with_year(title or original, item_year), original_title=original, year=item_year,
                overview=_strip_markup(str(item.get("description") or "")),
                poster_url=str(cover.get("extraLarge") or cover.get("large") or ""),
                detail_url=str(item.get("siteUrl") or f"https://anilist.co/anime/{media_id}"),
                rating=round(float(item.get("averageScore") or 0.0) / 10.0, 2),
            ))
        return candidates

    def _get_anilist(self, db: Session, metadata_id: int, season: int) -> MetadataRecord:
        query = """
        query ($id: Int!) {
          Media(id: $id, type: ANIME) {
            id title { romaji english native } description(asHtml: false)
            episodes startDate { year month day } coverImage { extraLarge large }
            bannerImage siteUrl format
          }
        }
        """
        data = self._anilist_request(db, query, {"id": metadata_id})
        item = data.get("Media") or {}
        titles = item.get("title") or {}
        title = str(titles.get("english") or titles.get("romaji") or titles.get("native") or "").strip()
        original = str(titles.get("native") or titles.get("romaji") or "").strip()
        start = item.get("startDate") or {}
        year = int(start.get("year") or 0)
        parts = [int(start.get(key) or 0) for key in ("year", "month", "day")]
        air_date = f"{parts[0]:04d}-{parts[1]:02d}-{parts[2]:02d}" if all(parts) else (str(year) if year else "")
        cover = item.get("coverImage") or {}
        return MetadataRecord(
            provider="anilist", id=metadata_id,
            media_type="movie" if item.get("format") == "MOVIE" else "tv",
            title=title or original, original_title=original, year=year,
            overview=_strip_markup(str(item.get("description") or "")),
            poster_url=str(cover.get("extraLarge") or cover.get("large") or ""),
            backdrop_url=str(item.get("bannerImage") or ""),
            detail_url=str(item.get("siteUrl") or f"https://anilist.co/anime/{metadata_id}"),
            total_episodes=int(item.get("episodes") or (1 if item.get("format") == "MOVIE" else 0)),
            season=max(0, season), air_date=air_date[:10], recommended_season=max(0, season),
            rating=round(float(item.get("averageScore") or 0.0) / 10.0, 2),
        )
