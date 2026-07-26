from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


_TEXT_FIELDS = (
    "name",
    "reference_title",
    "tmdb_title",
    "bgm_url",
    "manual_title",
    "metadata_overview",
    "poster_url",
    "backdrop_url",
    "primary_rss_name",
    "backup_rss_name",
    "include_keywords",
    "exclude_keywords",
    "episode_regex",
    "file_name_template",
    "save_path_template",
    "custom_download_path",
)


class SubscriptionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    reference_title: str = ""
    tmdb_title: str = ""
    bgm_url: str = ""
    air_date: date | None = None
    season: int = Field(default=1, ge=0, le=999)

    naming_mode: str = Field(default="auto", pattern="^(auto|manual|bangumi|tmdb)$")
    media_type: str = Field(default="tv", pattern="^(tv|movie)$")
    manual_title: str = ""
    tmdb_id: int = Field(default=0, ge=0)
    bangumi_id: int = Field(default=0, ge=0)
    metadata_year: int = Field(default=0, ge=0, le=9999)
    metadata_source: str = Field(default="", max_length=32)
    metadata_overview: str = ""
    poster_url: str = ""
    backdrop_url: str = ""
    auto_metadata: bool = False

    primary_rss_name: str = ""
    rss_url: HttpUrl
    backup_rss_name: str = ""
    backup_rss_url: HttpUrl | None = None

    include_keywords: str = ""
    exclude_keywords: str = ""
    episode_regex: str = ""
    episode_group: int = Field(default=0, ge=0, le=20)
    episode_offset: int = Field(default=0, ge=-10000, le=10000)
    total_episodes: int = Field(default=0, ge=0, le=10000)
    total_episodes_locked: bool = False
    total_episodes_source: str = Field(default="", max_length=32)

    rename_enabled: bool = True
    file_name_template: str = "{title} - S{season:02}E{episode:02}"
    scrape_enabled: bool = True
    save_path_template: str = "{base}/{media_folder}/Season {season:02}"
    custom_download_path: str = ""
    missing_detection: bool = False
    only_latest: bool = False
    enabled: bool = True

    @field_validator(*_TEXT_FIELDS)
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("include_keywords")
    @classmethod
    def normalize_no_match(cls, value: str) -> str:
        return "" if value.strip() in {"无", "none", "None"} else value.strip()


class SubscriptionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    reference_title: str | None = None
    tmdb_title: str | None = None
    bgm_url: str | None = None
    air_date: date | None = None
    season: int | None = Field(default=None, ge=0, le=999)

    naming_mode: str | None = Field(default=None, pattern="^(auto|manual|bangumi|tmdb)$")
    media_type: str | None = Field(default=None, pattern="^(tv|movie)$")
    manual_title: str | None = None
    tmdb_id: int | None = Field(default=None, ge=0)
    bangumi_id: int | None = Field(default=None, ge=0)
    metadata_year: int | None = Field(default=None, ge=0, le=9999)
    metadata_source: str | None = Field(default=None, max_length=32)
    metadata_overview: str | None = None
    poster_url: str | None = None
    backdrop_url: str | None = None
    auto_metadata: bool | None = None

    primary_rss_name: str | None = None
    rss_url: HttpUrl | None = None
    backup_rss_name: str | None = None
    backup_rss_url: HttpUrl | None = None

    include_keywords: str | None = None
    exclude_keywords: str | None = None
    episode_regex: str | None = None
    episode_group: int | None = Field(default=None, ge=0, le=20)
    episode_offset: int | None = Field(default=None, ge=-10000, le=10000)
    total_episodes: int | None = Field(default=None, ge=0, le=10000)
    total_episodes_locked: bool | None = None
    total_episodes_source: str | None = Field(default=None, max_length=32)

    rename_enabled: bool | None = None
    file_name_template: str | None = None
    scrape_enabled: bool | None = None
    save_path_template: str | None = None
    custom_download_path: str | None = None
    missing_detection: bool | None = None
    only_latest: bool | None = None
    enabled: bool | None = None


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    reference_title: str
    tmdb_title: str
    bgm_url: str
    air_date: str
    season: int
    naming_mode: str
    media_type: str
    manual_title: str
    tmdb_id: int
    bangumi_id: int
    metadata_year: int
    metadata_source: str
    metadata_overview: str
    poster_url: str
    backdrop_url: str
    metadata_last_synced_at: datetime | None
    auto_metadata: bool
    primary_rss_name: str
    rss_url: str
    backup_rss_name: str
    backup_rss_url: str
    include_keywords: str
    exclude_keywords: str
    episode_regex: str
    episode_group: int
    episode_offset: int
    total_episodes: int
    total_episodes_locked: bool
    total_episodes_source: str
    rename_enabled: bool
    file_name_template: str
    scrape_enabled: bool
    save_path_template: str
    custom_download_path: str
    missing_detection: bool
    only_latest: bool
    enabled: bool
    created_at: datetime
    updated_at: datetime
    last_checked_at: datetime | None
    last_error: str
    missing_episodes: list[int] = Field(default_factory=list)
    canonical_title: str = ""
    media_folder: str = ""


