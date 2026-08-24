from pydantic import BaseModel
from typing import Optional


class TokenCreate(BaseModel):
    full_name: Optional[str] = None


class TokenResponse(BaseModel):
    user_token: str
    full_name: Optional[str] = None


class MemoryStore(BaseModel):
    user_token: str
    session_token: Optional[str] = None
    stage: Optional[str] = None
    summary: str


class MemoryRecall(BaseModel):
    user_token: str
    session_token: Optional[str] = None


class MemoryUpdate(BaseModel):
    user_token: str
    session_token: str
    stage: Optional[str] = None
    summary: Optional[str] = None


class MemoryResponse(BaseModel):
    session_token: str
    stage: Optional[str] = None
    summary: str
