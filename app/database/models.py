from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, declarative_base, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.core.config import get_settings

try:
    from pgvector.sqlalchemy import Vector
except Exception:  # pragma: no cover
    Vector = None

settings = get_settings()
USE_POSTGRES = "postgresql" in settings.database_url.lower()
JSON_COLUMN_TYPE = JSONB if USE_POSTGRES else JSON


class JsonListText(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        return json.dumps(value)

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        return json.loads(value)


VECTOR_COLUMN_TYPE = Vector(384) if USE_POSTGRES and Vector is not None else JsonListText()

Base = declarative_base()


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(String(200), default="User")


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    title: Mapped[str] = mapped_column(String(255), default="New conversation")
    user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=True
    )
    user = relationship("User")


class Message(Base, TimestampMixin):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    conversation_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("conversations.id"), index=True
    )
    role: Mapped[str] = mapped_column(String(32), index=True)
    content: Mapped[str] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON_COLUMN_TYPE, default=dict)
    conversation = relationship("Conversation")


class Memory(Base, TimestampMixin):
    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    content: Mapped[str] = mapped_column(Text)
    memory_type: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(128), default="chat")
    importance: Mapped[float] = mapped_column(Float, default=0.0)
    embedding: Mapped[list[float] | None] = mapped_column(VECTOR_COLUMN_TYPE, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON_COLUMN_TYPE, default=dict)


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


class ToolExecution(Base, TimestampMixin):
    __tablename__ = "tool_executions"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    conversation_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("conversations.id"), nullable=True, index=True
    )
    tool_name: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    input_data: Mapped[dict[str, Any]] = mapped_column(JSON_COLUMN_TYPE, default=dict)
    output_data: Mapped[dict[str, Any] | None] = mapped_column(JSON_COLUMN_TYPE, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class TaskRecord(Base, TimestampMixin):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    title: Mapped[str] = mapped_column(String(255))
    instruction: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True, default="pending")
    params: Mapped[dict[str, Any]] = mapped_column(JSON_COLUMN_TYPE, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON_COLUMN_TYPE, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ManagedPathRecord(Base, TimestampMixin):
    __tablename__ = "managed_paths"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    path: Mapped[str] = mapped_column(Text, unique=True)
    entry_type: Mapped[str] = mapped_column(String(32), index=True)
    is_allowed: Mapped[int] = mapped_column(Integer, default=1)
    source: Mapped[str] = mapped_column(String(64), default="task_executor")
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON_COLUMN_TYPE, default=dict)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class SystemEventRecord(Base, TimestampMixin):
    __tablename__ = "system_events"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    type: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON_COLUMN_TYPE, default=dict)


class CalendarEventRecord(Base, TimestampMixin):
    __tablename__ = "calendar_events"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ReminderRecord(Base, TimestampMixin):
    __tablename__ = "reminders"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    title: Mapped[str] = mapped_column(String(255))
    schedule_type: Mapped[str] = mapped_column(String(16), index=True)
    schedule: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(64))
    params: Mapped[dict[str, Any]] = mapped_column(JSON_COLUMN_TYPE, default=dict)
    enabled: Mapped[int] = mapped_column(Integer, default=1, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


if USE_POSTGRES:
    Index("ix_memories_embedding", Memory.embedding, postgresql_using="ivfflat")
    Index("ix_document_chunks_embedding", DocumentChunk.embedding, postgresql_using="ivfflat")
