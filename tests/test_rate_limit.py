import base64
import os

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
