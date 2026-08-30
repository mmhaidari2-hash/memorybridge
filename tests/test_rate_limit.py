import pytest
from fastapi import HTTPException

from app.rate_limit import (
    InMemoryRateLimiter,
    RateLimitConfig,
    RedisRateLimiter,
    build_rate_limiter,
    reset_rate_limiter,
)


def test_rate_limit_returns_429_after_limit():
    limiter = InMemoryRateLimiter(RateLimitConfig(requests=2, window_seconds=60))

    limiter.check("key-a")
    limiter.check("key-a")

    with pytest.raises(HTTPException) as exc_info:
        limiter.check("key-a")

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail == "Rate limit exceeded"
    assert "Retry-After" in exc_info.value.headers


def test_rate_limit_isolated_by_service_key_identity():
    limiter = InMemoryRateLimiter(RateLimitConfig(requests=1, window_seconds=60))

    limiter.check("key-a")
    limiter.check("key-b")

    with pytest.raises(HTTPException) as exc_info:
        limiter.check("key-a")

    assert exc_info.value.status_code == 429


def test_missing_redis_url_uses_memory(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    reset_rate_limiter()
    limiter = build_rate_limiter(RateLimitConfig(requests=2, window_seconds=60))
    assert limiter.backend == "memory"
    limiter.check("key-a")


def test_leftover_redis_url_is_ignored_outside_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    monkeypatch.delenv("RATE_LIMIT_BACKEND", raising=False)
    called = {"connect": False}

    def fail_connect(url):
        called["connect"] = True
        raise AssertionError("local leftover REDIS_URL must not be contacted")

    monkeypatch.setattr("app.rate_limit._connect_redis", fail_connect)
    reset_rate_limiter()
    limiter = build_rate_limiter(RateLimitConfig(requests=2, window_seconds=60))
    assert limiter.backend == "memory"
    assert called["connect"] is False
    limiter.check("key-a")


def test_opt_in_unreachable_redis_falls_back_to_memory_outside_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("RATE_LIMIT_BACKEND", "redis")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    reset_rate_limiter()
    limiter = build_rate_limiter(RateLimitConfig(requests=2, window_seconds=60))
    assert limiter.backend == "memory"
    limiter.check("key-a")


def test_placeholder_redis_falls_back_to_memory_outside_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/change-me")
    reset_rate_limiter()
    limiter = build_rate_limiter(RateLimitConfig(requests=2, window_seconds=60))
    assert limiter.backend == "memory"


def test_unreachable_redis_fails_closed_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    reset_rate_limiter()
    with pytest.raises(RuntimeError, match="Redis is not reachable"):
        build_rate_limiter(RateLimitConfig(requests=2, window_seconds=60))


def test_placeholder_redis_fails_closed_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/change-me")
    reset_rate_limiter()
    with pytest.raises(RuntimeError, match="placeholder"):
        build_rate_limiter(RateLimitConfig(requests=2, window_seconds=60))


class _FakeRedis:
    def __init__(self, *, fail_execute=False):
        self.fail_execute = fail_execute
        self.store = {}

    def pipeline(self, transaction=True):
        return _FakePipeline(self)

    def zrange(self, key, start, end, withscores=False):
        return []


class _FakePipeline:
    def __init__(self, client):
        self.client = client
        self.ops = []

    def zremrangebyscore(self, *args):
        self.ops.append(("zrem", args))
        return self

    def zcard(self, key):
        self.ops.append(("zcard", key))
        return self

    def zadd(self, *args):
        self.ops.append(("zadd", args))
        return self

    def expire(self, *args):
        self.ops.append(("expire", args))
        return self

    def execute(self):
        if self.client.fail_execute:
            raise ConnectionError("redis down")
        if self.ops and self.ops[0][0] == "zrem":
            return [0, 0]
        return [1, True]


def test_reachable_redis_is_selected(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("RATE_LIMIT_BACKEND", "redis")
    monkeypatch.setenv("REDIS_URL", "redis://cache.internal:6379/0")
    monkeypatch.setattr("app.rate_limit._connect_redis", lambda url: fake)
    reset_rate_limiter()
    limiter = build_rate_limiter(RateLimitConfig(requests=2, window_seconds=60))
    assert limiter.backend == "redis"
    limiter.check("key-a")
    limiter.check("key-a")


def test_redis_runtime_failure_uses_memory_outside_production():
    limiter = RedisRateLimiter(
        RateLimitConfig(requests=1, window_seconds=60),
        _FakeRedis(fail_execute=True),
        allow_memory_fallback=True,
    )
    limiter.check("key-a")
    with pytest.raises(HTTPException) as exc_info:
        limiter.check("key-a")
    assert exc_info.value.status_code == 429


def test_redis_runtime_failure_fails_closed_in_production():
    limiter = RedisRateLimiter(
        RateLimitConfig(requests=1, window_seconds=60),
        _FakeRedis(fail_execute=True),
        allow_memory_fallback=False,
    )
    with pytest.raises(HTTPException) as exc_info:
        limiter.check("key-a")
    assert exc_info.value.status_code == 503
