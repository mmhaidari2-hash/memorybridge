import secrets
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User
from app.schemas import TokenCreate, TokenResponse

router = APIRouter(tags=["Auth"])

@router.post("/auth/token", response_model=TokenResponse)
def create_token(payload: TokenCreate, db: Session = Depends(get_db)):
    user_token = f"mb_{secrets.token_hex(16)}"
    db_user = User(user_token=user_token, full_name=payload.full_name)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return TokenResponse(user_token=db_user.user_token, full_name=db_user.full_name)
