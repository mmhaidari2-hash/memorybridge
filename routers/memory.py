import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.auth_context import AuthContext
from app.database import get_db
from app.metrics import metrics
from app.models import MemoryRecord, User
from app.schemas import (
    MemoryDelete,
    MemoryDeleteResponse,
    MemoryListRequest,
    MemoryListResponse,
    MemoryRecall,
    MemoryResponse,
    MemorySessionMeta,
    MemoryStore,
    MemoryUpdate,
)
from app.security import decrypt_text, encrypt_text, hash_token
from app.service_auth import verify_service_api_key

router = APIRouter(tags=["Memory"])


def get_user(db: Session, tenant_id: str, user_token: str) -> User:
    user = (
        db.query(User)
        .filter(
            User.tenant_id == tenant_id,
            User.user_token_hash == hash_token(user_token),
        )
        .first()
    )
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return user


def get_memory(db: Session, tenant_id: str, user: User, session_token: str) -> MemoryRecord:
    record = (
        db.query(MemoryRecord)
        .filter(
            MemoryRecord.tenant_id == tenant_id,
            MemoryRecord.user_id == user.id,
            MemoryRecord.session_token_hash == hash_token(session_token),
        )
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="Memory session not found")
    return record


def _audit(
    db: Session,
    auth: AuthContext,
    request: Request,
    *,
    action: str,
    outcome: str,
    resource_id: Optional[str] = None,
) -> None:
    record_audit(
        db,
        tenant_id=auth.tenant_id,
        actor_type="service_key",
        actor_id=auth.key_id or auth.key_prefix,
        action=action,
        outcome=outcome,
        resource_type="memory",
        resource_id=resource_id,
        request_id=request.headers.get("X-Request-ID"),
    )
    metrics.incr("memorybridge_requests_total", action=action, outcome=outcome)


@router.post("/memory/store", response_model=MemoryResponse, status_code=201)
def store_memory(
    payload: MemoryStore,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(verify_service_api_key),
):
    user = get_user(db, auth.tenant_id, payload.user_token)
    session_token = payload.session_token or f"sess_{secrets.token_urlsafe(24)}"
    session_hash = hash_token(session_token)

    existing = (
        db.query(MemoryRecord)
        .filter(
            MemoryRecord.tenant_id == auth.tenant_id,
            MemoryRecord.user_id == user.id,
            MemoryRecord.session_token_hash == session_hash,
        )
        .first()
    )
    if existing:
        _audit(db, auth, request, action="memory.store", outcome="conflict", resource_id=existing.id)
        raise HTTPException(status_code=409, detail="Memory session already exists")

    encrypted, key_version = encrypt_text(
        payload.summary,
        tenant_id=auth.tenant_id,
        user_id=user.id,
    )
    record = MemoryRecord(
        tenant_id=auth.tenant_id,
        user_id=user.id,
        session_token_hash=session_hash,
        stage=payload.stage,
        encrypted_content=encrypted,
        key_version=key_version,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    _audit(db, auth, request, action="memory.store", outcome="success", resource_id=record.id)

    return MemoryResponse(
        session_token=session_token,
        stage=record.stage,
        summary=payload.summary,
    )


@router.post("/memory/recall", response_model=MemoryResponse)
def recall_memory(
    payload: MemoryRecall,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(verify_service_api_key),
):
    user = get_user(db, auth.tenant_id, payload.user_token)
    record = get_memory(db, auth.tenant_id, user, payload.session_token)

    try:
        summary = decrypt_text(
            record.encrypted_content,
            tenant_id=auth.tenant_id,
            user_id=user.id,
            key_version=record.key_version,
        )
    except Exception:
        _audit(db, auth, request, action="memory.recall", outcome="decrypt_error", resource_id=record.id)
        raise HTTPException(status_code=500, detail="Unable to decrypt memory") from None

    _audit(db, auth, request, action="memory.recall", outcome="success", resource_id=record.id)

    return MemoryResponse(
        session_token=payload.session_token,
        stage=record.stage,
        summary=summary,
    )


@router.put("/memory/update", response_model=MemoryResponse)
def update_memory(
    payload: MemoryUpdate,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(verify_service_api_key),
):
    if payload.summary is None and payload.stage is None:
        raise HTTPException(status_code=400, detail="Nothing to update")

    user = get_user(db, auth.tenant_id, payload.user_token)
    record = get_memory(db, auth.tenant_id, user, payload.session_token)

    if payload.summary is not None:
        encrypted, key_version = encrypt_text(
            payload.summary,
            tenant_id=auth.tenant_id,
            user_id=user.id,
        )
        record.encrypted_content = encrypted
        record.key_version = key_version
    if payload.stage is not None:
        record.stage = payload.stage

    db.commit()
    db.refresh(record)

    summary = decrypt_text(
        record.encrypted_content,
        tenant_id=auth.tenant_id,
        user_id=user.id,
        key_version=record.key_version,
    )
    _audit(db, auth, request, action="memory.update", outcome="success", resource_id=record.id)

    return MemoryResponse(
        session_token=payload.session_token,
        stage=record.stage,
        summary=summary,
    )


@router.post("/memory/delete", response_model=MemoryDeleteResponse)
def delete_memory(
    payload: MemoryDelete,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(verify_service_api_key),
):
    user = get_user(db, auth.tenant_id, payload.user_token)
    record = get_memory(db, auth.tenant_id, user, payload.session_token)
    record_id = record.id
    db.delete(record)
    db.commit()

    _audit(db, auth, request, action="memory.delete", outcome="success", resource_id=record_id)
    return MemoryDeleteResponse(deleted=True, session_token=payload.session_token)


@router.post("/memory/list", response_model=MemoryListResponse)
def list_memory_sessions(
    payload: MemoryListRequest,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(verify_service_api_key),
):
    """List session metadata only — never returns decrypted summaries."""
    user = get_user(db, auth.tenant_id, payload.user_token)
    records = (
        db.query(MemoryRecord)
        .filter(
            MemoryRecord.tenant_id == auth.tenant_id,
            MemoryRecord.user_id == user.id,
        )
        .order_by(MemoryRecord.updated_at.desc())
        .limit(200)
        .all()
    )

    _audit(db, auth, request, action="memory.list", outcome="success", resource_id=user.id)

    return MemoryListResponse(
        sessions=[
            MemorySessionMeta(
                memory_id=record.id,
                stage=record.stage,
                created_at=record.created_at.isoformat() + "Z",
                updated_at=record.updated_at.isoformat() + "Z",
            )
            for record in records
        ]
    )
