from __future__ import annotations

import threading

from .config import settings
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
        self._thread = threading.Thread(target=self._run, name="rss-poll-scheduler", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        # Give the API time to finish startup, then perform an initial refresh.
        if self._stop_event.wait(10):
            return
        while not self._stop_event.is_set():
            refresh_all()
            if self._stop_event.wait(settings.poll_interval_minutes * 60):
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
