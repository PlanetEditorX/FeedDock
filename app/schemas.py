from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


_TEXT_FIELDS = (
    "name",
    "reference_title",
    "tmdb_title",
    "bgm_url",
    "primary_rss_name",
    "backup_rss_name",
    "include_keywords",
    "exclude_keywords",
    "episode_regex",
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

    save_path_template: str = "{base}/{subscription}/Season {season}"
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


class SubscriptionPreviewRequest(SubscriptionCreate):
    sample_title: str = Field(default="", max_length=1000)

    @field_validator("sample_title")
    @classmethod
    def strip_sample_title(cls, value: str) -> str:
        return value.strip()


class SubscriptionPreviewOut(BaseModel):
    parsed_episode: str = ""
    adjusted_episode: str = ""
    matched: bool
    match_reason: str
    save_path: str


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
    download_path: str = Field(default="/downloads/rss", max_length=2000)

    @field_validator("qbit_url", "qbit_username", "qbit_category", "download_path")
    @classmethod
    def strip_qbit_text(cls, value: str) -> str:
        return value.strip()
