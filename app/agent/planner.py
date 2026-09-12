from __future__ import annotations

from app.assistant.intent import Goal
from app.execution.models import Plan, PlanStep
from app.security.permissions import SecurityLevel

_STRICT_TOOLS = frozenset({
    "browser_click", "browser_js", "browser_open", "browser_navigate",
    "open_app", "open_url", "open_file", "close_app", "move_app",
    "mouse_click", "mouse_scroll", "type_text", "press_key", "click_text",
    "run_shell", "run_code", "task_execute", "procedure_run", "macro_run",
})


class Planner:
    """Converte ``Goal`` em ``Plan`` executável e verificável.

    O Planner não executa ferramentas nem decide segurança. Ele define a ordem,
    a ferramenta-alvo, as dependências e a evidência necessária para liberar o
    checkpoint seguinte.
    """

    def build_plan(self, goal: Goal) -> Plan:
        steps: list[PlanStep] = []
        for i, task in enumerate(goal.tasks):
            step_id = f"step-{goal.id or 'goal'}-{i}"
            if task.tool_hint in _STRICT_TOOLS:
                expected = [
                    "pós-condição observada e confirmada",
                    f"{task.tool_hint} executado com sucesso",
                ]
            else:
                expected = [f"{task.tool_hint} executado com sucesso"]
            steps.append(
                PlanStep(
                    id=step_id,
                    tool_hint=task.tool_hint,
                    entities=dict(task.entities or goal.intent.entities or {}),
                    required_permission=task.required_permission,
                    dependencies=[] if i == 0 else [f"step-{goal.id or 'goal'}-{i - 1}"],
                    expected_evidence=expected,
                    retryable=task.tool_hint not in {"memory_delete", "macro_run", "task_execute", "procedure_run"},
                )
            )

        skills_needed = []
        for step in steps:
            if step.tool_hint not in skills_needed:
                skills_needed.append(step.tool_hint)

        risk_level = getattr(goal.intent, "risk_level", SecurityLevel.low)
        return Plan(
            id=goal.id or "",
            goal_intent=goal.intent.name,
            goal_entities=dict(goal.intent.entities or {}),
            priority=goal.priority,
            risk_level=risk_level,
            steps=steps,
            skills_needed=skills_needed,
            expected_result=goal.expected_result,
        )
