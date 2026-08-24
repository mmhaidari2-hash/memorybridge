import secrets

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.quota import enforce_quota
from app.schemas import TokenCreate, TokenResponse
from app.security import hash_token
from app.service_auth import ServiceAuthContext, verify_service_api_key
from app.usage import record_usage

router = APIRouter(tags=["Auth"])


@router.post("/auth/token", response_model=TokenResponse, status_code=201)
def create_token(
    payload: TokenCreate,
    db: Session = Depends(get_db),
    auth: ServiceAuthContext = Depends(verify_service_api_key),
):
    enforce_quota(db, auth)

    # The plaintext token is returned once to the caller and is never stored.
    user_token = f"mb_{secrets.token_urlsafe(32)}"
    db_user = User(
        workspace_id=auth.workspace_id,
        user_token_hash=hash_token(user_token),
        full_name=payload.full_name,
    )
    db.add(db_user)
    record_usage(db, auth, "user.create")
    db.commit()

    return TokenResponse(user_token=user_token, full_name=db_user.full_name)
