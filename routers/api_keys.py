import hashlib
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ApiKey
from app.service_auth import ServiceAuthContext, verify_service_api_key

router = APIRouter(tags=["API Keys"])


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ApiKeyCreated(BaseModel):
    id: str
    name: str
    key_prefix: str
    api_key: str
    created_at: datetime


class ApiKeyView(BaseModel):
    id: str
    name: str
    key_prefix: str
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


def require_workspace(auth: ServiceAuthContext) -> str:
    if auth.workspace_id is None:
        raise HTTPException(status_code=403, detail="Workspace API key required")
    return auth.workspace_id


@router.post("/api-keys", response_model=ApiKeyCreated, status_code=201)
def create_api_key(
    payload: ApiKeyCreate,
    db: Session = Depends(get_db),
    auth: ServiceAuthContext = Depends(verify_service_api_key),
):
    workspace_id = require_workspace(auth)
    plaintext = f"mbs_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
    key = ApiKey(
        workspace_id=workspace_id,
        name=payload.name,
        key_prefix=plaintext[:12],
        key_hash=key_hash,
    )
    db.add(key)
    db.commit()
    db.refresh(key)
    return ApiKeyCreated(
        id=key.id,
        name=key.name,
        key_prefix=key.key_prefix,
        api_key=plaintext,
        created_at=key.created_at,
    )


@router.get("/api-keys", response_model=list[ApiKeyView])
def list_api_keys(
    db: Session = Depends(get_db),
    auth: ServiceAuthContext = Depends(verify_service_api_key),
):
    workspace_id = require_workspace(auth)
    return (
        db.query(ApiKey)
        .filter(ApiKey.workspace_id == workspace_id)
        .order_by(ApiKey.created_at.desc())
        .all()
    )


@router.delete("/api-keys/{key_id}", status_code=204)
def revoke_api_key(
    key_id: str,
    db: Session = Depends(get_db),
    auth: ServiceAuthContext = Depends(verify_service_api_key),
):
    workspace_id = require_workspace(auth)
    key = (
        db.query(ApiKey)
        .filter(ApiKey.id == key_id, ApiKey.workspace_id == workspace_id)
        .first()
    )
    if key is None:
        raise HTTPException(status_code=404, detail="API key not found")
    if key.is_active:
        key.is_active = False
        key.revoked_at = datetime.utcnow()
        db.commit()
    return None
