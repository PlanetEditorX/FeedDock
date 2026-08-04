from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

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
    "catalog_weekday",
    "catalog_air_time",
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
    source_type: str = Field(default="", max_length=32)
    source_anime_id: str = Field(default="", max_length=120)
    canonical_key: str = Field(default="", max_length=255)
    subscription_mode: Literal["subscribed", "trial"] = "subscribed"
    trial_bulk: bool = False
    reference_title: str = ""
    tmdb_title: str = ""
    bgm_url: str = ""
    air_date: date | None = None
    catalog_weekday: str = ""
    catalog_air_time: str = ""
    season: int = Field(default=1, ge=0, le=999)
    season_mode: str = Field(default="title", pattern="^(manual|latest|title)$")

    naming_mode: str = Field(default="auto", pattern="^(auto|manual|bangumi|tmdb|anilist)$")
    media_type: str = Field(default="tv", pattern="^(tv|movie)$")
    manual_title: str = ""
    tmdb_id: int = Field(default=0, ge=0)
    bangumi_id: int = Field(default=0, ge=0)
    anilist_id: int = Field(default=0, ge=0)
    metadata_year: int = Field(default=0, ge=0, le=9999)
    metadata_rating: float = Field(default=0.0, ge=0.0, le=10.0)
    metadata_source: str = Field(default="", max_length=32)
    metadata_overview: str = ""
    poster_url: str = ""
    backdrop_url: str = ""
    auto_metadata: bool = False
    metadata_confirmed: bool = False
    metadata_review_skipped: bool = False

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
    scrape_enabled: bool = False
    scrape_mode: str = Field(default="off", pattern="^(local|tmm|both|off)$")
    save_path_template: str = "{base}/{media_folder}/Season {season:02}"
    custom_download_path: str = ""
    missing_detection: bool = False
    only_latest: bool = False
    auto_disable_when_complete: bool = False
    stale_days: int = Field(default=0, ge=0, le=3650)
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
    source_type: str | None = Field(default=None, max_length=32)
    source_anime_id: str | None = Field(default=None, max_length=120)
    canonical_key: str | None = Field(default=None, max_length=255)
    subscription_mode: Literal["subscribed", "trial"] | None = None
    trial_bulk: bool | None = None
    reference_title: str | None = None
    tmdb_title: str | None = None
    bgm_url: str | None = None
    air_date: date | None = None
    catalog_weekday: str | None = None
    catalog_air_time: str | None = None
    season: int | None = Field(default=None, ge=0, le=999)
    season_mode: str | None = Field(default=None, pattern="^(manual|latest|title)$")

    naming_mode: str | None = Field(default=None, pattern="^(auto|manual|bangumi|tmdb|anilist)$")
    media_type: str | None = Field(default=None, pattern="^(tv|movie)$")
    manual_title: str | None = None
    tmdb_id: int | None = Field(default=None, ge=0)
    bangumi_id: int | None = Field(default=None, ge=0)
    anilist_id: int | None = Field(default=None, ge=0)
    metadata_year: int | None = Field(default=None, ge=0, le=9999)
    metadata_rating: float | None = Field(default=None, ge=0.0, le=10.0)
    metadata_source: str | None = Field(default=None, max_length=32)
    metadata_overview: str | None = None
    poster_url: str | None = None
    backdrop_url: str | None = None
    auto_metadata: bool | None = None
    metadata_confirmed: bool | None = None
    metadata_review_skipped: bool | None = None

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
    scrape_mode: str | None = Field(default=None, pattern="^(local|tmm|both|off)$")
    save_path_template: str | None = None
    custom_download_path: str | None = None
    missing_detection: bool | None = None
    only_latest: bool | None = None
    auto_disable_when_complete: bool | None = None
    stale_days: int | None = Field(default=None, ge=0, le=3650)
    enabled: bool | None = None


class AnimePreferenceItem(BaseModel):
    canonical_key: str = Field(min_length=1, max_length=255)
    title: str = Field(default="", max_length=300)
    bangumi_id: int = Field(default=0, ge=0)
    hidden: bool = True
    reason: str = Field(default="", max_length=500)


