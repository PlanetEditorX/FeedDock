from __future__ import annotations

import threading
import time

from .config import settings
from .mikan_cache import refresh_due_mikan_catalogs
from .postprocess import normalize_pending_items
from .rss_service import refresh_all


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

    def _run(self) -> None:
        if self._stop_event.wait(10):
            return
        next_rss_refresh = 0.0
        next_rename_check = 0.0
        while not self._stop_event.is_set():
            now = time.monotonic()
            if now >= next_rss_refresh:
                try:
                    refresh_all()
                except Exception:
                    pass
                next_rss_refresh = time.monotonic() + settings.poll_interval_minutes * 60

            if now >= next_rename_check:
                try:
                    normalize_pending_items(limit=50)
                except Exception:
                    pass
                next_rename_check = time.monotonic() + 120

            try:
                refresh_due_mikan_catalogs()
            except Exception:
                pass

            next_event = min(next_rss_refresh, next_rename_check)
            wait_seconds = max(1.0, next_event - time.monotonic())
            if self._stop_event.wait(min(600.0, wait_seconds)):
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
