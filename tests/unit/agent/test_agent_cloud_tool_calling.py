"""Tool calling no MODO CLOUD em nível de agente: tool é enviada e executada."""
from __future__ import annotations


async def _approve(candidate):
    return True


async def _deny(candidate):
    return False


from unittest.mock import patch

import pytest

from app.agent.agent import AgentCore
from app.llm.base import LLMResponse, ToolCall
from app.llm.mock import MockLLMProvider
from app.llm.router import LLMRouter
from app.tools.base import Tool, ToolPermission, ToolResult
from app.tools.registry import ToolRegistry


class FakeCloud:
    model = "alpha"
    base_url = "http://gateway:20128/v1"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def complete(self, messages, tools=None, temperature=0.2):
        self.calls.append({"messages": list(messages), "tools": tools})
        return self.responses.pop(0)


class OpenAppTool(Tool):
    name = "open_app"
    description = "abre aplicativo"
    permission = ToolPermission.write

    def __init__(self):
        self.calls = 0

    async def execute(self, **kwargs):
        self.calls += 1
        return ToolResult(name=self.name, success=True, data={"app": kwargs.get("app")})

    def parameters_schema(self):
        return {"type": "object", "properties": {"app": {"type": "string"}}, "required": ["app"]}


class FakeMemory:
    async def search_memories(self, query, limit=5):
        return []

    async def load_profile(self, limit=50):
        return []

    async def save_episode(self, *a, **k):
        return None


@pytest.mark.anyio
async def test_cloud_mode_calls_tool_and_executes():
    cloud = FakeCloud(
        [
            LLMResponse(content="", tool_calls=[ToolCall(name="open_app", arguments={"app": "bloco de notas"})]),
            LLMResponse(content="Pronto, abri o bloco de notas."),
        ]
    )
    router = LLMRouter(local_provider=MockLLMProvider([LLMResponse(content="x")]), cloud_provider=cloud)
    tool = OpenAppTool()
    agent = AgentCore(
        llm_router=router,
        tool_registry=ToolRegistry(tools={"open_app": tool}),
        memory_service=FakeMemory(),
        permission_request_handler=_approve,
    )
    agent.settings.llm_mode = "cloud"

    with patch.object(router, "_cloud_available", return_value=True):
        result = await agent.chat("abrir o bloco de notas")

    assert tool.calls == 1
    assert "open_app" in result["tools_used"]
    assert result["response"] == "Pronto, abri o bloco de notas."
    assert result["evidence"]
    assert result["evidence"][0]["tool"] == "open_app"
    assert result["route"]["selected_route"] == "cloud"
    assert result["route"]["configured_mode"] == "cloud"

    # O gateway cloud recebeu os schemas das tools no turno.
    assert cloud.calls and cloud.calls[0]["tools"]
    schema_names = {
        s["function"]["name"] for s in cloud.calls[0]["tools"]
    }
    assert "open_app" in schema_names


@pytest.mark.anyio
async def test_cloud_mode_preserves_assistant_before_tool_result():
    cloud = FakeCloud(
        [
            LLMResponse(content="", tool_calls=[ToolCall(name="open_app", arguments={"app": "x"})]),
            LLMResponse(content="ok"),
        ]
    )
    router = LLMRouter(local_provider=MockLLMProvider([LLMResponse(content="x")]), cloud_provider=cloud)
    agent = AgentCore(
        llm_router=router,
        tool_registry=ToolRegistry(tools={"open_app": OpenAppTool()}),
        memory_service=FakeMemory(),
        permission_request_handler=_approve,
    )
    agent.settings.llm_mode = "cloud"

    with patch.object(router, "_cloud_available", return_value=True):
        await agent.chat("abrir")

    second_turn = cloud.calls[1]["messages"]
    assistant_idx = next(i for i, m in enumerate(second_turn) if m.role == "assistant" and m.tool_calls)
    tool_idx = next(i for i, m in enumerate(second_turn) if m.role == "tool")
    assert assistant_idx < tool_idx