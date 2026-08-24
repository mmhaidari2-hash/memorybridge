import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Dict

from fastapi import HTTPException


@dataclass(frozen=True)
class RateLimitConfig:
    requests: int
    window_seconds: int


class InMemoryRateLimiter:
    """Process-local sliding-window limiter.

    This backend is intentionally isolated behind a small interface so it can
    later be replaced by Redis without changing the public API contract.
    """

    def __init__(self, config: RateLimitConfig):
        self.config = config
        self._events: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, identity: str) -> None:
        now = time.monotonic()
        cutoff = now - self.config.window_seconds

        with self._lock:
            bucket = self._events[identity]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            if len(bucket) >= self.config.requests:
                retry_after = max(1, int(self.config.window_seconds - (now - bucket[0])))
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit exceeded",
                    headers={"Retry-After": str(retry_after)},
                )

            bucket.append(now)


def get_rate_limit_config() -> RateLimitConfig:
    raw_requests = os.getenv("RATE_LIMIT_REQUESTS", "120")
    raw_window = os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60")

    try:
        requests = int(raw_requests)
        window_seconds = int(raw_window)
    except ValueError as exc:
        raise RuntimeError("Rate limit settings must be integers") from exc

    if requests <= 0 or window_seconds <= 0:
        raise RuntimeError("Rate limit settings must be positive")

    return RateLimitConfig(requests=requests, window_seconds=window_seconds)


rate_limiter = InMemoryRateLimiter(get_rate_limit_config())