class AnimePreferenceBatchUpdate(BaseModel):
    items: list[AnimePreferenceItem] = Field(min_length=1, max_length=500)


class SubscriptionBatchRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=1000)
    action: Literal["enable", "disable", "delete"]

    @field_validator("ids")
    @classmethod
    def unique_positive_ids(cls, values: list[int]) -> list[int]:
        unique: list[int] = []
        seen: set[int] = set()
        for value in values:
            if value <= 0 or value in seen:
                continue
            seen.add(value)
            unique.append(value)
        if not unique:
            raise ValueError("至少选择一个有效订阅")
        return unique


class SubscriptionImportRequest(BaseModel):
    subscriptions: list[SubscriptionCreate] = Field(min_length=1, max_length=500)
    conflict: Literal["skip", "update"] = "skip"




class SystemBackupImportRequest(BaseModel):
    backup: dict[str, Any]
    mode: Literal["merge", "replace"] = "merge"
    subscription_conflict: Literal["skip", "update"] = "update"


class RssCandidateSearchRequest(BaseModel):
    query: str = Field(default="", max_length=300)

    @field_validator("query")
    @classmethod
    def strip_query(cls, value: str) -> str:
        return value.strip()


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    source_type: str = "other"
    source_anime_id: str = ""
    canonical_key: str = ""
    subscription_mode: Literal["subscribed", "trial"] = "subscribed"
    trial_bulk: bool = False
    reference_title: str
    tmdb_title: str
    bgm_url: str
    air_date: str
    catalog_weekday: str
    catalog_air_time: str
    season: int
    season_mode: str
    naming_mode: str
    media_type: str
    manual_title: str
    tmdb_id: int
    bangumi_id: int
    anilist_id: int
    metadata_year: int
    metadata_rating: float
    metadata_source: str
    metadata_overview: str
    poster_url: str
    backdrop_url: str
    metadata_last_synced_at: datetime | None
    auto_metadata: bool
    metadata_confirmed: bool
    metadata_review_skipped: bool
    primary_rss_name: str
    rss_url: str
    source_type: str = "other"
    source_label: str = "其它 RSS"
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
    total_episodes_checked_at: datetime | None
    rename_enabled: bool
    file_name_template: str
    scrape_enabled: bool
    scrape_mode: str
    save_path_template: str
    custom_download_path: str
    missing_detection: bool
    only_latest: bool
    auto_disable_when_complete: bool
    stale_days: int
    last_new_item_at: datetime | None
    last_stale_notified_at: datetime | None
    completion_notified_at: datetime | None
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


class MikanTrialRequest(BaseModel):
    year: int = Field(ge=2000, le=2100)
    season: Literal["冬", "春", "夏", "秋"]


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
    trial_download_path: str
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
    trackers_status: str
    trackers_message: str
    trackers_applied_at: datetime | None
    qbit_record_removed_at: datetime | None
    qbit_record_remove_message: str
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


class LogSettingsUpdate(BaseModel):
    level: str = Field(default="INFO", max_length=16)

    @field_validator("level")
    @classmethod
    def validate_level(cls, value: str) -> str:
        level = value.strip().upper()
        if level not in {"INFO", "DEBUG"}:
            raise ValueError("日志级别只能是 INFO 或 DEBUG")
        return level


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
    source: str = "local"
    checked_at: str = ""
    manifest_url: str = ""
    can_apply_update: bool = False
    current_revision: str = ""
    latest_revision: str = ""
    latest_digest: str = ""
    platform_digest: str = ""
    image_platform: str = ""
    current_build_source: str = ""
    current_created_at: str = ""
    metadata_consistent: bool = True


