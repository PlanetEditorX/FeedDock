from __future__ import annotations

import os
import signal
import time


def terminate_process(*, restart: bool) -> None:
    """Terminate FeedDock after the HTTP response has been sent.

    Docker/Compose decides whether the container returns. With the documented
    ``restart: unless-stopped`` policy both actions may restart the container;
    a real container stop must still be performed by the host orchestrator.
    """

    time.sleep(0.4)
    if restart:
        os._exit(75)
    os.kill(os.getpid(), signal.SIGTERM)
