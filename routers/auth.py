import secrets

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.auth_context import AuthContext
from app.database import get_db
from app.metrics import metrics
from app.models import User
from app.schemas import TokenCreate, TokenResponse
from app.security import hash_token
from app.service_auth import verify_service_api_key

router = APIRouter(tags=["Auth"])


@router.post("/auth/token", response_model=TokenResponse, status_code=201)
def create_token(
    payload: TokenCreate,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(verify_service_api_key),
):
    # Plaintext token is returned once and never stored.
    user_token = f"mb_{secrets.token_urlsafe(32)}"
    db_user = User(
        tenant_id=auth.tenant_id,
        user_token_hash=hash_token(user_token),
        full_name=payload.full_name,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    request_id = request.headers.get("X-Request-ID")
    record_audit(
        db,
        tenant_id=auth.tenant_id,
        actor_type="service_key",
        actor_id=auth.key_id or auth.key_prefix,
        action="auth.token_create",
        outcome="success",
        resource_type="user",
        resource_id=db_user.id,
        request_id=request_id,
    )
    metrics.incr("memorybridge_requests_total", action="auth.token_create", outcome="success")

    return TokenResponse(user_token=user_token, full_name=db_user.full_name)
