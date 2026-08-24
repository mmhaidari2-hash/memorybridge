import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_token = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    memories = relationship("MemoryRecord", back_populates="user")


class MemoryRecord(Base):
    __tablename__ = "memory_records"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_token = Column(String, ForeignKey("users.user_token"), nullable=False, index=True)
    session_token = Column(String, index=True, nullable=False)
    stage = Column(String, nullable=True)
    encrypted_content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="memories")
