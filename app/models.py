from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AdminAccount(Base):
    __tablename__ = "admin_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    session_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    source_anime_id: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    canonical_key: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    # Trial subscriptions retain their RSS identity but stop after one episode.
    subscription_mode: Mapped[str] = mapped_column(String(20), default="subscribed", nullable=False)
    trial_bulk: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Metadata used to identify and organize a title. These fields are optional
    # and do not call third-party metadata APIs by themselves.
    reference_title: Mapped[str] = mapped_column(Text, default="", nullable=False)
    tmdb_title: Mapped[str] = mapped_column(Text, default="", nullable=False)
    bgm_url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    air_date: Mapped[str] = mapped_column(String(10), default="", nullable=False)
    season: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    season_mode: Mapped[str] = mapped_column(String(20), default="title", nullable=False)

    # rss_url remains the primary URL for backward compatibility.
    primary_rss_name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    rss_url: Mapped[str] = mapped_column(Text, nullable=False)
    backup_rss_name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    backup_rss_url: Mapped[str] = mapped_column(Text, default="", nullable=False)

    include_keywords: Mapped[str] = mapped_column(Text, default="", nullable=False)
    exclude_keywords: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # episode_group=0 means the entire custom regex match; 1 means the first
    # capture group. Invalid group indexes safely fall back to the first usable
    # value.
    episode_regex: Mapped[str] = mapped_column(Text, default="", nullable=False)
    episode_group: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    episode_offset: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_episodes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_episodes_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    total_episodes_source: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    total_episodes_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Metadata matching and Emby-friendly naming. Existing installations are
    # migrated additively in database.ensure_schema().
    naming_mode: Mapped[str] = mapped_column(String(20), default="auto", nullable=False)
    media_type: Mapped[str] = mapped_column(String(20), default="tv", nullable=False)
    manual_title: Mapped[str] = mapped_column(Text, default="", nullable=False)
    tmdb_id: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bangumi_id: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    anilist_id: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metadata_year: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metadata_rating: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    metadata_source: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    metadata_overview: Mapped[str] = mapped_column(Text, default="", nullable=False)
    poster_url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    backdrop_url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    metadata_last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    auto_metadata: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    metadata_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    metadata_review_skipped: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    rename_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    file_name_template: Mapped[str] = mapped_column(
        Text, default="{title} - S{season:02}E{episode:02}", nullable=False
    )
    scrape_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    scrape_mode: Mapped[str] = mapped_column(String(20), default="off", nullable=False)

    save_path_template: Mapped[str] = mapped_column(
        Text,
        default="{base}/{media_folder}/Season {season:02}",
        nullable=False,
    )
    custom_download_path: Mapped[str] = mapped_column(Text, default="", nullable=False)
    missing_detection: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    only_latest: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    auto_disable_when_complete: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    stale_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_new_item_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_stale_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completion_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_missing_signature: Mapped[str] = mapped_column(Text, default="", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)

    items: Mapped[list[FeedItem]] = relationship(
        back_populates="subscription",
        cascade="all, delete-orphan",
    )


class FeedItem(Base):
    __tablename__ = "feed_items"
    __table_args__ = (
        UniqueConstraint("subscription_id", "fingerprint", name="uq_feed_item_fingerprint"),
        Index("ix_feed_items_created_at", "created_at"),
        Index("ix_feed_items_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subscription_id: Mapped[int] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    guid: Mapped[str] = mapped_column(Text, default="", nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    download_url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source_url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    episode: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="discovered", nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    save_path: Mapped[str] = mapped_column(Text, default="", nullable=False)
    desired_name: Mapped[str] = mapped_column(Text, default="", nullable=False)
    qbit_tag: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    torrent_hash: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    rename_status: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    rename_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    download_progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scrape_status: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    scrape_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    scraped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trackers_status: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    trackers_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    trackers_applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    qbit_record_removed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    qbit_record_remove_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    subscription: Mapped[Subscription] = relationship(back_populates="items")


class SystemLog(Base):
    __tablename__ = "system_logs"
    __table_args__ = (Index("ix_system_logs_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    level: Mapped[str] = mapped_column(String(16), default="INFO", nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AnimePreference(Base):
    __tablename__ = "anime_preferences"

    canonical_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    bangumi_id: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    title_normalized: Mapped[str] = mapped_column(String(255), default="", nullable=False, index=True)
    hidden: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class MikanCacheEntry(Base):
    __tablename__ = "mikan_cache_entries"
    __table_args__ = (
        Index("ix_mikan_cache_entries_kind_fetched_at", "kind", "fetched_at"),
    )

    cache_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    params_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
