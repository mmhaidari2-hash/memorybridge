import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Dict

from fastapi import HTTPException

from app.config import get_settings


@dataclass(frozen=True)
class RateLimitConfig:
    requests: int
    window_seconds: int


class InMemoryRateLimiter:
    """Process-local sliding-window limiter.

    Isolated behind a small interface so it can later be replaced by Redis
    without changing the public API contract.
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

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


def get_rate_limit_config() -> RateLimitConfig:
    settings = get_settings()
    return RateLimitConfig(
        requests=settings.rate_limit.requests,
        window_seconds=settings.rate_limit.window_seconds,
    )


def build_rate_limiter() -> InMemoryRateLimiter:
    return InMemoryRateLimiter(get_rate_limit_config())


# Constructed at import once settings env is available.
rate_limiter = build_rate_limiter()
