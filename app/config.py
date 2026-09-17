"""Centralized runtime configuration with fail-closed validation."""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, FrozenSet, Tuple


@dataclass(frozen=True)
class EncryptionKeyring:
    """Versioned AES-256 keys. New writes use active_version; reads use stored version."""

    keys: Dict[int, bytes]
    active_version: int

    def get(self, version: int) -> bytes:
        try:
            return self.keys[version]
        except KeyError as exc:
            raise RuntimeError(f"Unknown encryption key version: {version}") from exc


@dataclass(frozen=True)
class RateLimitSettings:
    requests: int
    window_seconds: int


@dataclass(frozen=True)
class Settings:
    database_url: str
    keyring: EncryptionKeyring
    env_service_key_hashes: FrozenSet[str]
    admin_api_key_hash: str | None
    token_hash_pepper: bytes
    rate_limit: RateLimitSettings
    default_tenant_slug: str
    max_request_bytes: int
    metrics_enabled: bool


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value or not value.strip():
        raise RuntimeError(f"{name} is required")
    return value.strip()


def _parse_database_url() -> str:
    database_url = _require("DATABASE_URL")
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    return database_url


def _decode_aes_key(raw: str, source: str) -> bytes:
    try:
        key = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise RuntimeError(f"{source} must be valid base64") from exc
    if len(key) != 32:
        raise RuntimeError(f"{source} must decode to exactly 32 bytes")
    return key


def _parse_keyring() -> EncryptionKeyring:
    """
    Accept either:
      ENCRYPTION_KEY=<base64>                 → version 1
      ENCRYPTION_KEYS=1:<b64>,2:<b64>         → multi-version
      ENCRYPTION_ACTIVE_VERSION=2             → write version (default: max)
    """
    multi = os.getenv("ENCRYPTION_KEYS", "").strip()
    keys: Dict[int, bytes] = {}

    if multi:
        for part in multi.split(","):
            part = part.strip()
            if not part:
                continue
            if ":" not in part:
                raise RuntimeError("ENCRYPTION_KEYS entries must be version:base64")
            version_raw, key_raw = part.split(":", 1)
            try:
                version = int(version_raw)
            except ValueError as exc:
                raise RuntimeError("ENCRYPTION_KEYS versions must be integers") from exc
            if version < 1:
                raise RuntimeError("ENCRYPTION_KEYS versions must be >= 1")
            if version in keys:
                raise RuntimeError(f"Duplicate ENCRYPTION_KEYS version: {version}")
            keys[version] = _decode_aes_key(key_raw.strip(), f"ENCRYPTION_KEYS[{version}]")
    else:
        keys[1] = _decode_aes_key(_require("ENCRYPTION_KEY"), "ENCRYPTION_KEY")

    if not keys:
        raise RuntimeError("At least one encryption key is required")

    active_raw = os.getenv("ENCRYPTION_ACTIVE_VERSION", "").strip()
    if active_raw:
        try:
            active_version = int(active_raw)
        except ValueError as exc:
            raise RuntimeError("ENCRYPTION_ACTIVE_VERSION must be an integer") from exc
        if active_version not in keys:
            raise RuntimeError("ENCRYPTION_ACTIVE_VERSION must exist in the keyring")
    else:
        active_version = max(keys)

    return EncryptionKeyring(keys=keys, active_version=active_version)


def _hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _parse_env_service_keys() -> FrozenSet[str]:
    raw = os.getenv("SERVICE_API_KEYS", "").strip()
    keys = [item.strip() for item in raw.split(",") if item.strip()]
    if not keys:
        raise RuntimeError("SERVICE_API_KEYS is required for bootstrap authentication")
    for key in keys:
        if len(key) < 24:
            raise RuntimeError("SERVICE_API_KEYS entries must be at least 24 characters")
    return frozenset(_hash_api_key(key) for key in keys)


def _parse_admin_key() -> str | None:
    raw = os.getenv("ADMIN_API_KEY", "").strip()
    if not raw:
        return None
    if len(raw) < 32:
        raise RuntimeError("ADMIN_API_KEY must be at least 32 characters")
    return _hash_api_key(raw)


def _parse_pepper() -> bytes:
    """
    Optional HMAC pepper for credential hashing.
    If unset, derive a deterministic non-secret fallback from ENCRYPTION material so
    hashes remain stable in development — production should set TOKEN_HASH_PEPPER.
    """
    raw = os.getenv("TOKEN_HASH_PEPPER", "").strip()
    if raw:
        try:
            pepper = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise RuntimeError("TOKEN_HASH_PEPPER must be valid base64") from exc
        if len(pepper) < 16:
            raise RuntimeError("TOKEN_HASH_PEPPER must decode to at least 16 bytes")
        return pepper

    # Dev fallback: not a substitute for a dedicated pepper in production.
    keyring = _parse_keyring()
    material = keyring.get(keyring.active_version)
    return hashlib.sha256(b"memorybridge-dev-pepper:" + material).digest()


def _parse_rate_limit() -> RateLimitSettings:
    try:
        requests = int(os.getenv("RATE_LIMIT_REQUESTS", "120"))
        window_seconds = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
    except ValueError as exc:
        raise RuntimeError("Rate limit settings must be integers") from exc
    if requests <= 0 or window_seconds <= 0:
        raise RuntimeError("Rate limit settings must be positive")
    return RateLimitSettings(requests=requests, window_seconds=window_seconds)


def _parse_max_request_bytes() -> int:
    try:
        value = int(os.getenv("MAX_REQUEST_BYTES", "262144"))
    except ValueError as exc:
        raise RuntimeError("MAX_REQUEST_BYTES must be an integer") from exc
    if value < 1024:
        raise RuntimeError("MAX_REQUEST_BYTES must be at least 1024")
    return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        database_url=_parse_database_url(),
        keyring=_parse_keyring(),
        env_service_key_hashes=_parse_env_service_keys(),
        admin_api_key_hash=_parse_admin_key(),
        token_hash_pepper=_parse_pepper(),
        rate_limit=_parse_rate_limit(),
        default_tenant_slug=os.getenv("DEFAULT_TENANT_SLUG", "default").strip() or "default",
        max_request_bytes=_parse_max_request_bytes(),
        metrics_enabled=os.getenv("METRICS_ENABLED", "true").strip().lower()
        not in {"0", "false", "no"},
    )


def clear_settings_cache() -> None:
    get_settings.cache_clear()


def hash_service_api_key(key: str) -> str:
    return _hash_api_key(key)


def api_key_prefix(key: str) -> str:
    """Non-secret prefix for operator identification (never sufficient for auth)."""
    return key[:12] if len(key) >= 12 else key
