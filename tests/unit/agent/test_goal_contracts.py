from __future__ import annotations

from app.agent.planner import Planner
from app.assistant.intent import Goal, Intent, Task
from app.execution.models import Plan


def test_goal_has_stable_id_and_serializes_tasks_without___dict__():
    goal = Goal(
        intent=Intent(name="gui_action"),
        tasks=[Task(tool_hint="mouse_click", entities={"text": "Enviar"})],
        original_text="Clique em Enviar",
        expected_result="Botão acionado",
    )

    payload = goal.to_dict()

    assert payload["id"].startswith("goal-")
    assert payload["tasks"] == [
        {
            "tool_hint": "mouse_click",
            "entities": {"text": "Enviar"},
            "required_permission": "read",
        }
    ]


def test_planner_builds_deterministic_sequential_dependencies():
    goal = Goal(
        intent=Intent(name="gui_action"),
        tasks=[
            Task(tool_hint="open_app"),
            Task(tool_hint="mouse_click"),
        ],
        expected_result="Tela aberta e botão acionado",
    )

    plan = Planner().build_plan(goal)

    assert isinstance(plan, Plan)
    assert plan.id == goal.id
    assert [step.id for step in plan.steps] == [
        f"step-{goal.id}-0",
        f"step-{goal.id}-1",
    ]
    assert plan.steps[0].dependencies == []
    assert plan.steps[1].dependencies == [f"step-{goal.id}-0"]
    assert plan.expected_result == goal.expected_result