class QBittorrentSettingsUpdate(BaseModel):
    qbit_url: str = Field(default="", max_length=2000)
    qbit_auth_mode: Literal["password", "api_key"] = "password"
    qbit_username: str = Field(default="", max_length=200)
    qbit_password: str | None = Field(default=None, max_length=500)
    clear_password: bool = False
    qbit_api_key: str | None = Field(default=None, max_length=500)
    clear_api_key: bool = False
    qbit_category: str = Field(default="rss", max_length=200)
    download_path: str = Field(default="/media", max_length=2000)

    @field_validator("qbit_url", "qbit_username", "qbit_category", "download_path")
    @classmethod
    def strip_qbit_text(cls, value: str) -> str:
        return value.strip()


class ApplicationPreferencesUpdate(BaseModel):
    theme_color: Literal["blue", "indigo", "green", "orange", "rose"] = "blue"
    subscription_sort: Literal["weekday", "updated", "created", "name", "rating", "pinyin"] = "updated"
    retry_count: int = Field(default=2, ge=0, le=10)
    concurrent_limit: int = Field(default=3, ge=0, le=100)
    seeding_minutes: int = Field(default=-1, ge=-1, le=525600)
    cleanup_completed_enabled: bool = False
    cleanup_completed_delay_minutes: int = Field(default=1, ge=1, le=525600)
    rss_enabled: bool = True
    rss_timeout_seconds: int = Field(default=20, ge=5, le=300)
    auto_skip_existing: bool = True
    auto_disable_complete: bool = False
    trackers_enabled: bool = True
    trackers_update_url: str = Field(default="https://cf.trackerslist.com/best.txt", max_length=4000)


class SubscriptionSortUpdate(BaseModel):
    subscription_sort: Literal["weekday", "updated", "created", "name", "rating", "pinyin"] = "updated"


class MetadataSettingsUpdate(BaseModel):
    tmdb_read_access_token: str | None = Field(default=None, max_length=2000)
    clear_tmdb_token: bool = False
    bangumi_access_token: str | None = Field(default=None, max_length=2000)
    clear_bangumi_token: bool = False
    metadata_language: str = Field(default="zh-CN", max_length=20)
    tmdb_api_base: str = Field(default="https://api.themoviedb.org", max_length=2000)
    tmdb_image_base: str = Field(default="https://image.tmdb.org", max_length=2000)
    auto_scrape_enabled: bool = True
    follow_days: int = Field(default=14, ge=1, le=3650)
    bangumi_ini_enabled: bool = False
    media_local_root: str = Field(default="", max_length=2000)
    emby_url: str = Field(default="", max_length=2000)
    emby_api_key: str | None = Field(default=None, max_length=1000)
    clear_emby_api_key: bool = False
    tmm_url: str = Field(default="", max_length=2000)
    tmm_api_key: str | None = Field(default=None, max_length=1000)
    clear_tmm_api_key: bool = False
    tmm_enabled: bool = False




class AutomationSettingsUpdate(BaseModel):
    download_enabled: bool = False
    scrape_enabled: bool = False
    daily_time: str = Field(default="02:00", max_length=5)
    timezone: str = Field(default="Asia/Shanghai", max_length=100)


class RssPollSettingsUpdate(BaseModel):
    minutes: int = Field(default=30, ge=5, le=1440)


class NotificationSettingsUpdate(BaseModel):
    enabled: bool = False
    events: list[str] = Field(default_factory=list, max_length=20)
    title_template: str = Field(default="{title}", min_length=1, max_length=1000)
    body_template: str = Field(default="{message}", min_length=1, max_length=10000)
    telegram_enabled: bool = False
    telegram_bot_token: str | None = Field(default=None, max_length=1000)
    clear_telegram_bot_token: bool = False
    telegram_chat_id: str = Field(default="", max_length=300)
    bark_enabled: bool = False
    bark_server_url: str = Field(default="https://api.day.app", max_length=4000)
    bark_device_key: str | None = Field(default=None, max_length=1000)
    clear_bark_device_key: bool = False
    bark_encryption_enabled: bool = False
    bark_encryption_algorithm: str = Field(default="AES128", pattern="^(AES128|AES192|AES256)$")
    bark_encryption_mode: str = Field(default="CBC", pattern="^(CBC|ECB|GCM)$")
    bark_encryption_padding: str = Field(default="pkcs7", pattern="^(pkcs7|noPadding)$")
    bark_encryption_key: str | None = Field(default=None, max_length=1000)
    clear_bark_encryption_key: bool = False
    webhook_enabled: bool = False
    webhook_url: str | None = Field(default=None, max_length=4000)
    clear_webhook_url: bool = False
    webhook_headers_json: str | None = Field(default=None, max_length=20000)
    clear_webhook_headers: bool = False


