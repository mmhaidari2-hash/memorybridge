import logging
import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Dict, Protocol
from urllib.parse import urlparse

from fastapi import HTTPException


logger = logging.getLogger("memorybridge.rate_limit")
_PLACEHOLDER_MARKERS = ("REPLACE", "change-me", "example.com")
_cached_limiter = None


@dataclass(frozen=True)
class RateLimitConfig:
    requests: int
    window_seconds: int


class RateLimiter(Protocol):
    def check(self, identity: str) -> None: ...


class InMemoryRateLimiter:
    """Process-local sliding-window limiter."""

    backend = "memory"

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


class RedisRateLimiter:
    """Distributed sliding-window limiter backed by Redis sorted sets."""

    backend = "redis"

    def __init__(self, config: RateLimitConfig, client, *, allow_memory_fallback: bool):
        self.config = config
        self._client = client
        self._allow_memory_fallback = allow_memory_fallback
        self._fallback = InMemoryRateLimiter(config)

    def check(self, identity: str) -> None:
        now = time.time()
        cutoff = now - self.config.window_seconds
        key = f"mb:rl:{identity}"
        try:
            pipe = self._client.pipeline(True)
            pipe.zremrangebyscore(key, 0, cutoff)
            pipe.zcard(key)
            _removed, count = pipe.execute()
            if int(count or 0) >= self.config.requests:
                oldest = self._client.zrange(key, 0, 0, withscores=True)
                oldest_score = oldest[0][1] if oldest else now
                retry_after = max(1, int(self.config.window_seconds - (now - oldest_score)))
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit exceeded",
                    headers={"Retry-After": str(retry_after)},
                )
            pipe = self._client.pipeline(True)
            pipe.zadd(key, {f"{now}": now})
            pipe.expire(key, self.config.window_seconds)
            pipe.execute()
        except HTTPException:
            raise
        except Exception:
            if not self._allow_memory_fallback:
                logger.warning("rate_limit_backend_unavailable backend=redis")
                raise HTTPException(status_code=503, detail="Rate limit backend unavailable")
            logger.warning("rate_limit_redis_unavailable backend=memory")
            self._fallback.check(identity)


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


def _is_production() -> bool:
    return os.getenv("APP_ENV", "").strip().lower() == "production"


def _redis_url() -> str:
    return os.getenv("REDIS_URL", "").strip()


def _backend_override() -> str:
    return os.getenv("RATE_LIMIT_BACKEND", "").strip().lower()


def _is_placeholder(value: str) -> bool:
    return any(marker.lower() in value.lower() for marker in _PLACEHOLDER_MARKERS)


def _should_use_redis(url: str) -> bool:
    """Honor leftover REDIS_URL only when Redis is explicitly wanted.

    Local/development defaults to process memory so a shell REDIS_URL from
    another project does not have to be unset. Production uses Redis when
    REDIS_URL is set. RATE_LIMIT_BACKEND=redis opts in; =memory forces memory.
    """
    override = _backend_override()
    if override == "memory":
        return False
    if override == "redis":
        return True
    if override:
        raise RuntimeError("RATE_LIMIT_BACKEND must be 'memory' or 'redis'")
    return _is_production() and bool(url)


def _safe_redis_host(url: str) -> str:
    try:
        parsed = urlparse(url)
        return parsed.hostname or "unspecified"
    except Exception:
        return "unspecified"


def _connect_redis(url: str):
    try:
        import redis
    except ImportError as exc:
        raise RuntimeError("REDIS_URL is set but the redis package is not installed") from exc

    client = redis.Redis.from_url(url, socket_connect_timeout=0.4, socket_timeout=0.4)
    client.ping()
    return client


def build_rate_limiter(config: RateLimitConfig | None = None) -> RateLimiter:
    """Select Redis when it is usable; otherwise use process memory.

    Local/development never requires unsetting REDIS_URL. An unset, placeholder,
    or unreachable Redis target falls back to in-memory. Production fails closed
    if REDIS_URL is set to a placeholder or an unreachable host.
    """
    config = config or get_rate_limit_config()
    url = _redis_url()
    if not _should_use_redis(url):
        return InMemoryRateLimiter(config)

    if not url:
        if _is_production() or _backend_override() == "redis":
            raise RuntimeError("RATE_LIMIT_BACKEND=redis requires REDIS_URL")
        return InMemoryRateLimiter(config)

    if _is_placeholder(url):
        if _is_production():
            raise RuntimeError("REDIS_URL still contains a placeholder value")
        logger.warning("rate_limit_redis_ignored reason=placeholder backend=memory")
        return InMemoryRateLimiter(config)

    try:
        client = _connect_redis(url)
    except Exception:
        if _is_production():
            logger.warning("rate_limit_redis_unavailable host=%s", _safe_redis_host(url))
            raise RuntimeError("REDIS_URL is set but Redis is not reachable")
        logger.warning(
            "rate_limit_redis_unavailable host=%s backend=memory",
            _safe_redis_host(url),
        )
        return InMemoryRateLimiter(config)

    logger.info("rate_limit_backend=redis host=%s", _safe_redis_host(url))
    return RedisRateLimiter(config, client, allow_memory_fallback=not _is_production())


def reset_rate_limiter() -> None:
    global _cached_limiter
    _cached_limiter = None


def get_rate_limiter() -> RateLimiter:
    global _cached_limiter
    if _cached_limiter is None:
        _cached_limiter = build_rate_limiter()
    return _cached_limiter


class _RateLimiterProxy:
    def check(self, identity: str) -> None:
        get_rate_limiter().check(identity)


rate_limiter = _RateLimiterProxy()
