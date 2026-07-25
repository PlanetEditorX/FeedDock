from __future__ import annotations

import threading
import time

from .config import settings
from .mikan_cache import refresh_due_mikan_catalogs
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
        # Give the API time to finish startup. Mikan due-cache checks run at
        # least every 10 minutes and are independent of the RSS poll interval.
        if self._stop_event.wait(10):
            return
        next_rss_refresh = 0.0
        while not self._stop_event.is_set():
            now = time.monotonic()
            if now >= next_rss_refresh:
                try:
                    refresh_all()
                except Exception:
                    # A transient RSS failure must not stop future runs.
                    pass
                next_rss_refresh = time.monotonic() + settings.poll_interval_minutes * 60

            try:
                refresh_due_mikan_catalogs()
            except Exception:
                # Cache refresh failures are recorded per entry and retried later.
                pass

            seconds_until_rss = max(1.0, next_rss_refresh - time.monotonic())
            if self._stop_event.wait(min(600.0, seconds_until_rss)):
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
