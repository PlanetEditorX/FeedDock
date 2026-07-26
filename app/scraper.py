from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from .models import Subscription


@dataclass(slots=True)
class ScrapeResult:
    ok: bool
    message: str
    local_path: str = ""
    files: list[str] | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "message": self.message,
            "local_path": self.local_path,
            "files": self.files or [],
        }


def _removed(message: str, *, ok: bool = True) -> ScrapeResult:
    return ScrapeResult(ok, message)


def scrape_local_metadata(db: Session, subscription: Subscription) -> ScrapeResult:
    return _removed("FeedDock 已移除本地 NFO/图片刮削功能，请交由外部媒体库识别")


def trigger_tmm_scrape(db: Session, subscription: Subscription) -> ScrapeResult:
    return _removed("FeedDock 已移除 tinyMediaManager 刮削功能，请交由外部媒体库识别", ok=False)


def scrape_subscription(db: Session, subscription: Subscription) -> ScrapeResult:
    return _removed("FeedDock 已移除刮削功能，请交由外部媒体库识别")


def test_tmm_connection(db: Session) -> ScrapeResult:
    return _removed("FeedDock 已移除 tinyMediaManager 配置与测试入口", ok=False)


def refresh_emby_library(db: Session) -> ScrapeResult:
    return _removed("FeedDock 已移除媒体库刷新入口，请在外部媒体库中自动识别", ok=False)
