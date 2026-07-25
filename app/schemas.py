from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class SubscriptionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    rss_url: HttpUrl
    include_keywords: str = ""
    exclude_keywords: str = ""
    episode_regex: str = ""
    save_path_template: str = "{base}/{subscription}"
    enabled: bool = True

    @field_validator("name", "include_keywords", "exclude_keywords", "episode_regex", "save_path_template")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class SubscriptionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    rss_url: HttpUrl | None = None
    include_keywords: str | None = None
    exclude_keywords: str | None = None
    episode_regex: str | None = None
    save_path_template: str | None = None
    enabled: bool | None = None


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    rss_url: str
    include_keywords: str
    exclude_keywords: str
    episode_regex: str
    save_path_template: str
    enabled: bool
    created_at: datetime
    updated_at: datetime
    last_checked_at: datetime | None
    last_error: str


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
