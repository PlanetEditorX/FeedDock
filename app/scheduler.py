from __future__ import annotations

import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from .anime_catalog import refresh_due_anime_catalogs
from .database import SessionLocal
from .debug_logging import log_exception
from .mikan_cache import refresh_due_mikan_catalogs
from .postprocess import normalize_pending_items
from .rss_service import dispatch_scheduled_downloads, refresh_all
from .runtime_config import load_automation_config, load_rss_poll_config, mark_automation_run
from .settings_config import load_application_preferences


class PollScheduler:
    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="feeddock-scheduler", daemon=True)
        self._thread.start()

    @staticmethod
    def run_daily_automation(*, force: bool = False) -> dict[str, object]:
        with SessionLocal() as db:
            config = load_automation_config(db)
            timezone = ZoneInfo(config.timezone)
            local_now = datetime.now(timezone)
            local_date = local_now.date().isoformat()
            current_time = local_now.strftime("%H:%M")
            if not force:
                if not config.enabled or current_time < config.daily_time or config.last_run_date == local_date:
                    return {"ok": True, "ran": False, "message": "尚未到统一执行时间或今日已执行"}
            result: dict[str, object] = {"ok": True, "ran": True, "date": local_date}
            if config.download_enabled:
                result["downloads"] = dispatch_scheduled_downloads(db, limit=1000)
            result["completion"] = normalize_pending_items(db, limit=500)
            mark_automation_run(db, local_date)
            return result

    def _run(self) -> None:
        if self._stop_event.wait(10):
            return
        last_rss_refresh: float | None = None
        next_completion_check = 0.0
        while not self._stop_event.is_set():
            now = time.monotonic()
            with SessionLocal() as db:
                poll_interval = load_rss_poll_config(db).minutes
                rss_enabled = load_application_preferences(db).rss.enabled
            rss_due = rss_enabled and (last_rss_refresh is None or now - last_rss_refresh >= poll_interval * 60)
            if rss_due:
                try:
                    refresh_all()
                except Exception as exc:
                    log_exception("后台 RSS 刷新异常", exc, stage="scheduler.refresh-all")
                last_rss_refresh = time.monotonic()

            if now >= next_completion_check:
                try:
                    with SessionLocal() as db:
                        dispatch_scheduled_downloads(db, limit=100, include_daily=False)
                        normalize_pending_items(db, limit=100)
                except Exception as exc:
                    log_exception("后台下载完成检查异常", exc, stage="scheduler.normalize-pending")
                next_completion_check = time.monotonic() + 120

            try:
                self.run_daily_automation()
            except Exception as exc:
                log_exception("每日自动任务异常", exc, stage="scheduler.daily-automation")

            try:
                refresh_due_mikan_catalogs()
            except Exception as exc:
                log_exception("Mikan 后台缓存刷新异常", exc, stage="scheduler.mikan-refresh")

            try:
                refresh_due_anime_catalogs()
            except Exception as exc:
                log_exception("多站点番剧周历后台刷新异常", exc, stage="scheduler.anime-catalog-refresh")

            next_rss_refresh = (last_rss_refresh or time.monotonic()) + poll_interval * 60
            next_event = min(next_rss_refresh, next_completion_check)
            wait_seconds = max(1.0, next_event - time.monotonic())
            if self._stop_event.wait(min(60.0, wait_seconds)):
                return

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)


scheduler = PollScheduler()


def start_scheduler() -> None:
    scheduler.start()


def stop_scheduler() -> None:
    scheduler.stop()
