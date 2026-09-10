from __future__ import annotations

import time
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from app.agent.task import Task, TaskStatus, TaskStep
from app.core.events import EventBus, EventType


class AgentState(StrEnum):
    idle = "idle"
    understanding = "understanding"
    planning = "planning"
    executing = "executing"
    waiting_confirmation = "waiting_confirmation"
    waiting_input = "waiting_input"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class TaskEngine:
    """Gerencia o ciclo de vida de tarefas multi-etapas com estado explícito.

    Emite eventos via EventBus (task_created, task_step_completed, task_completed,
    task_failed, task_cancelled) para que a CLI acompanhe progresso real.
    """

    def __init__(self, event_bus: EventBus | None = None, max_iterations: int = 8) -> None:
        self.event_bus = event_bus
        self.max_iterations = max_iterations
        self._tasks: dict[str, Task] = {}
        self._order: list[str] = []
        self.agent_state: AgentState | None = AgentState.idle

    def start(self, goal: str, max_iterations: int | None = None) -> Task:
        task = Task(
            id=str(uuid4()),
            goal=goal,
            status=TaskStatus.running,
            max_iterations=max_iterations or self.max_iterations,
        )
        self._tasks[task.id] = task
        self._order.append(task.id)
        self._emit(EventType.task_created, task_id=task.id, goal=task.goal)
        return task

    def get(self, task_id: str | None) -> Task | None:
        if task_id is None:
            return None
        return self._tasks.get(task_id)

    def current(self) -> Task | None:
        for task_id in reversed(self._order):
            task = self._tasks[task_id]
            if task.status in (
                TaskStatus.pending,
                TaskStatus.running,
                TaskStatus.waiting_confirmation,
                TaskStatus.waiting_input,
            ):
                return task
        return None

    def recent(self, limit: int = 10) -> list[Task]:
        return [self._tasks[task_id] for task_id in reversed(self._order)][:limit]

    def add_step(self, task_id: str, name: str) -> TaskStep:
        task = self._require(task_id)
        step = TaskStep(name=name, status="running", started_at=time.monotonic())
        task.steps.append(step)
        task.current_step = name
        self._touch(task)
        self._emit(EventType.agent_progress, task_id=task_id, step=name)
        return step

    def complete_step(self, task_id: str, step: TaskStep, detail: str | None = None) -> None:
        step.status = "completed"
        step.detail = detail
        step.finished_at = time.monotonic()
        if step.started_at is not None:
            step.duration_ms = int((step.finished_at - step.started_at) * 1000)
        task = self._require(task_id)
        self._touch(task)
        self._emit(
            EventType.task_step_completed,
            task_id=task_id,
            step=step.name,
            duration_ms=step.duration_ms,
        )

    def fail_step(self, task_id: str, step: TaskStep, detail: str | None = None) -> None:
        step.status = "failed"
        step.detail = detail
        step.finished_at = time.monotonic()
        if step.started_at is not None:
            step.duration_ms = int((step.finished_at - step.started_at) * 1000)
        self._touch(self._require(task_id))

    def record_observation(self, task_id: str, observation: str) -> None:
        task = self._require(task_id)
        task.observations.append(observation)
        self._touch(task)

    def bump_iteration(self, task_id: str) -> Task:
        task = self._require(task_id)
        task.iterations += 1
        self._touch(task)
        return task

    def waiting(self, task_id: str, kind: str) -> None:
        task = self._require(task_id)
        task.status = (
            TaskStatus.waiting_confirmation
            if kind == "confirmation"
            else TaskStatus.waiting_input
        )
        self._touch(task)
        self._emit(
            EventType.waiting_confirmation if kind == "confirmation" else EventType.waiting_input,
            task_id=task_id,
            goal=task.goal,
        )

    def resumed(self, task_id: str) -> None:
        task = self._require(task_id)
        task.status = TaskStatus.running
        self._touch(task)

    def complete(self, task_id: str, result: Any = None) -> Task:
        task = self._require(task_id)
        task.status = TaskStatus.completed
        task.result = result
        self._touch(task)
        self._emit(EventType.task_completed, task_id=task_id, result=result)
        return task

    def fail(self, task_id: str, error: str) -> Task:
        task = self._require(task_id)
        task.status = TaskStatus.failed
        task.error = error
        self._touch(task)
        self._emit(EventType.task_failed, task_id=task_id, error=error)
        return task

    def cancel(self, task_id: str) -> Task:
        task = self._require(task_id)
        token = getattr(task, "_cancel_token", None)
        if token is not None:
            token.set()
        task.status = TaskStatus.cancelled
        self._touch(task)
        self._emit(EventType.task_cancelled, task_id=task_id, goal=task.goal)
        return task

    def cancel_current(self) -> Task | None:
        task = self.current()
        if task is None:
            return None
        return self.cancel(task.id)

    def _require(self, task_id: str) -> Task:
        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(f"tarefa não encontrada: {task_id}")
        return task

    def _touch(self, task: Task) -> None:
        task.updated_at = datetime.now(UTC)

    def _emit(self, event_type: EventType, **payload: Any) -> None:
        if self.event_bus is not None:
            self.event_bus.emit(event_type, dict(payload))