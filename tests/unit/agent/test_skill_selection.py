"""Testes de integração: seleção de Skills/Tools no AgentCore.

Fluxo: Intent -> Skill selection -> Relevant tools -> verificação de
permissões ANTES de expor a tool -> Agent execution.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.agent.agent import CORE_TOOLS, FALLBACK_TOOLS, AgentCore
from app.llm.base import LLMResponse, ToolCall
from app.llm.mock import MockLLMProvider
from app.llm.router import LLMRouter
from app.skills.catalog import build_default_skill_registry
from app.tools.base import Tool, ToolPermission, ToolResult
from app.tools.registry import ToolRegistry


class FakeMemoryService:
    async def search_memories(self, query: str, limit: int = 5):
        return []

    async def load_profile(self, limit: int = 50):
        return []

    async def save_episode(self, user_message, response, tool_names=None):
        return type("Memory", (), {"content": user_message})()


@dataclass
class _Stub:
    name: str
    permission: ToolPermission = ToolPermission.read


def _make_tool(stub: _Stub) -> Tool:
    class _T(Tool):
        name = stub.name
        description = f"tool {stub.name}"
        permission = stub.permission

        async def execute(self, **kwargs):
            return ToolResult(name=self.name, success=True, data={})

        def parameters_schema(self):
            return {"type": "object", "properties": {}}

    return _T()


def _tools() -> dict[str, Tool]:
    specs = [
        _Stub("browser_open", ToolPermission.write),
        _Stub("browser_text", ToolPermission.read),
        _Stub("browser_js", ToolPermission.sensitive),
        _Stub("open_url", ToolPermission.write),
        _Stub("file_search", ToolPermission.read),
        _Stub("file_read", ToolPermission.read),
        _Stub("file_info", ToolPermission.read),
        _Stub("file_write", ToolPermission.sensitive),
        _Stub("web_search", ToolPermission.read),
        _Stub("run_code", ToolPermission.sensitive),
        _Stub("run_shell", ToolPermission.sensitive),
        _Stub("calendar_list", ToolPermission.read),
        _Stub("macro_run", ToolPermission.sensitive),
        _Stub("time", ToolPermission.read),
        _Stub("system_info", ToolPermission.read),
    ]
    return {spec.name: _make_tool(spec) for spec in specs}


def _agent(tools: dict[str, Tool], handler=None) -> AgentCore:
    return AgentCore(
        llm_router=LLMRouter(
            local_provider=MockLLMProvider([LLMResponse(content="ok")]),
            cloud_provider=MockLLMProvider([LLMResponse(content="ok")]),
        ),
        tool_registry=ToolRegistry(tools=tools),
        memory_service=FakeMemoryService(),
        skill_registry=build_default_skill_registry(),
        permission_request_handler=handler,
    )


def _names(agent: AgentCore, task: str) -> set[str]:
    return agent._initial_tool_names(task, agent._permissions_for_turn())


def _schema_names(agent: AgentCore, task: str) -> set[str]:
    names = _names(agent, task)
    schemas = agent._schemas_for(names, agent._permissions_for_turn())
    return {s["function"]["name"] for s in schemas}


def test_skill_selection_browser_web_compound():
    """'Abra o YouTube e procure vídeos.' -> Browser + Web apenas."""
    agent = _agent(_tools(), handler=lambda _: True)
    names = _names(agent, "Abra o YouTube e procure vídeos de Python.")

    assert {"browser_open", "browser_text", "web_search", "open_url"} <= names
    # skills não relacionadas NÃO são selecionadas
    assert "file_write" not in names
    assert "run_code" not in names
    assert "run_shell" not in names
    assert "calendar_list" not in names
    assert "macro_run" not in names


def test_skill_selection_files_only():
    """'Liste os arquivos da pasta Downloads.' -> Files apenas."""
    agent = _agent(_tools(), handler=lambda _: True)
    names = _names(agent, "Liste os arquivos da minha pasta Downloads.")

    assert {"file_search", "file_read", "file_info"} <= names
    assert "run_code" not in names
    assert "run_shell" not in names
    assert "browser_open" not in names
    assert "browser_js" not in names
    assert "web_search" not in names
    assert "calendar_list" not in names
    assert "macro_run" not in names


def test_permissions_filter_before_exposure_read_only():
    """Sem handler: só tools 'read' dos skills selecionados aparecem."""
    agent = _agent(_tools())
    names = _names(agent, "Abra o YouTube e procure vídeos de Python.")

    assert "browser_text" in names  # read
    assert "web_search" in names  # read
    # write/sensível não expostos sem caminho de autorização
    assert "browser_open" not in names  # write
    assert "open_url" not in names  # write
    assert "browser_js" not in names  # sensitive
    for name in names:
        assert agent.tool_registry.get(name).permission is ToolPermission.read


def test_permissions_allow_write_with_handler():
    """Com handler, write das skills selecionadas é exposto."""
    agent = _agent(_tools(), handler=lambda _: True)
    names = _names(agent, "Abra o YouTube e procure vídeos de Python.")

    assert "browser_open" in names  # write, skill selecionada
    assert "open_url" in names
    # sensíveis de skills NÃO selecionadas continuam fora
    assert "run_code" not in names
    assert "macro_run" not in names
    assert "file_write" not in names  # Files não selecionada
    assert "calendar_list" not in names  # read, porém skill não selecionada


def test_sensitive_tool_exposed_from_selected_skill_with_handler():
    """Sensível da skill selecionada é exposto quando há caminho de confirmação."""
    agent = _agent(_tools(), handler=lambda _: True)
    skills = agent.skill_registry.select_skills_for_task("escrever um arquivo qualquer")
    assert {s.name for s in skills} == {"Files"}

    names = _names(agent, "escrever um arquivo qualquer")
    assert "file_write" in names  # sensível, mas pertence à skill Files selecionada


def test_sensitive_tool_not_exposed_without_handler():
    """Sem handler, sensíveis nunca são expostas mesmo com skill selecionada."""
    agent = _agent(_tools())
    names = _names(agent, "abrir um terminal e rodar um script")
    skills = agent.skill_registry.select_skills_for_task("abrir um terminal e rodar um script")
    assert {s.name for s in skills} == {"Shell"}
    assert "run_shell" not in names
    assert "run_code" not in names


def test_no_skill_fallback_is_safe_subset():
    """Tarefa genérica: fallback seguro (FALLBACK_TOOLS ∪ CORE), sem sensíveis."""
    agent = _agent(_tools(), handler=lambda _: True)
    names = _names(agent, "conte uma piada divertida sobre programação")

    assert names
    assert names <= (FALLBACK_TOOLS | CORE_TOOLS)
    for name in names:
        assert agent.tool_registry.get(name).permission is not ToolPermission.sensitive
    assert "browser_js" not in names
    assert "run_code" not in names
    assert "macro_run" not in names
    assert "calendar_list" not in names


def test_low_confidence_weak_tie_falls_back():
    """Empate fraco de keywords -> fallback, não expõe skill ambígua."""
    agent = _agent(_tools(), handler=lambda _: True)
    names = _names(agent, "preciso encontrar um documento")

    assert names <= (FALLBACK_TOOLS | CORE_TOOLS)
    assert "file_search" in names  # fallback oferece leitura de arquivo
    assert "file_info" not in names  # Files não foi escolhida (empate fraco)
    assert "document_search" not in names  # Documents não foi escolhida


def test_schemas_gate_excludes_non_advertised_permissions():
    """Schemas nunca expõem tool fora da autorização anunciada do turno."""
    agent = _agent(_tools(), handler=lambda _: True)
    schema_names = _schema_names(agent, "Abra o YouTube e procure vídeos de Python.")

    assert "browser_open" in schema_names  # write com handler -> anunciado
    assert "browser_js" in schema_names  # sensível da skill selecionada, com handler
    assert "run_code" not in schema_names  # shell não selecionada
    assert "file_write" not in schema_names  # files não selecionada


def test_schemas_gate_read_only_no_handler():
    """Sem handler: o schema só expõe read das skills selecionadas."""
    agent = _agent(_tools())
    schema_names = _schema_names(agent, "Abra o YouTube e procure vídeos de Python.")

    assert "browser_text" in schema_names
    assert "web_search" in schema_names
    assert "browser_js" not in schema_names
    assert "browser_open" not in schema_names
    assert "run_code" not in schema_names


@pytest.mark.anyio
async def test_selection_does_not_add_llm_calls():
    """A seleção é determinística e não adiciona chamadas ao LLM."""
    provider = MockLLMProvider(
        [
            LLMResponse(content="", tool_calls=[ToolCall(name="time", arguments={})]),
            LLMResponse(content="fim"),
        ]
    )
    agent = AgentCore(
        llm_router=LLMRouter(local_provider=provider, cloud_provider=provider),
        tool_registry=ToolRegistry(tools=_tools()),
        memory_service=FakeMemoryService(),
        skill_registry=build_default_skill_registry(),
    )
    assert _names(agent, "liste os arquivos da pasta downloads") == _names(
        agent, "liste os arquivos da pasta downloads"
    )

    result = await agent.chat("liste os arquivos da pasta downloads")

    assert result["response"] == "fim"
    # 1 chamada para o primeiro turno + 1 para o segundo (após tool). Nenhuma
    # chamada extra foi gasta com seleção.
    assert len(provider.calls) == 2


def test_skill_selection_macros_only():
    """'Quais macros estão configuradas?' -> Macros apenas."""
    agent = _agent(_tools(), handler=lambda _: True)
    skills = agent.skill_registry.select_skills_for_task("quais macros estão configuradas?")
    assert [s.name for s in skills] == ["Macros"]
    names = _names(agent, "quais macros estão configuradas?")
    assert "macro_run" in names
    assert "file_read" not in names
    assert "browser_open" not in names
    assert "web_search" not in names


def test_skill_selection_memory_reminders_compound():
    """'lembrar de comprar pão amanhã às 10' -> Memory + Reminders."""
    agent = _agent(_tools(), handler=lambda _: True)
    skills = agent.skill_registry.select_skills_for_task("lembrar de comprar pão amanhã às 10")
    assert {s.name for s in skills} == {"Memory", "Reminders"}


@pytest.mark.anyio
async def test_unknown_tool_call_rejected():
    """Modelo chama tool inexistente → mensagem de erro com alternativas."""
    from app.llm.base import ToolCall as RealToolCall

    agent = _agent(_tools(), handler=lambda _: True)
    permissions = agent._permissions_for_turn()
    allowed = {"time", "file_read", "file_search"}
    tool_call = RealToolCall(name="nope_tool", arguments={"q": 1})
    result_msg, evidence = await agent._execute_tool(
        tool_call, permissions, None, allowed
    )
    assert evidence is None
    assert "nope_tool" in result_msg.content
    assert "Use apenas" in result_msg.content


def test_schemas_for_only_returns_advertised():
    """_schemas_for never returns tools outside the provided name set."""
    agent = _agent(_tools(), handler=lambda _: True)
    all_names = {"browser_open", "browser_text", "browser_js"}
    schemas = agent._schemas_for(all_names, agent._permissions_for_turn())
    names_in_schemas = {s["function"]["name"] for s in schemas}
    assert "browser_open" in names_in_schemas
    assert "browser_js" in names_in_schemas
    assert names_in_schemas <= all_names
    # Nenhum nome fora do conjunto jamais vira schema.
    assert "web_search" not in names_in_schemas
    assert "macro_run" not in names_in_schemas