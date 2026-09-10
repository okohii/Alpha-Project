from __future__ import annotations

from app.assistant.intent import Goal
from app.execution.models import Plan, PlanStep
from app.security.permissions import SecurityLevel


class Planner:
    """Converte um ``Goal`` (camada COMPREENDER) em um ``Plan`` (camada de
    execução estruturada).

    Responsabilidades:
    - Transformar as ``Task`` do Goal em ``PlanStep``.
    - Definir dependências entre passos (sequenciais por padrão).
    - Identificar as skills/ferramentas necessárias.
    - Preservar prioridade, risco e o resultado esperado do Goal.
    - NUNCA executar tools e NUNCA decidir segurança: apenas planeja.
    """

    def build_plan(self, goal: Goal) -> Plan:
        """Constrói um ``Plan`` determinístico a partir de um ``Goal``.

        O plano resultante pode ser imediatamente passado ao ``TaskEngine``
        para execução supervisionada.
        """
        steps: list[PlanStep] = []
        for i, task in enumerate(goal.tasks):
            step_id = f"step-{goal.id or 'goal'}-{i}"
            steps.append(
                PlanStep(
                    id=step_id,
                    tool_hint=task.tool_hint,
                    entities=dict(goal.intent.entities) if goal.intent.entities else {},
                    required_permission=task.required_permission,
                    dependencies=[] if i == 0 else [f"step-{goal.id or 'goal'}-{i - 1}"],
                    expected_evidence=[f"{task.tool_hint} executado com sucesso"],
                    retryable=False,
                )
            )

        # Habilidades necessárias são os hints únicos das tasks.
        skills_needed: list[str] = list(
            {step.tool_hint for step in steps} if steps else []
        )

        # Deriva risco do intent, se disponível; fallback low.
        if hasattr(goal.intent, "risk_level"):
            risk_level = goal.intent.risk_level
        else:
            risk_level = SecurityLevel.low

        return Plan(
            id=goal.id or "",
            goal_intent=goal.intent.name,
            goal_entities=dict(goal.intent.entities) if goal.intent.entities else {},
            priority=goal.priority,
            risk_level=risk_level,
            steps=steps,
            skills_needed=skills_needed,
            expected_result=goal.expected_result,
        )