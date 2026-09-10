from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from app.assistant.intent import Goal
from app.security.permissions import SecurityLevel


class PlanStatus(StrEnum):
    pending = "pending"
    ready = "ready"
    running = "running"
    waiting_confirmation = "waiting_confirmation"
    waiting_input = "waiting_input"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class PlanStepStatus(StrEnum):
    pending = "pending"
    ready = "ready"
    running = "running"
    waiting_confirmation = "waiting_confirmation"
    waiting_input = "waiting_input"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


@dataclass(slots=True)
class PlanStep:
    """Um único passo dentro de um ``Plan``.

    Representa uma unidade de execução: a ferramenta/skill a ser invocada,
    as entidades necessárias, a permissão requerida, dependências com outros
    passos e os esperados como "evidência" de conclusão bem-sucedida.
    """

    id: str
    tool_hint: str
    entities: dict[str, str] = field(default_factory=dict)
    required_permission: str = "read"
    status: str = PlanStepStatus.pending
    dependencies: list[str] = field(default_factory=list)
    expected_evidence: list[str] = field(default_factory=list)
    attempts: int = 0
    retryable: bool = False


@dataclass(slots=True)
class Plan:
    """Plano estruturado derivado de um ``Goal``.

    Contém a lista de passos, o estado geral, as skills necessárias e
    metadados de controle para o ciclo de execução via ``TaskEngine``.
    """

    id: str
    goal_intent: str
    goal_entities: dict[str, str]
    priority: str
    risk_level: SecurityLevel
    steps: list[PlanStep] = field(default_factory=list)
    status: PlanStatus = PlanStatus.pending
    skills_needed: list[str] = field(default_factory=list)
    expected_result: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    cancel_token: asyncio.Event | None = field(default=None, repr=False)

    def add_step(self, step: PlanStep) -> None:
        self.steps.append(step)
        self.updated_at = datetime.now(UTC)

    def set_running(self) -> None:
        self.status = PlanStatus.running
        self.updated_at = datetime.now(UTC)

    def set_completed(self, result: str | None = None) -> None:
        self.status = PlanStatus.completed
        self.expected_result = result
        self.updated_at = datetime.now(UTC)

    def set_failed(self, error: str) -> None:
        self.status = PlanStatus.failed
        self.updated_at = datetime.now(UTC)

    def set_cancelled(self) -> None:
        self.status = PlanStatus.cancelled
        self.updated_at = datetime.now(UTC)


# Helper para criar um Plan a partir de um Goal assistant (app/assistant/intent.py).
def from_assistant_goal(
    goal: Goal,
    *,
    priority: str = "normal",
    risk_level: SecurityLevel = SecurityLevel.low,
) -> Plan:
    """Converte um ``Goal`` assistant em um ``Plan`` determinístico.

    - Cada tarefa ``Task`` do Goal se torna um ``PlanStep``.
    - O ``priority`` e ``risk_level`` são copiados/derivados do Goal.
    - Skills necessários são extraídas das hints das Tasks.
    """
    steps: list[PlanStep] = []
    for i, task in enumerate(goal.tasks):
        step_id = f"step-{goal.id}-{i}"
        steps.append(
            PlanStep(
                id=step_id,
                tool_hint=task.tool_hint,
                entities=dict(goal.intent.entities) if goal.intent.entities else {},
                required_permission=task.required_permission,
                dependencies=[],
                expected_evidence=[f"{task.tool_hint} executado com sucesso"],
                retryable=False,
            )
        )
    return Plan(
        id=goal.id or "",
        goal_intent=goal.intent.name,
        goal_entities=dict(goal.intent.entities) if goal.intent.entities else {},
        priority=priority,
        risk_level=risk_level,
        steps=steps,
        expected_result=goal.expected_result,
    )