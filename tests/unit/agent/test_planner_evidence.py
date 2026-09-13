from __future__ import annotations

from app.agent.planner import Planner
from app.assistant.intent import Goal, Intent, Task


def test_strict_plan_step_requires_postcondition_evidence():
    goal = Goal(
        intent=Intent(name="gui_action"),
        tasks=[Task(tool_hint="mouse_click")],
        expected_result="botão acionado",
    )
    step = Planner().build_plan(goal).steps[0]
    assert "pós-condição observada e confirmada" in step.expected_evidence
    assert "mouse_click executado com sucesso" in step.expected_evidence
    assert step.retryable is True


def test_side_effecting_steps_are_not_marked_retryable_by_default():
    goal = Goal(
        intent=Intent(name="macro_execute"),
        tasks=[Task(tool_hint="macro_run", required_permission="sensitive")],
    )
    step = Planner().build_plan(goal).steps[0]
    assert step.retryable is False
