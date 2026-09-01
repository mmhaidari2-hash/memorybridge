import hashlib
import hmac
import os
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import FrozenSet, Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import ApiKey, Workspace
from app.rate_limit import rate_limiter


@dataclass(frozen=True)
class ServiceAuthContext:
    key_hash: str
    source: str
    workspace_id: Optional[str] = None
    tenant_id: Optional[str] = None


@lru_cache(maxsize=1)
def get_legacy_service_key_hashes() -> FrozenSet[str]:
    raw = os.getenv("SERVICE_API_KEYS", "")
    keys = [item.strip() for item in raw.split(",") if item.strip()]
    return frozenset(hashlib.sha256(key.encode("utf-8")).hexdigest() for key in keys)


def _authenticate_database_key(db: Session, supplied_hash: str) -> Optional[ServiceAuthContext]:
    api_key = (
        db.query(ApiKey)
        .options(joinedload(ApiKey.workspace).joinedload(Workspace.tenant))
        .filter(ApiKey.key_hash == supplied_hash, ApiKey.is_active.is_(True))
        .one_or_none()
    )
    if api_key is None:
        return None

    workspace = api_key.workspace
    tenant = workspace.tenant if workspace else None
    if workspace is None or tenant is None or tenant.status != "active":
        return None

    api_key.last_used_at = datetime.utcnow()
    db.commit()

    return ServiceAuthContext(
        key_hash=supplied_hash,
        source="database",
        workspace_id=workspace.id,
        tenant_id=tenant.id,
    )


def _authenticate_legacy_key(supplied_hash: str) -> Optional[ServiceAuthContext]:
    valid = any(
        hmac.compare_digest(supplied_hash, expected_hash)
        for expected_hash in get_legacy_service_key_hashes()
    )
    if not valid:
        return None

    return ServiceAuthContext(key_hash=supplied_hash, source="legacy_env")


def verify_service_api_key(
    x_memorybridge_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> ServiceAuthContext:
    if not x_memorybridge_key:
        raise HTTPException(status_code=401, detail="Missing service API key")

    supplied_hash = hashlib.sha256(x_memorybridge_key.encode("utf-8")).hexdigest()

    context = _authenticate_database_key(db, supplied_hash)
    if context is None:
        context = _authenticate_legacy_key(supplied_hash)

    if context is None:
        raise HTTPException(status_code=401, detail="Invalid service API key")

    rate_limiter.check(supplied_hash)
    return context
