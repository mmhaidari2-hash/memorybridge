import logging
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional, Protocol

from fastapi import HTTPException

from app.config import get_settings

logger = logging.getLogger("memorybridge.rate_limit")


@dataclass(frozen=True)
class RateLimitConfig:
    requests: int
    window_seconds: int


class RateLimiter(Protocol):
    def check(self, identity: str) -> None: ...

    def reset(self) -> None: ...


class InMemoryRateLimiter:
    """Process-local sliding-window limiter (dev/tests only).

    Not safe across multiple workers/instances — use RedisRateLimiter in prod.
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

            if not bucket:
                self._events.pop(identity, None)
                bucket = self._events[identity]

            if len(bucket) >= self.config.requests:
                retry_after = max(1, int(self.config.window_seconds - (now - bucket[0])))
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit exceeded",
                    headers={"Retry-After": str(retry_after)},
                )

            bucket.append(now)
            self._gc_expired_buckets(cutoff)

    def _gc_expired_buckets(self, cutoff: float) -> None:
        stale: list[str] = []
        for key, dq in self._events.items():
            while dq and dq[0] <= cutoff:
                dq.popleft()
            if not dq:
                stale.append(key)
        for key in stale:
            self._events.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


class RedisRateLimiter:
    """Shared sliding-window limiter via Redis sorted sets.

    Safe across multiple app workers/instances (Railway, etc.).
    """

    def __init__(self, config: RateLimitConfig, redis_client):
        self.config = config
        self._redis = redis_client

    def check(self, identity: str) -> None:
        key = f"mb:rl:{identity}"
        now = time.time()
        window = self.config.window_seconds
        cutoff = now - window
        member = f"{now}:{threading.get_ident()}:{id(self)}"

        pipe = self._redis.pipeline()
        pipe.zremrangebyscore(key, 0, cutoff)
        pipe.zcard(key)
        pipe.zadd(key, {member: now})
        pipe.expire(key, window + 1)
        _, count, _, _ = pipe.execute()

        # count is before this request's ZADD
        if count >= self.config.requests:
            # Undo the optimistic add when over limit.
            self._redis.zrem(key, member)
            oldest = self._redis.zrange(key, 0, 0, withscores=True)
            if oldest:
                retry_after = max(1, int(window - (now - oldest[0][1])))
            else:
                retry_after = window
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(retry_after)},
            )

    def reset(self) -> None:
        for key in self._redis.scan_iter(match="mb:rl:*"):
            self._redis.delete(key)


def get_rate_limit_config() -> RateLimitConfig:
    settings = get_settings()
    return RateLimitConfig(
        requests=settings.rate_limit.requests,
        window_seconds=settings.rate_limit.window_seconds,
    )


def build_rate_limiter() -> RateLimiter:
    settings = get_settings()
    config = get_rate_limit_config()
    redis_url = settings.redis_url
    if redis_url:
        try:
            import redis

            client = redis.Redis.from_url(redis_url, decode_responses=True)
            client.ping()
            logger.info("rate_limiter_backend=redis")
            return RedisRateLimiter(config, client)
        except Exception:
            logger.exception(
                "redis_rate_limiter_unavailable_falling_back_to_memory url=%s",
                redis_url,
            )

    logger.warning(
        "rate_limiter_backend=memory "
        "(set REDIS_URL for multi-worker / multi-instance production safety)"
    )
    return InMemoryRateLimiter(config)


# Constructed at import once settings env is available.
rate_limiter: RateLimiter = build_rate_limiter()
