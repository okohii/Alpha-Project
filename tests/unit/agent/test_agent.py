from __future__ import annotations

import asyncio

import pytest

from app.agent.agent import AgentCore
from app.core.events import EventBus, EventType
from app.llm.base import LLMResponse, StreamedResponse, ToolCall
from app.llm.mock import MockLLMProvider
from app.llm.router import LLMRouter
from app.security import AccessDeniedError
from app.tools.base import Tool, ToolPermission, ToolResult
from app.tools.registry import ToolRegistry


class FakeTool(Tool):
    name = "time"
    description = "returns time"
    permission = ToolPermission.read

    async def execute(self, **kwargs):
        return ToolResult(name=self.name, success=True, data={"utc": "2026-08-17T00:00:00Z"})


class DeniedThenAllowedTool(Tool):
    name = "worker"
    description = "english"
    permission = ToolPermission.write

    def __init__(self):
        self.calls = 0

    async def execute(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return ToolResult(
                name=self.name,
                success=False,
                data={},
                error=AccessDeniedError("negado", candidate="C:/Users/teste/Downloads"),
            )
        return ToolResult(name=self.name, success=True, data={"done": True})


class DeniedTool(Tool):
    name = "worker"
    description = "english"
    permission = ToolPermission.write

    async def execute(self, **kwargs):
        return ToolResult(
            name=self.name,
            success=False,
            data={},
            error=AccessDeniedError("negado", candidate="C:/Users/teste/Downloads"),
        )


class ExplodingTool(Tool):
    name = "worker"
    description = "english"
    permission = ToolPermission.write

    async def execute(self, **kwargs):
        raise RuntimeError("boom")


class FakeMemoryService:
    def __init__(self):
        self.saved = []

    async def search_memories(self, query: str, limit: int = 5):
        return []

    async def load_profile(self, limit: int = 50):
        return []

    async def save_episode(
        self, user_message: str, response: str, tool_names: list[str] | None = None
    ):
        self.saved.append((user_message, tool_names))
        return type("Memory", (), {"content": user_message})()


@pytest.mark.anyio
async def test_agent_calls_tool_and_returns_final_answer():
    provider = MockLLMProvider(
        [
            LLMResponse(content="", tool_calls=[ToolCall(name="time", arguments={})]),
            LLMResponse(content="A hora atual é 00:00 UTC."),
        ]
    )
    agent = AgentCore(
        llm_router=LLMRouter(local_provider=provider, cloud_provider=provider),
        tool_registry=ToolRegistry(tools={"time": FakeTool()}),
        memory_service=FakeMemoryService(),
    )

    result = await agent.chat("Que horas são?")

    assert result["response"] == "A hora atual é 00:00 UTC."
    assert result["memory_created"] is True


@pytest.mark.anyio
async def test_agent_respects_tool_iteration_limit():
    looping_provider = MockLLMProvider(
        [LLMResponse(content="", tool_calls=[ToolCall(name="time", arguments={})])]
    )
    agent = AgentCore(
        llm_router=LLMRouter(local_provider=looping_provider, cloud_provider=looping_provider),
        tool_registry=ToolRegistry(tools={"time": FakeTool()}),
        memory_service=FakeMemoryService(),
    )
    agent.settings.agent_max_tool_iterations = 1

    result = await agent.chat("Que horas são?")

    assert result["response"] == ""


def test_llm_router_prefers_local_for_simple_questions(monkeypatch):
    local_provider = MockLLMProvider([LLMResponse(content="local")])
    cloud_provider = MockLLMProvider([LLMResponse(content="cloud")])
    router = LLMRouter(local_provider=local_provider, cloud_provider=cloud_provider)
    router.settings.allow_cloud_llm = True
    router.settings.gemini_api_key = "token"
    router.settings.llm_mode = "auto"

    monkeypatch.setattr(router, "_cloud_available", lambda: False)

    assert router.choose("Qual é a capital do Brasil?") is local_provider


@pytest.mark.anyio
async def test_agent_includes_project_context_for_cloud_mode(monkeypatch):
    provider = MockLLMProvider([LLMResponse(content="ok")])
    router = LLMRouter(
        local_provider=MockLLMProvider([LLMResponse(content="local")]), cloud_provider=provider
    )
    router.settings.allow_cloud_llm = True
    router.settings.gemini_api_key = "token"
    router.settings.llm_mode = "auto"

    monkeypatch.setattr(router, "_cloud_available", lambda: True)

    agent = AgentCore(
        llm_router=router,
        tool_registry=ToolRegistry(tools={}),
        memory_service=FakeMemoryService(),
    )

    await agent.chat("Analise a arquitetura do projeto, como ele está estruturado e organize um resumo técnico.")

    assert provider.calls
    payload = provider.calls[0][0]
    assert any(
        "ALPHA" in message.content and "Rotas permitidas" in message.content
        for message in payload
        if message.role == "system"
    )


@pytest.mark.anyio
async def test_agent_requests_permission_and_retries_tool_when_granted():
    tool = DeniedThenAllowedTool()
    requests = []

    async def handler(candidate):
        requests.append(candidate)
        return True

    provider = MockLLMProvider(
        [
            LLMResponse(content="", tool_calls=[ToolCall(name="worker", arguments={})]),
            LLMResponse(content="trabalho concluído"),
        ]
    )
    agent = AgentCore(
        llm_router=LLMRouter(local_provider=provider, cloud_provider=provider),
        tool_registry=ToolRegistry(tools={"worker": tool}),
        memory_service=FakeMemoryService(),
        permission_request_handler=handler,
    )

    result = await agent.chat("pode fazer")

    assert result["response"] == "trabalho concluído"
    assert requests == ["C:/Users/teste/Downloads"]
    assert tool.calls == 2


@pytest.mark.anyio
async def test_agent_does_not_retry_tool_when_permission_denied():
    tool = DeniedTool()
    requests = []

    async def handler(candidate):
        requests.append(candidate)
        return False

    provider = MockLLMProvider(
        [
            LLMResponse(content="", tool_calls=[ToolCall(name="worker", arguments={})]),
            LLMResponse(content="não tenho permissão para acessar esse diretório."),
        ]
    )
    agent = AgentCore(
        llm_router=LLMRouter(local_provider=provider, cloud_provider=provider),
        tool_registry=ToolRegistry(tools={"worker": tool}),
        memory_service=FakeMemoryService(),
        permission_request_handler=handler,
    )

    result = await agent.chat("pode fazer")

    assert requests == ["C:/Users/teste/Downloads"]
    assert "não tenho permissão" in result["response"]


@pytest.mark.anyio
async def test_agent_survives_unexpected_tool_exception():
    provider = MockLLMProvider(
        [
            LLMResponse(content="", tool_calls=[ToolCall(name="worker", arguments={})]),
            LLMResponse(content="o trabalho falhou, vou tentar de outro jeito."),
        ]
    )
    agent = AgentCore(
        llm_router=LLMRouter(local_provider=provider, cloud_provider=provider),
        tool_registry=ToolRegistry(tools={"worker": ExplodingTool()}),
        memory_service=FakeMemoryService(),
        permission_request_handler=lambda _: True,
    )

    result = await agent.chat("faça")

    assert "outro jeito" in result["response"]
    # Tool que explodiu NÃO entrou como ação executada: memória/evidência só
    # registram execuções bem-sucedidas de verdade.
    assert "worker" not in agent._tools_used


def _mem(content: str, *, episode: bool = False):
    class M:
        def __init__(self):
            self.content = content
            self.metadata = {"episode": True} if episode else {}

    return M()


def test_memory_context_line_strips_episode_result_claims():
    line = AgentCore._memory_context_line(
        _mem(
            "Episódio: usuário pediu 'abre o chrome' | ações: open_app | "
            "resultado: 'O Chrome foi aberto com sucesso'",
            episode=True,
        )
    )

    assert "O Chrome foi aberto" not in line
    assert "ações: open_app" in line


def test_memory_context_line_keeps_preferences_intact():
    line = AgentCore._memory_context_line(
        _mem("preferencia: usuário sempre abre o Discord no monitor 2.")
    )

    assert line == "preferencia: usuário sempre abre o Discord no monitor 2."


@pytest.mark.anyio
async def test_agent_denies_by_default_without_handler():
    tool = DeniedTool()
    provider = MockLLMProvider(
        [
            LLMResponse(content="", tool_calls=[ToolCall(name="worker", arguments={})]),
            LLMResponse(content="sem acesso."),
        ]
    )
    agent = AgentCore(
        llm_router=LLMRouter(local_provider=provider, cloud_provider=provider),
        tool_registry=ToolRegistry(tools={"worker": tool}),
        memory_service=FakeMemoryService(),
    )

    result = await agent.chat("pode fazer")

    assert "sem acesso" in result["response"]


class StreamingProvider:
    """Provider fake com stream_turn que entrega tokens e tool_calls."""

    def __init__(
        self,
        tokens: list[str],
        tool_calls: list[ToolCall] | None = None,
        content: str | None = None,
    ) -> None:
        self.tokens = tokens
        self.tool_calls = tool_calls
        self.final_content = content or "".join(tokens)

    async def complete(self, messages, tools=None, temperature=0.2):
        return LLMResponse(content=self.final_content, tool_calls=self.tool_calls)

    async def stream_turn(self, messages, tools=None, temperature=0.2):
        streamed = StreamedResponse()

        async def _iterate():
            for token in self.tokens:
                yield token
            streamed.content = self.final_content
            streamed.tool_calls = self.tool_calls

        streamed.generator = _iterate()
        return streamed


@pytest.mark.anyio
async def test_agent_chat_stream_emits_tokens_in_order():
    bus = EventBus()
    provider = StreamingProvider(tokens=["olá", " ", "tudo", " ", "bem?"])
    agent = AgentCore(
        llm_router=LLMRouter(local_provider=provider, cloud_provider=provider),
        tool_registry=ToolRegistry(tools={}),
        memory_service=FakeMemoryService(),
        event_bus=bus,
    )

    events: list[tuple[EventType, dict]] = []

    async def consume(messages):
        collect = {"task": None}
        async for event in messages:
            if event.type in (EventType.token_stream, EventType.assistant_message):
                events.append((event.type, event.payload))
        collect["task"] = "done"
        return collect

    async with asyncio.TaskGroup() as tg:
        result_task = tg.create_task(consume(agent.chat_stream("Oi")))

    await result_task

    token_payloads = [payload for event, payload in events if event is EventType.token_stream]
    joined = "".join(payload.get("token", "") for payload in token_payloads)
    assert joined == "olá tudo bem?"


@pytest.mark.anyio
async def test_agent_chat_stream_yields_assistant_message():
    bus = EventBus()
    provider = StreamingProvider(tokens=["resposta ok"])
    agent = AgentCore(
        llm_router=LLMRouter(local_provider=provider, cloud_provider=provider),
        tool_registry=ToolRegistry(tools={}),
        memory_service=FakeMemoryService(),
        event_bus=bus,
    )

    finals: list[dict] = []
    async for event in agent.chat_stream("Olá"):
        if event.type is EventType.assistant_message:
            finals.append(event.payload)

    assert finals
    assert finals[-1].get("content") == "resposta ok"


@pytest.mark.anyio
async def test_agent_chat_emits_start_finish_and_cancellation_aware():
    bus = EventBus()
    provider = StreamingProvider(tokens=["ok"])
    agent = AgentCore(
        llm_router=LLMRouter(local_provider=provider, cloud_provider=provider),
        tool_registry=ToolRegistry(tools={}),
        memory_service=FakeMemoryService(),
        event_bus=bus,
    )

    started = []
    finished = []
    bus.subscribe(EventType.agent_started, lambda e: started.append(e))
    bus.subscribe(EventType.agent_finished, lambda e: finished.append(e))

    result = await agent.chat("Oi")

    assert result["response"] == "ok"
    assert len(started) == 1
    assert len(finished) == 1
