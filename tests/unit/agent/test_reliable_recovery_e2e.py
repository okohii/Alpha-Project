from __future__ import annotations

import asyncio

import pytest

from app.agent.reliable import ReliableAgentCore
from app.assistant.facilitator import AssistantFacilitator
from app.llm.base import LLMResponse, ToolCall
from app.llm.mock import MockLLMProvider
from app.llm.router import LLMRouter
from app.skills.base import Skill
from app.skills.registry import SkillRegistry
from app.tools.base import Tool, ToolPermission, ToolResult
from app.tools.registry import ToolRegistry


class Memory:
    async def search_memories(self, query, limit=5): return []
    async def load_profile(self, limit=50): return []
    async def save_episode(self, *args, **kwargs): return None


class Primary(Tool):
    name = "primary_action"
    description = "ação primária"
    permission = ToolPermission.write

    def __init__(self): self.calls = 0

    async def execute(self, **kwargs):
        self.calls += 1
        return ToolResult(name=self.name, success=False, data={}, error="alvo indisponível")

    def parameters_schema(self): return {"type": "object", "properties": {}}


class Alternate(Tool):
    name = "alternate_action"
    description = "ação alternativa"
    permission = ToolPermission.write

    def __init__(self): self.calls = 0

    async def execute(self, **kwargs):
        self.calls += 1
        return ToolResult(name=self.name, success=True, data={"done": True})

    def parameters_schema(self): return {"type": "object", "properties": {}}


class Verify(Tool):
    name = "verify_screen"
    description = "verificação"
    permission = ToolPermission.read

    async def execute(self, **kwargs):
        return ToolResult(name=self.name, success=True, data={"achieved": True, "confidence": 0.95})

    def parameters_schema(self): return {"type": "object", "properties": {"goal": {"type": "string"}}}


class Blocking(Tool):
    name = "blocking_action"
    description = "ação bloqueante"
    permission = ToolPermission.write

    def __init__(self, started: asyncio.Event): self.started = started

    async def execute(self, **kwargs):
        self.started.set()
        await asyncio.sleep(60)
        return ToolResult(name=self.name, success=True, data={})

    def parameters_schema(self): return {"type": "object", "properties": {}}


def _agent(provider, tools, registry, cancel_event=None):
    return ReliableAgentCore(
        llm_router=LLMRouter(local_provider=provider, cloud_provider=provider),
        tool_registry=ToolRegistry(tools=tools),
        memory_service=Memory(),
        skill_registry=registry,
        facilitator=AssistantFacilitator(skill_registry=registry),
        permission_request_handler=lambda candidate: asyncio.sleep(0, result=True),
        cancel_event=cancel_event,
    )


@pytest.mark.anyio
async def test_failed_tool_recovers_with_different_tool_from_same_skill():
    primary = Primary()
    alternate = Alternate()
    verify = Verify()
    registry = SkillRegistry()
    registry.register(Skill(name="Computer", description="computador", keywords=["abrir", "aplicativo"], tools=["primary_action", "alternate_action", "verify_screen"]))
    provider = MockLLMProvider([
        LLMResponse(content="", tool_calls=[ToolCall(name="primary_action", arguments={})]),
        LLMResponse(content="", tool_calls=[ToolCall(name="alternate_action", arguments={})]),
        LLMResponse(content="Concluído com a alternativa."),
    ])
    agent = _agent(provider, {"primary_action": primary, "alternate_action": alternate, "verify_screen": verify}, registry)
    agent.settings.agent_require_tool_verification = False

    result = await agent.chat("abrir aplicativo")

    assert primary.calls == 1
    assert alternate.calls == 1
    assert result["response"] == "Concluído com a alternativa."
    assert any(item["tool"] == "primary_action" and item["success"] is False for item in result["evidence"])
    assert any(item["tool"] == "alternate_action" and item["success"] is True for item in result["evidence"])


@pytest.mark.anyio
async def test_cancellation_stops_execution_before_final_claim():
    started = asyncio.Event()
    cancel = asyncio.Event()
    blocking = Blocking(started)
    registry = SkillRegistry()
    registry.register(Skill(name="Computer", description="computador", keywords=["executar"], tools=["blocking_action"]))
    provider = MockLLMProvider([LLMResponse(content="", tool_calls=[ToolCall(name="blocking_action", arguments={})])])
    agent = _agent(provider, {"blocking_action": blocking}, registry, cancel_event=cancel)
    agent.settings.agent_tool_timeout_seconds = 30

    task = asyncio.create_task(agent.chat("executar ação"))
    await asyncio.wait_for(started.wait(), timeout=2)
    cancel.set()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.anyio
async def test_model_text_alone_cannot_turn_failed_execution_into_success():
    primary = Primary()
    registry = SkillRegistry()
    registry.register(Skill(name="Computer", description="computador", keywords=["abrir"], tools=["primary_action"]))
    provider = MockLLMProvider([
        LLMResponse(content="", tool_calls=[ToolCall(name="primary_action", arguments={})]),
        LLMResponse(content="Abri com sucesso."),
    ])
    agent = _agent(provider, {"primary_action": primary}, registry)
    agent.settings.agent_tool_result_strict = True

    result = await agent.chat("abrir aplicativo")

    assert primary.calls == 1
    assert result["response"] != "Abri com sucesso."
    assert "falh" in result["response"].lower() or "não" in result["response"].lower()
