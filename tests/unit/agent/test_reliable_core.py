from __future__ import annotations

from app.agent.planner import Planner
from app.agent.reliable import Complexity, ComplexityGate, ReliableAgentCore
from app.assistant.intent import Goal, Intent, Task


def test_complexity_gate_distinguishes_simple_medium_complex():
    gate = ComplexityGate()
    assert gate.classify("oi").level is Complexity.SIMPLE
    assert gate.classify("abra o chrome").level is Complexity.MEDIUM
    decision = gate.classify("abra o chrome e depois abra o github e copie o meu perfil")
    assert decision.level is Complexity.COMPLEX
    assert decision.requires_plan is True
    assert decision.requires_verification is True


def test_plan_checkpoint_marks_strict_action_running_until_verified():
    core = object.__new__(ReliableAgentCore)
    core._plan = Planner().build_plan(
        Goal(intent=Intent(name="gui_action"), tasks=[Task(tool_hint="mouse_click")])
    )
    core._emit = lambda *args, **kwargs: None
    from app.llm.base import ExecutionEvidence

    execution = ExecutionEvidence(
        action_id="a1", tool="mouse_click", arguments={}, executed_at="now",
        success=True, result={}, verified=False, status="executed_unverified",
    )
    core._update_plan_checkpoint(execution)
    assert core._plan.steps[0].attempts == 1
    assert core._plan.steps[0].status == "running"


def test_plan_checkpoint_completes_after_verified_action():
    core = object.__new__(ReliableAgentCore)
    core._plan = Planner().build_plan(
        Goal(intent=Intent(name="gui_action"), tasks=[Task(tool_hint="mouse_click")])
    )
    core._emit = lambda *args, **kwargs: None
    from app.llm.base import ExecutionEvidence

    execution = ExecutionEvidence(
        action_id="a1", tool="mouse_click", arguments={}, executed_at="now",
        success=True, result={}, verified=True, status="verified",
    )
    core._update_plan_checkpoint(execution)
    assert core._plan.steps[0].status == "completed"
    assert core._plan.status == "completed"
