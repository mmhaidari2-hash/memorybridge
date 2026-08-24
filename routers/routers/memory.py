import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import MemoryRecord, User
from app.schemas import MemoryRecall, MemoryResponse, MemoryStore, MemoryUpdate
from app.security import decrypt_text, encrypt_text, hash_token
from app.service_auth import ServiceAuthContext, verify_service_api_key
from app.usage import record_usage

router = APIRouter(tags=["Memory"])


def get_user(db: Session, user_token: str, auth: ServiceAuthContext) -> User:
    query = db.query(User).filter(User.user_token_hash == hash_token(user_token))
    if auth.workspace_id is None:
        query = query.filter(User.workspace_id.is_(None))
    else:
        query = query.filter(User.workspace_id == auth.workspace_id)

    user = query.first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return user


def get_memory(db: Session, user: User, session_token: str) -> MemoryRecord:
    record = (
        db.query(MemoryRecord)
        .filter(
            MemoryRecord.user_id == user.id,
            MemoryRecord.session_token_hash == hash_token(session_token),
        )
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="Memory session not found")
    return record


@router.post("/memory/store", response_model=MemoryResponse, status_code=201)
def store_memory(
    payload: MemoryStore,
    db: Session = Depends(get_db),
    auth: ServiceAuthContext = Depends(verify_service_api_key),
):
    user = get_user(db, payload.user_token, auth)
    session_token = payload.session_token or f"sess_{secrets.token_urlsafe(24)}"

    record = MemoryRecord(
        user_id=user.id,
        session_token_hash=hash_token(session_token),
        stage=payload.stage,
        encrypted_content=encrypt_text(payload.summary),
    )
    db.add(record)
    record_usage(db, auth, "memory.store")
    db.commit()

    return MemoryResponse(
        session_token=session_token,
        stage=record.stage,
        summary=payload.summary,
    )


@router.post("/memory/recall", response_model=MemoryResponse)
def recall_memory(
    payload: MemoryRecall,
    db: Session = Depends(get_db),
    auth: ServiceAuthContext = Depends(verify_service_api_key),
):
    user = get_user(db, payload.user_token, auth)
    record = get_memory(db, user, payload.session_token)
    summary = decrypt_text(record.encrypted_content)
    record_usage(db, auth, "memory.recall")
    db.commit()

    return MemoryResponse(
        session_token=payload.session_token,
        stage=record.stage,
        summary=summary,
    )


@router.put("/memory/update", response_model=MemoryResponse)
def update_memory(
    payload: MemoryUpdate,
    db: Session = Depends(get_db),
    auth: ServiceAuthContext = Depends(verify_service_api_key),
):
    user = get_user(db, payload.user_token, auth)
    record = get_memory(db, user, payload.session_token)

    if payload.summary is not None:
        record.encrypted_content = encrypt_text(payload.summary)
    if payload.stage is not None:
        record.stage = payload.stage

    record_usage(db, auth, "memory.update")
    db.commit()
    db.refresh(record)

    return MemoryResponse(
        session_token=payload.session_token,
        stage=record.stage,
        summary=decrypt_text(record.encrypted_content),
    )
