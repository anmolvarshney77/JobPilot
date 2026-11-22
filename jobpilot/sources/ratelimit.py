from __future__ import annotations

import threading
import time
from urllib.parse import urlparse


class HostRateLimiter:
    """1 req/sec per host, thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_request: dict[str, float] = {}

    def wait(self, url: str) -> None:
        host = urlparse(url).netloc
        with self._lock:
            last = self._last_request.get(host, 0.0)
            now = time.monotonic()
            elapsed = now - last
            if elapsed < 1.0:
                time.sleep(1.0 - elapsed)
            self._last_request[host] = time.monotonic()
