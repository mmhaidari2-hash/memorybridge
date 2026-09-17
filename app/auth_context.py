"""Authenticated service identity attached to each protected request."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AuthContext:
    tenant_id: str
    tenant_slug: str
    key_source: str  # "env" | "db"
    key_id: str | None
    key_hash: str
    key_prefix: str | None
