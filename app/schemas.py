from typing import List, Optional

from pydantic import BaseModel, Field


class TokenCreate(BaseModel):
    full_name: Optional[str] = Field(default=None, max_length=200)


class TokenResponse(BaseModel):
    user_token: str
    full_name: Optional[str] = None


class MemoryStore(BaseModel):
    user_token: str = Field(min_length=16, max_length=256)
    session_token: Optional[str] = Field(default=None, min_length=16, max_length=256)
    stage: Optional[str] = Field(default=None, max_length=100)
    summary: str = Field(min_length=1, max_length=100_000)


class MemoryRecall(BaseModel):
    user_token: str = Field(min_length=16, max_length=256)
    session_token: str = Field(min_length=16, max_length=256)


class MemoryUpdate(BaseModel):
    user_token: str = Field(min_length=16, max_length=256)
    session_token: str = Field(min_length=16, max_length=256)
    stage: Optional[str] = Field(default=None, max_length=100)
    summary: Optional[str] = Field(default=None, min_length=1, max_length=100_000)


class MemoryDelete(BaseModel):
    user_token: str = Field(min_length=16, max_length=256)
    session_token: str = Field(min_length=16, max_length=256)


class MemoryResponse(BaseModel):
    session_token: str
    stage: Optional[str] = None
    summary: str


class MemoryDeleteResponse(BaseModel):
    deleted: bool
    session_token: str


class MemoryListRequest(BaseModel):
    user_token: str = Field(min_length=16, max_length=256)


class MemorySessionMeta(BaseModel):
    memory_id: str
    stage: Optional[str] = None
    created_at: str
    updated_at: str


class MemoryListResponse(BaseModel):
    sessions: List[MemorySessionMeta]


class TenantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class TenantResponse(BaseModel):
    id: str
    name: str
    slug: str
    status: str


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ApiKeyCreatedResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    key_prefix: str
    api_key: str
    status: str


class ApiKeyResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    key_prefix: str
    status: str
    created_at: str
    revoked_at: Optional[str] = None
    last_used_at: Optional[str] = None


class PlanInfo(BaseModel):
    code: str
    name: str
    monthly_price_cents: int
    currency: str
    monthly_ops_limit: int
    max_memories: int


class BillingStatusResponse(BaseModel):
    tenant_id: str
    plan_code: str
    plan_name: str
    status: str
    monthly_price_cents: int
    currency: str
    period_key: str
    ops_used: int
    ops_limit: int
    ops_remaining: int
    memories_used: int
    memories_limit: int
    memories_remaining: int
    upgrade_required: bool


class CheckoutRequest(BaseModel):
    plan_code: str = Field(pattern=r"^(starter|growth)$")
    customer_email: Optional[str] = Field(default=None, max_length=320)


class CheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str
    plan_code: str


class AssignPlanRequest(BaseModel):
    plan_code: str = Field(pattern=r"^(free|starter|growth)$")
