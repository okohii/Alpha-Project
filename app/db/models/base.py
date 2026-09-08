from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, declarative_base, mapped_column
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