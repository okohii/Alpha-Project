from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import JSON_COLUMN_TYPE, Base, TimestampMixin


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