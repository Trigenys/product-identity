import sys
import time
from contextlib import nullcontext
from dataclasses import dataclass
from typing import ContextManager, Protocol


class RateLimitExceeded(Exception):
    pass


class VerificationRateLimiter(Protocol):
    def check(self, key: str) -> None:
        ...


@dataclass
class _Window:
    started_at: float
    count: int


class InMemoryFixedWindowRateLimiter:
    """Single-process safety net.

    Production distributed enforcement belongs to the hardening milestone.
    This implementation exists so the public verification boundary already
    has an explicit, swappable rate-limit contract.
    """

    def __init__(self, *, limit: int = 120, window_seconds: int = 60) -> None:
        self._limit = limit
        self._window_seconds = window_seconds
        self._windows: dict[str, _Window] = {}
        if sys.platform == "emscripten":
            # Cloudflare Python Workers run on Pyodide where threading is
            # importable but not functional. Worker requests are already
            # serialized by the entrypoint-level asyncio lock.
            self._lock: ContextManager[None] = nullcontext()
        else:
            import threading

            self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            window = self._windows.get(key)
            if window is None or now - window.started_at >= self._window_seconds:
                self._windows[key] = _Window(started_at=now, count=1)
                return

            if window.count >= self._limit:
                raise RateLimitExceeded("Verification rate limit exceeded")

            window.count += 1
