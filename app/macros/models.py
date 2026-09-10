from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import JSON_COLUMN_TYPE, Base, TimestampMixin


class MacroStepType(StrEnum):
    CLICK = "click"                    # clicar em elemento (UIA) ou coordenada
    TYPE = "type"                      # digitar texto
    PRESS_KEY = "press_key"            # tecla/combinação
    OPEN_APP = "open_app"              # abrir aplicativo
    OPEN_URL = "open_url"              # abrir URL
    WAIT = "wait"                      # esperar (segundos ou texto aparecer)
    SCROLL = "scroll"                  # rolar
    MOVE_WINDOW = "move_window"        # mover janela de monitor
    CLOSE_APP = "close_app"            # fechar app
    MESSAGE = "message"                # placeholder de mensagem (params.message)


class MacroRecord(Base, TimestampMixin):
    __tablename__ = "macros"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    parameters: Mapped[list[str]] = mapped_column(JSON_COLUMN_TYPE, default=list)
    tags: Mapped[list[str]] = mapped_column(JSON_COLUMN_TYPE, default=list)
    enabled: Mapped[int] = mapped_column(Integer, default=1, index=True)
    target_path: Mapped[str | None] = mapped_column(String(256), nullable=True)

    steps: Mapped[list[MacroStepRecord]] = relationship(
        "MacroStepRecord",
        back_populates="macro",
        cascade="all, delete-orphan",
        order_by="MacroStepRecord.step_order",
        lazy="selectin",
    )
    schedules: Mapped[list[MacroScheduleRecord]] = relationship(
        "MacroScheduleRecord",
        back_populates="macro",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "tags": self.tags,
            "enabled": bool(self.enabled),
            "steps": [s.to_dict() for s in self.steps],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class MacroStepRecord(Base):
    __tablename__ = "macro_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    macro_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("macros.id", ondelete="CASCADE"),
        index=True,
    )
    step_order: Mapped[int] = mapped_column(Integer)
    step_type: Mapped[str] = mapped_column(String(32))
    params: Mapped[dict[str, Any]] = mapped_column(JSON_COLUMN_TYPE, default=dict)
    wait_after: Mapped[float] = mapped_column(default=0.0)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    macro: Mapped[MacroRecord] = relationship("MacroRecord", back_populates="steps")

    __table_args__ = (UniqueConstraint("macro_id", "step_order", name="uq_macro_step_order"),)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "order": self.step_order,
            "step_type": self.step_type,
            "params": self.params,
            "wait_after": self.wait_after,
            "description": self.description,
        }


class MacroScheduleRecord(Base, TimestampMixin):
    __tablename__ = "macro_schedules"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    macro_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("macros.id", ondelete="CASCADE"),
        index=True,
    )
    cron_expression: Mapped[str | None] = mapped_column(String(128), nullable=True)
    run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fixed_parameters: Mapped[dict[str, Any]] = mapped_column(JSON_COLUMN_TYPE, default=dict)
    enabled: Mapped[int] = mapped_column(Integer, default=1, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    run_count: Mapped[int] = mapped_column(Integer, default=0)

    macro: Mapped[MacroRecord] = relationship("MacroRecord", back_populates="schedules")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "macro_id": self.macro_id,
            "cron_expression": self.cron_expression,
            "run_at": self.run_at.isoformat() if self.run_at else None,
            "fixed_parameters": self.fixed_parameters,
            "enabled": bool(self.enabled),
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "next_run_at": self.next_run_at.isoformat() if self.next_run_at else None,
            "run_count": self.run_count,
        }


class MacroExecutionLogRecord(Base):
    __tablename__ = "macro_execution_logs"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    macro_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("macros.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    schedule_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("macro_schedules.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(32))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON_COLUMN_TYPE, default=dict)
    steps_executed: Mapped[int] = mapped_column(Integer, default=0)
    steps_total: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "macro_id": self.macro_id,
            "schedule_id": self.schedule_id,
            "status": self.status,
            "parameters": self.parameters,
            "steps_executed": self.steps_executed,
            "steps_total": self.steps_total,
            "error": self.error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "duration_ms": self.duration_ms,
        }