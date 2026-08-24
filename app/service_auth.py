import hashlib
import hmac
import os
from functools import lru_cache
from typing import FrozenSet

from fastapi import Header, HTTPException

from app.rate_limit import rate_limiter


@lru_cache(maxsize=1)
def get_service_key_hashes() -> FrozenSet[str]:
    raw = os.getenv("SERVICE_API_KEYS", "")
    keys = [item.strip() for item in raw.split(",") if item.strip()]
    if not keys:
        raise RuntimeError("SERVICE_API_KEYS is required")

    return frozenset(hashlib.sha256(key.encode("utf-8")).hexdigest() for key in keys)


def verify_service_api_key(x_memorybridge_key: str | None = Header(default=None)) -> str:
    if not x_memorybridge_key:
        raise HTTPException(status_code=401, detail="Missing service API key")

    supplied_hash = hashlib.sha256(x_memorybridge_key.encode("utf-8")).hexdigest()
    valid = any(
        hmac.compare_digest(supplied_hash, expected_hash)
        for expected_hash in get_service_key_hashes()
    )
    if not valid:
        raise HTTPException(status_code=401, detail="Invalid service API key")

    rate_limiter.check(supplied_hash)
    return supplied_hash
