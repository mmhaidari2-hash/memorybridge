import secrets

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.schemas import TokenCreate, TokenResponse
from app.security import hash_token

router = APIRouter(tags=["Auth"])


@router.post("/auth/token", response_model=TokenResponse, status_code=201)
def create_token(payload: TokenCreate, db: Session = Depends(get_db)):
    # The plaintext token is returned once to the caller and is never stored.
    user_token = f"mb_{secrets.token_urlsafe(32)}"
    db_user = User(
        user_token_hash=hash_token(user_token),
        full_name=payload.full_name,
    )
    db.add(db_user)
    db.commit()

    return TokenResponse(user_token=user_token, full_name=db_user.full_name)
