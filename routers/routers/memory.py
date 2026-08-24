import secrets
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, MemoryRecord
from app.schemas import MemoryStore, MemoryRecall, MemoryUpdate, MemoryResponse
from app.security import encrypt_text, decrypt_text

router = APIRouter(tags=["Memory"])

@router.post("/memory/store", response_model=MemoryResponse)
def store_memory(payload: MemoryStore, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.user_token == payload.user_token).first()
    if not user:
        raise HTTPException(status_code=404, detail="User token not found")

    session_token = payload.session_token or f"sess_{secrets.token_hex(12)}"
    encrypted_summary = encrypt_text(payload.summary)

    record = MemoryRecord(
        user_token=payload.user_token,
        session_token=session_token,
        stage=payload.stage,
        encrypted_content=encrypted_summary,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return MemoryResponse(
        session_token=record.session_token,
        stage=record.stage,
        summary=payload.summary,
    )

@router.post("/memory/recall", response_model=MemoryResponse)
def recall_memory(payload: MemoryRecall, db: Session = Depends(get_db)):
    query = db.query(MemoryRecord).filter(MemoryRecord.user_token == payload.user_token)
    if payload.session_token:
        query = query.filter(MemoryRecord.session_token == payload.session_token)

    record = query.order_by(MemoryRecord.created_at.desc()).first()
    if not record:
        raise HTTPException(status_code=404, detail="No memory record found")

    decrypted_summary = decrypt_text(record.encrypted_content)
    return MemoryResponse(
        session_token=record.session_token,
        stage=record.stage,
        summary=decrypted_summary,
    )

@router.put("/memory/update", response_model=MemoryResponse)
def update_memory(payload: MemoryUpdate, db: Session = Depends(get_db)):
    record = (
        db.query(MemoryRecord)
        .filter(
            MemoryRecord.user_token == payload.user_token,
            MemoryRecord.session_token == payload.session_token,
        )
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="Memory session not found")

    if payload.summary:
        record.encrypted_content = encrypt_text(payload.summary)
    if payload.stage:
        record.stage = payload.stage

    db.commit()
    db.refresh(record)

    decrypted_summary = decrypt_text(record.encrypted_content)
    return MemoryResponse(
        session_token=record.session_token,
        stage=record.stage,
        summary=decrypted_summary,
    )
