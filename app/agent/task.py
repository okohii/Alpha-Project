from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class TaskStatus(StrEnum):
    pending = "pending"
    running = "running"
    waiting_confirmation = "waiting_confirmation"
    waiting_input = "waiting_input"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


@dataclass(slots=True)
class TaskStep:
    name: str
    status: str = "pending"
    detail: str | None = None
    duration_ms: int | None = None
    started_at: float | None = None
    finished_at: float | None = None


@dataclass(slots=True)
class Task:
    id: str
    goal: str
    status: TaskStatus = TaskStatus.pending
    current_step: str | None = None
    steps: list[TaskStep] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    iterations: int = 0
    max_iterations: int = 0
    plan_id: str | None = None
    plan_step_ids: list[str] | None = None
    priority: str | None = None
    expected_result: str | None = None
    result: Any = None
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    _cancel_token: asyncio.Event | None = field(default=None, repr=False)

    @property
    def completed_steps(self) -> int:
        return sum(1 for step in self.steps if step.status == "completed")

    @property
    def failed_steps(self) -> int:
        return sum(1 for step in self.steps if step.status == "failed")

    def cancel_token(self) -> asyncio.Event:
        token = asyncio.Event()
        self._cancel_token = token
        return token

    def is_cancellation_requested(self) -> bool:
        token = self._cancel_token
        return token is not None and token.is_set()