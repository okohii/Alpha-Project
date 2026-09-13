"""Garante que `_build_system_prompt` (agora async) continua funcionando."""
from __future__ import annotations

import inspect

import pytest

from app.agent.agent import AgentCore
from app.llm.base import LLMResponse
from app.llm.mock import MockLLMProvider
from app.llm.router import LLMRouter
from app.tools.registry import ToolRegistry


class FakeMacro:
    def __init__(self, name: str, description: str) -> None:
        self.name = name
        self.description = description


class FakeScalars:
    def __init__(self, items) -> None:
        self._items = items

    def all(self):
        return list(self._items)


class FakeExecuteResult:
    def __init__(self, items) -> None:
        self._items = items

    def scalars(self):
        return FakeScalars(self._items)


class FakeSession:
    def __init__(self, items=None) -> None:
        self._items = items or []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def execute(self, *args, **kwargs):
        return FakeExecuteResult(self._items)


class FakeMemoryService:
    async def search_memories(self, query: str, limit: int = 5):
        return []

    async def load_profile(self, limit: int = 50):
        return []

    async def save_episode(self, user_message, response, tool_names=None):
        return None


@pytest.mark.anyio
async def test_build_system_prompt_is_async():
    assert inspect.iscoroutinefunction(AgentCore._build_system_prompt)


@pytest.mark.anyio
async def test_chat_flow_builds_system_prompt_async(monkeypatch):
    """chat() chama _build_system_prompt de forma async sem bloquear o loop."""
    captured: list[str] = []

    async def _fake_macros(self) -> str:
        captured.append("called")
        return f"prompt {self._project_context()}"

    monkeypatch.setattr(AgentCore, "_build_system_prompt", _fake_macros)

    provider = MockLLMProvider([LLMResponse(content="ok")])
    agent = AgentCore(
        llm_router=LLMRouter(local_provider=provider, cloud_provider=provider),
        tool_registry=ToolRegistry(tools={}),
        memory_service=FakeMemoryService(),
    )

    result = await agent.chat("oi")

    assert result["response"] == "ok"
    assert captured == ["called"]
    assert provider.calls
    # O system prompt via novo caminho async chegou ao provedor.
    sent_messages = provider.calls[0][0]
    assert any(
        isinstance(m.content, str)
        and m.content.startswith("prompt ")
        and "Rotas permitidas" in m.content
        for m in sent_messages
        if m.role == "system"
    )


@pytest.mark.anyio
async def test_build_system_prompt_appends_macros(monkeypatch):
    """Macros carregados via session async são listados no prompt."""
    fake_session = FakeSession(
        [FakeMacro("abrir email", "abre o cliente de email")]
    )
    monkeypatch.setattr(
        "app.db.session.AsyncSessionLocal", lambda: fake_session
    )

    agent = AgentCore(
        llm_router=LLMRouter(
            local_provider=MockLLMProvider([LLMResponse(content="ok")]),
            cloud_provider=MockLLMProvider([LLMResponse(content="ok")]),
        ),
        tool_registry=ToolRegistry(tools={}),
        memory_service=FakeMemoryService(),
    )

    prompt = await agent._build_system_prompt()

    assert "## Macros disponíveis" in prompt
    assert "abrir email: abre o cliente de email" in prompt


@pytest.mark.anyio
async def test_build_system_prompt_without_macros(monkeypatch):
    """Sem macros, o prompt é montado sem a seção de macros."""
    fake_session = FakeSession([])
    monkeypatch.setattr(
        "app.db.session.AsyncSessionLocal", lambda: fake_session
    )

    agent = AgentCore(
        llm_router=LLMRouter(
            local_provider=MockLLMProvider([LLMResponse(content="ok")]),
            cloud_provider=MockLLMProvider([LLMResponse(content="ok")]),
        ),
        tool_registry=ToolRegistry(tools={}),
        memory_service=FakeMemoryService(),
    )

    prompt = await agent._build_system_prompt()

    assert "## Macros disponíveis" not in prompt
    assert "Rotas permitidas" in prompt
    assert "ALPHA" in prompt