import base64
import os
import time

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("ENCRYPTION_KEY", base64.b64encode(b"x" * 32).decode("ascii"))
os.environ.setdefault("SERVICE_API_KEYS", "mbs_test_service_key_abcdefghijklmnopqrstuvwxyz")
os.environ.setdefault("TOKEN_HASH_PEPPER", base64.b64encode(b"p" * 32).decode("ascii"))

import pytest
from fastapi import HTTPException

from app.rate_limit import InMemoryRateLimiter, RateLimitConfig


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


def test_rate_limit_evicts_empty_identity_buckets(monkeypatch):
    """Expired windows must drop their dict keys to avoid unbounded memory growth."""
    limiter = InMemoryRateLimiter(RateLimitConfig(requests=5, window_seconds=1))
    limiter.check("one-shot-a")
    limiter.check("one-shot-b")
    assert "one-shot-a" in limiter._events
    assert "one-shot-b" in limiter._events

    # Advance monotonic clock past the window so prune empties both buckets.
    base = time.monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: base + 5.0)

    limiter.check("keep-alive")
    assert "one-shot-a" not in limiter._events
    assert "one-shot-b" not in limiter._events
    assert "keep-alive" in limiter._events
