from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import (
    JSON_COLUMN_TYPE,
    USE_POSTGRES,
    VECTOR_COLUMN_TYPE,
    Base,
    TimestampMixin,
)


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    filename: Mapped[str] = mapped_column(String(255))
    path: Mapped[str] = mapped_column(Text, unique=True)
    hash: Mapped[str] = mapped_column(String(128), index=True)
    mime_type: Mapped[str] = mapped_column(String(128), default="application/octet-stream")
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON_COLUMN_TYPE, default=dict)


class DocumentChunk(Base, TimestampMixin):
    __tablename__ = "document_chunks"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    document_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("documents.id"), index=True
    )
    content: Mapped[str] = mapped_column(Text)
    chunk_index: Mapped[int] = mapped_column(Integer, index=True)
    embedding: Mapped[list[float] | None] = mapped_column(VECTOR_COLUMN_TYPE, nullable=True)
    document = relationship("Document")


if USE_POSTGRES:
    Index("ix_document_chunks_embedding", DocumentChunk.embedding, postgresql_using="ivfflat")