class SubscriptionPreviewRequest(SubscriptionCreate):
    sample_title: str = Field(default="", max_length=1000)

    @field_validator("sample_title")
    @classmethod
    def strip_sample_title(cls, value: str) -> str:
        return value.strip()


class SubscriptionPreviewOut(BaseModel):
    parsed_episode: str = ""
    adjusted_episode: str = ""
    episode_recognized: bool = False
    preview_episode: str = ""
    matched: bool
    match_reason: str
    save_path: str
    desired_name: str = ""
    media_folder: str = ""


class GlobalRulesUpdate(BaseModel):
    exclude_rules: str = Field(default="", max_length=10000)


class FeedItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subscription_id: int
    title: str
    download_url: str
    source_url: str
    episode: str
    published_at: datetime | None
    status: str
    reason: str
    save_path: str
    desired_name: str
    qbit_tag: str
    torrent_hash: str
    rename_status: str
    rename_message: str
    download_progress: int
    completed_at: datetime | None
    scrape_status: str
    scrape_message: str
    scraped_at: datetime | None
    hidden: bool
    created_at: datetime
    updated_at: datetime


class LogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    level: str
    message: str
    details: str
    created_at: datetime


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=500)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=500)
    new_password: str = Field(min_length=10, max_length=500)


class AuthStatusOut(BaseModel):
    authenticated: bool
    username: str = ""
    must_change_password: bool = False


class UpdateStatusOut(BaseModel):
    current_version: str
    latest_version: str = ""
    update_available: bool = False
    release_url: str = ""
    published_at: str = ""
    repository: str = ""
    updater_configured: bool = False
    deployed_image: str = ""
    message: str = ""


class QBittorrentSettingsUpdate(BaseModel):
    qbit_url: str = Field(default="", max_length=2000)
    qbit_username: str = Field(default="", max_length=200)
    qbit_password: str | None = Field(default=None, max_length=500)
    clear_password: bool = False
    qbit_category: str = Field(default="rss", max_length=200)
    download_path: str = Field(default="/media", max_length=2000)

    @field_validator("qbit_url", "qbit_username", "qbit_category", "download_path")
    @classmethod
    def strip_qbit_text(cls, value: str) -> str:
        return value.strip()


class MetadataSettingsUpdate(BaseModel):
    tmdb_read_access_token: str | None = Field(default=None, max_length=2000)
    clear_tmdb_token: bool = False
    bangumi_access_token: str | None = Field(default=None, max_length=2000)
    clear_bangumi_token: bool = False
    metadata_language: str = Field(default="zh-CN", max_length=20)
    media_local_root: str = Field(default="", max_length=2000)
    emby_url: str = Field(default="", max_length=2000)
    emby_api_key: str | None = Field(default=None, max_length=1000)
    clear_emby_api_key: bool = False


class MetadataCandidateOut(BaseModel):
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


class MetadataRecordOut(MetadataCandidateOut):
    total_episodes: int = 0
    backdrop_url: str = ""
    season: int = 1
    air_date: str = ""


