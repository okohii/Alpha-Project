from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import DateTime, Float, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import (
    JSON_COLUMN_TYPE,
    USE_POSTGRES,
    VECTOR_COLUMN_TYPE,
    Base,
    TimestampMixin,
)


class Memory(Base, TimestampMixin):
    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    content: Mapped[str] = mapped_column(Text)
    memory_type: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(128), default="chat")
    importance: Mapped[float] = mapped_column(Float, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    embedding: Mapped[list[float] | None] = mapped_column(VECTOR_COLUMN_TYPE, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON_COLUMN_TYPE, default=dict)
    expiration: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


if USE_POSTGRES:
    Index("ix_memories_embedding", Memory.embedding, postgresql_using="ivfflat")
