from typing import Optional

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


class MemoryResponse(BaseModel):
    session_token: str
    stage: Optional[str] = None
    summary: str