class MetadataApplyRequest(BaseModel):
    provider: str = Field(pattern="^(tmdb|bangumi)$")
    metadata_id: int = Field(gt=0)
    media_type: str = Field(default="tv", pattern="^(tv|movie)$")
    season: int = Field(default=1, ge=0, le=999)


class MetadataSyncRequest(BaseModel):
    provider: str = Field(default="auto", pattern="^(auto|tmdb|bangumi)$")


class DiscoverySubscriptionPresetOut(BaseModel):
    name: str
    reference_title: str = ""
    tmdb_title: str = ""
    bgm_url: str = ""
    air_date: date | None = None
    season: int = 1
    primary_rss_name: str = ""
    rss_url: str
    backup_rss_name: str = ""
    backup_rss_url: str | None = None
    include_keywords: str = ""
    exclude_keywords: str = ""
    episode_regex: str = ""
    episode_group: int = 0
    episode_offset: int = 0
    total_episodes: int = 0
    save_path_template: str = "{base}/{media_folder}/Season {season:02}"
    custom_download_path: str = ""
    missing_detection: bool = False
    only_latest: bool = False
    enabled: bool = True
    sample_title: str = ""


class DiscoveryResultOut(BaseModel):
    provider: str
    result_type: str
    id: str
    title: str
    description: str = ""
    detail_url: str = ""
    rss_url: str = ""
    source_url: str = ""
    published_at: str = ""
    download_url: str = ""
    base_url: str = ""
    bangumi_id: int | None = None
    preset: DiscoverySubscriptionPresetOut | None = None


class DiscoverySearchOut(BaseModel):
    query: str
    provider: str
    results: list[DiscoveryResultOut] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class MikanCatalogItemOut(BaseModel):
    bangumi_id: int
    title: str
    cover_url: str = ""
    cover_proxy_url: str = ""
    update_at: str = ""
    detail_url: str
    base_url: str
    hidden: bool = False


class MikanCatalogRowOut(BaseModel):
    weekday: str
    day_of_week: int | None = None
    items: list[MikanCatalogItemOut] = Field(default_factory=list)
    hidden_count: int = 0


class MikanCatalogOut(BaseModel):
    provider: str = "mikan"
    year: int
    season: str
    query: str = ""
    base_url: str
    rows: list[MikanCatalogRowOut] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    cache_status: str = "cache"
    cached_at: datetime | None = None
    next_refresh_at: datetime | None = None
    refresh_interval_hours: int = 6
    is_stale: bool = False
    refresh_error: str = ""
    hidden_count: int = 0


class MikanWeekdayFilterUpdate(BaseModel):
    year: int = Field(ge=2000, le=2100)
    season: str = Field(pattern="^(冬|春|夏|秋)$")
    weekday: str = Field(min_length=1, max_length=40)
    hidden_bangumi_ids: list[int] = Field(default_factory=list, max_length=2000)

    @field_validator("weekday")
    @classmethod
    def normalize_weekday(cls, value: str) -> str:
        return " ".join(value.split()).strip()

    @field_validator("hidden_bangumi_ids")
    @classmethod
    def normalize_hidden_ids(cls, values: list[int]) -> list[int]:
        return sorted({value for value in values if value > 0})


class MikanWeekdayFilterOut(BaseModel):
    year: int
    season: str
    weekday: str
    hidden_bangumi_ids: list[int] = Field(default_factory=list)


class MikanGroupOut(BaseModel):
    subgroup_id: int
    name: str
    rss_url: str
    detail_url: str = ""
    preset: DiscoverySubscriptionPresetOut


class MikanBangumiDetailOut(BaseModel):
    provider: str = "mikan"
    bangumi_id: int
    title: str
    base_url: str
    detail_url: str
    groups: list[MikanGroupOut] = Field(default_factory=list)
    cache_status: str = "cache"
    cached_at: datetime | None = None
    next_refresh_at: datetime | None = None
    refresh_interval_hours: int = 6
    is_stale: bool = False
    refresh_error: str = ""