class NotificationPreviewRequest(BaseModel):
    event: str = Field(default="download_started", max_length=100)
    title_template: str = Field(default="{title}", min_length=1, max_length=1000)
    body_template: str = Field(default="{message}", min_length=1, max_length=10000)


class ProxySettingsUpdate(BaseModel):
    enabled: bool = False
    proxy_url: str | None = Field(default=None, max_length=2000)
    clear_proxy_url: bool = False
    no_proxy: str = Field(default="localhost,127.0.0.1,host.docker.internal", max_length=4000)


class MetadataReviewSkipRequest(BaseModel):
    skipped: bool = True


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
    rating: float = 0.0
    requested_query: str = ""
    search_query: str = ""
    search_attempts: list[str] = Field(default_factory=list)
    fallback_level: int = 0


class MetadataRecordOut(MetadataCandidateOut):
    total_episodes: int = 0
    backdrop_url: str = ""
    season: int = 1
    air_date: str = ""
    available_seasons: list[dict[str, Any]] = Field(default_factory=list)
    recommended_season: int = 1


class MetadataApplyRequest(BaseModel):
    provider: str = Field(pattern="^(tmdb|bangumi|anilist)$")
    metadata_id: int = Field(gt=0)
    media_type: str = Field(default="tv", pattern="^(tv|movie)$")
    season: int = Field(default=1, ge=0, le=999)
    season_mode: str = Field(default="title", pattern="^(manual|latest|title)$")


class ManualTrialStartRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    media_type: str = Field(default="tv", pattern="^(tv|movie)$")
    year: int = Field(default=0, ge=0, le=9999)
    season: int = Field(default=1, ge=0, le=999)
    total_episodes: int = Field(default=0, ge=0, le=10000)
    air_date: date | None = None
    rating: float = Field(default=0.0, ge=0.0, le=10.0)
    poster_url: str = Field(default="", max_length=4000)
    backdrop_url: str = Field(default="", max_length=4000)
    overview: str = Field(default="", max_length=20000)

    @field_validator("title", "poster_url", "backdrop_url", "overview")
    @classmethod
    def strip_manual_metadata_text(cls, value: str) -> str:
        return value.strip()


class MetadataSyncRequest(BaseModel):
    provider: str = Field(default="auto", pattern="^(auto|tmdb|bangumi|anilist)$")


class DiscoverySubscriptionPresetOut(BaseModel):
    name: str
    source_type: str = ""
    source_anime_id: str = ""
    canonical_key: str = ""
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
    auto_disable_when_complete: bool = False
    stale_days: int = Field(default=0, ge=0, le=3650)
    enabled: bool = True
    sample_title: str = ""
    bangumi_id: int = 0


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
    source_type: str = "mikan"
    source_anime_id: str = ""
    canonical_key: str = ""
    subject_id: int = 0
    mikan_id: int = 0
    aliases: list[str] = Field(default_factory=list)
    cover_url: str = ""
    cover_proxy_url: str = ""
    update_at: str = ""
    detail_url: str
    base_url: str
    hidden: bool = False
    subscribed: bool = False
    trialed: bool = False
    subscribed_here: bool = False
    subscribed_sources: list[str] = Field(default_factory=list)
    subscription_badge: str = ""
    available: bool = True
    action_text: str = ""


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

class SourceCatalogDetailQuery(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    subject_id: int = Field(default=0, ge=0)
    source_anime_id: str = Field(default="", max_length=120)
    mikan_id: int = Field(default=0, ge=0)
    original_title: str = Field(default="", max_length=300)
    english_title: str = Field(default="", max_length=300)
    aliases: str = Field(default="", max_length=2000)
    force_refresh: bool = Field(default=False)
