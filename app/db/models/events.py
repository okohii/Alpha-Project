from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import JSON_COLUMN_TYPE, Base, TimestampMixin


class SystemEventRecord(Base, TimestampMixin):
    __tablename__ = "system_events"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    type: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON_COLUMN_TYPE, default=dict)