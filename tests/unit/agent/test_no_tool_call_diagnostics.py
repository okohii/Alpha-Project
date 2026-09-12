"""Diagnóstico e retry estrutural quando o LLM não produz tool call.

Uma tarefa claramente acionável com tools expostas NUNCA vira "não entendi"
silenciosamente: registramos ``tool_selection_status=no_tool_call`` e, quando
a rota primária é cloud, tentamos UMA vez a rota local (modelo causal com
tool calling nativo) antes de aceitar a resposta de texto.
"""
from __future__ import annotations

import pytest

from app.agent.reliable import Complexity, ComplexityDecision, ReliableAgentCore
from app.core.events import EventType
from app.llm.base import LLMMessage, LLMResponse, ToolCall
from app.llm.mock import MockLLMProvider
from app.llm.router import FaultTolerantProvider

SCHEMA = {
    "type": "function",
    "function": {
        "name": "open_app",
        "parameters": {"type": "object", "properties": {}},
    },
}


def _core(
    complexity: Complexity = Complexity.MEDIUM, task: str = "abrir o bloco de notas"
) -> ReliableAgentCore:
    core = object.__new__(ReliableAgentCore)
    core._complexity = ComplexityDecision(
        complexity,
        complexity is Complexity.COMPLEX,
        complexity is not Complexity.SIMPLE,
        "só teste",
    )
    core._active_task = task
    core.events = []
    core.event_bus = None
    return core


def _recorded(core: ReliableAgentCore) -> list[dict]:
    return [
        {"type": event.type, "payload": event.payload}
        for event in getattr(core, "events", [])
    ]


@pytest.mark.anyio
async def test_cloud_no_tool_call_retries_local_once():
    local = MockLLMProvider(
        [LLMResponse(content="", tool_calls=[ToolCall(name="open_app", arguments={"app": "x"})])]
    )
    cloud = MockLLMProvider([LLMResponse(content="não entendi")])
    provider = FaultTolerantProvider(
        primary=cloud, fallback=local, label="cloud", fallback_label="local"
    )

    core = _core()
    response = await core._provider_turn(
        provider,
        [LLMMessage(role="user", content="abrir o bloco de notas")],
        [SCHEMA],
        False,
    )

    assert response.tool_calls
    assert response.tool_calls[0].name == "open_app"
    assert len(cloud.calls) == 1
    assert len(local.calls) == 1

    kinds = [e.payload.get("status") for e in core.events if e.type is EventType.tool_selected]
    assert "no_tool_call" in kinds
    progress = [e.payload.get("kind") for e in core.events if e.type is EventType.agent_progress]
    assert "retry_local" in progress


@pytest.mark.anyio
async def test_local_route_no_tool_call_is_diagnosed_but_not_retried():
    local = MockLLMProvider([LLMResponse(content="não entendi")])
    cloud = MockLLMProvider([LLMResponse(content="não entendi")])
    provider = FaultTolerantProvider(
        primary=local, fallback=cloud, label="local", fallback_label="cloud"
    )

    core = _core()
    response = await core._provider_turn(
        provider,
        [LLMMessage(role="user", content="abrir o bloco de notas")],
        [SCHEMA],
        False,
    )

    assert response.tool_calls is None
    assert len(local.calls) == 1
    assert len(cloud.calls) == 0
    statuses = [e.payload.get("status") for e in core.events if e.type is EventType.tool_selected]
    assert "no_tool_call" in statuses


@pytest.mark.anyio
async def test_simple_task_does_not_trigger_diagnostics():
    provider = FaultTolerantProvider(
        primary=MockLLMProvider([LLMResponse(content="oi")]),
        fallback=MockLLMProvider([LLMResponse(content="oi")]),
        label="cloud",
        fallback_label="local",
    )
    core = _core(Complexity.SIMPLE, task="oi")
    response = await core._provider_turn(
        provider, [LLMMessage(role="user", content="oi")], [SCHEMA], False
    )
    assert response.content == "oi"
    kinds = [e.payload.get("status") for e in core.events if e.type is EventType.tool_selected]
    assert "no_tool_call" not in kinds


@pytest.mark.anyio
async def test_cloud_retry_requires_ollama_available(monkeypatch):
    local = MockLLMProvider(
        [LLMResponse(content="", tool_calls=[ToolCall(name="open_app", arguments={"app": "x"})])]
    )
    local.base_url = "http://localhost:11434"
    cloud = MockLLMProvider([LLMResponse(content="sem tool call")])
    provider = FaultTolerantProvider(
        primary=cloud, fallback=local, label="cloud", fallback_label="local"
    )

    core = _core()
    async def _ollama_down(_url) -> bool:
        return False
    monkeypatch.setattr("app.agent.reliable.ollama_available", _ollama_down)
    response = await core._provider_turn(
        provider, [LLMMessage(role="user", content="abrir o bloco de notas")], [SCHEMA], False
    )

    # Ollama fora do ar -> o retry local é SKIPPED (não há double-call nem loop).
    assert response.tool_calls is None
    assert len(cloud.calls) == 1
    assert len(local.calls) == 0


@pytest.mark.anyio
async def test_cloud_retry_happens_when_ollama_available(monkeypatch):
    local = MockLLMProvider(
        [LLMResponse(content="", tool_calls=[ToolCall(name="open_app", arguments={"app": "x"})])]
    )
    local.base_url = "http://localhost:11434"
    cloud = MockLLMProvider([LLMResponse(content="sem tool call")])
    provider = FaultTolerantProvider(
        primary=cloud, fallback=local, label="cloud", fallback_label="local"
    )

    core = _core()
    async def _ollama_up(_url) -> bool:
        return True
    monkeypatch.setattr("app.agent.reliable.ollama_available", _ollama_up)
    response = await core._provider_turn(
        provider, [LLMMessage(role="user", content="abrir o bloco de notas")], [SCHEMA], False
    )

    assert response.tool_calls and response.tool_calls[0].name == "open_app"
    assert len(cloud.calls) == 1
    assert len(local.calls) == 1


def test_selection_status_classification():
    from app.agent.serialized import SerializedAgentCore

    compute = SerializedAgentCore._compute_tool_selection_status
    def _status(**kw):
        return compute(
            executed_count=kw.get("executed_count", 0),
            denied_count=kw.get("denied_count", 0),
            exposed_tools=kw.get("exposed_tools", set()),
            selected_skills=kw.get("selected_skills", []),
            fallback_used=kw.get("fallback_used", False),
        )[0]

    status = _status(executed_count=1, exposed_tools={"a"}, selected_skills=["Computer"])
    assert status == "selected"
    assert _status(denied_count=2, exposed_tools={"a"}) == "rejected"
    assert _status(exposed_tools=set(), selected_skills=["Computer"]) == "unavailable"
    assert _status(exposed_tools={"b"}, fallback_used=True) == "ambiguous"
    assert _status(exposed_tools={"c"}, selected_skills=["Computer"]) == "no_tool_call"