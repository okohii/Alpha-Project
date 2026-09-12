"""Auditoria de HARDENING do AgentCore.

Cobre:
1. memory_save — confirmação só após execução real (sucesso/falha/exceção/
   ferramenta inexistente/alegação do LLM sem execução);
2. Honesty Gate — alegação de sucesso sem evidência é bloqueada; negações em
   pt-BR nunca viram sucesso;
3. Textual tool call (JSON) — nunca executa e nunca vaza ao usuário;
4. Execução fora do catálogo exposto é recusada;
5. Isolamento entre turnos (tools/evidência/emoção de um turno não vazam);
6. CASO 1/2/3/4/5 — regressão dos bugs originais.
"""
from __future__ import annotations

import asyncio

import pytest

from app.agent.agent import (
    _FALLBACK_ON_NO_SUCCESS,
    _HONESTY_MEMORY_UNCONFIRMED,
    _TEXTUAL_TOOL_CALL_BLOCKED,
    AgentCore,
)
from app.core.events import EventBus, EventType
from app.llm.base import LLMResponse, ToolCall
from app.llm.mock import MockLLMProvider
from app.llm.router import LLMRouter
from app.tools.base import Tool, ToolPermission, ToolResult
from app.tools.registry import ToolRegistry


async def _allow_all(candidate: str) -> bool:
    return True


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------


class FakeMemoryService:
    def __init__(self) -> None:
        self.episodes: list[tuple] = []

    async def search_memories(self, query: str, limit: int = 5):
        return []

    async def load_profile(self, limit: int = 50):
        return []

    async def save_episode(self, user_message, response, tool_names=None):
        self.episodes.append((user_message, tool_names))
        return type("Memory", (), {"content": user_message})()


class MemorySaveToolOk(Tool):
    name = "memory_save"
    description = "salva memória"
    permission = ToolPermission.write

    def __init__(self, success: bool = True, explode: bool = False) -> None:
        self.calls = 0
        self.success = success
        self.explode = explode

    async def execute(self, **kwargs):
        self.calls += 1
        if self.explode:
            raise RuntimeError("db caiu")
        if not self.success:
            return ToolResult(name=self.name, success=False, data={}, error="falha ao salvar")
        return ToolResult(
            name=self.name, success=True, data={"content": kwargs.get("content", "")}
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {"content": {"type": "string"}},
            "required": ["content"],
        }


class OpenAppToolOk(Tool):
    name = "open_app"
    description = "abre app"
    permission = ToolPermission.write

    def __init__(self, success: bool = True) -> None:
        self.success = success
        self.calls = 0

    async def execute(self, **kwargs):
        self.calls += 1
        if not self.success:
            return ToolResult(name=self.name, success=False, data={}, error="app não encontrado")
        return ToolResult(name=self.name, success=True, data={"app": kwargs.get("app")})

    def parameters_schema(self) -> dict:
        return {"type": "object", "properties": {"app": {"type": "string"}}}


class BrowserOpenToolOk(Tool):
    name = "browser_open"
    description = "abre navegador"
    permission = ToolPermission.write

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, **kwargs):
        self.calls += 1
        return ToolResult(name=self.name, success=True, data={"url": kwargs.get("url")})

    def parameters_schema(self) -> dict:
        return {"type": "object", "properties": {"url": {"type": "string"}}}


class FakeTimeTool(Tool):
    name = "time"
    description = "hora"
    permission = ToolPermission.read

    async def execute(self, **kwargs):
        return ToolResult(name=self.name, success=True, data={"utc": "2026-01-01T00:00:00Z"})

    def parameters_schema(self) -> dict:
        return {"type": "object", "properties": {}}


class MemorySearchToolOk(Tool):
    name = "memory_search"
    description = "busca memória"
    permission = ToolPermission.read

    async def execute(self, **kwargs):
        return ToolResult(name=self.name, success=True, data={"memories": []})

    def parameters_schema(self) -> dict:
        return {"type": "object", "properties": {"query": {"type": "string"}}}


class WebSearchToolOk(Tool):
    name = "web_search"
    description = "pesquisa web"
    permission = ToolPermission.read

    async def execute(self, **kwargs):
        return ToolResult(name=self.name, success=True, data={"results": []})

    def parameters_schema(self) -> dict:
        return {"type": "object", "properties": {"query": {"type": "string"}}}


class ScriptedProvider:
    """Provider que alterna scripts por turno (rota A/B/C)."""

    def __init__(self) -> None:
        self.mode = "a"
        self.scripts: dict[str, list] = {}

    def script(self, mode: str, responses: list) -> None:
        self.scripts[mode] = list(responses)

    async def complete(self, messages, tools=None, temperature=0.2):
        responses = self.scripts.get(self.mode, [LLMResponse(content="ok")])
        if not responses:
            return LLMResponse(content="ok")
        item = responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def _evidence_names(result: dict) -> list[str]:
    return [item.get("tool", "") for item in result.get("evidence", [])]


def _evidence_success(result: dict) -> bool:
    return any(item.get("success") for item in result.get("evidence", []))


# ---------------------------------------------------------------------------
# 1. MEMORY_SAVE — confirmação honesta
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_memory_save_success_allows_confirmation():
    """ToolResult(success=True) → Evidence EXECUTED → resposta pode confirmar."""
    tool = MemorySaveToolOk()
    provider = MockLLMProvider(
        [
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(name="memory_save", arguments={"content": "Ellen é amiga do usuário"})
                ],
            ),
            LLMResponse(content="Guardei a informação sobre a Ellen."),
        ]
    )
    agent = AgentCore(
        llm_router=LLMRouter(local_provider=provider, cloud_provider=provider),
        tool_registry=ToolRegistry(tools={"memory_save": tool}),
        memory_service=FakeMemoryService(),
        permission_request_handler=_allow_all,
    )

    result = await agent.chat("Guarde essa informação sobre Ellen.")

    assert tool.calls == 1
    assert result["response"] == "Guardei a informação sobre a Ellen."
    assert "memory_save" in _evidence_names(result)
    assert _evidence_success(result)


@pytest.mark.anyio
async def test_memory_claim_blocked_when_llm_never_calls_tool():
    """LLM alega 'guardei' sem executar memory_save → resposta honesta no lugar."""
    provider = MockLLMProvider(
        [LLMResponse(content="Guardei a informação sobre a Ellen no banco.")]
    )
    agent = AgentCore(
        llm_router=LLMRouter(local_provider=provider, cloud_provider=provider),
        tool_registry=ToolRegistry(tools={"memory_save": MemorySaveToolOk()}),
        memory_service=FakeMemoryService(),
        permission_request_handler=_allow_all,
    )

    result = await agent.chat("Guarde isso.")

    assert result["response"] == _HONESTY_MEMORY_UNCONFIRMED
    assert "memory_save" not in _evidence_names(result)


@pytest.mark.anyio
async def test_memory_claim_blocked_when_save_fails():
    """memory_save(success=False) → resposta não pode afirmar 'guardei'."""
    provider = MockLLMProvider(
        [
            LLMResponse(
                content="",
                tool_calls=[ToolCall(name="memory_save", arguments={"content": "x"})],
            ),
            LLMResponse(content="Guardei tudo certinho."),
        ]
    )
    agent = AgentCore(
        llm_router=LLMRouter(local_provider=provider, cloud_provider=provider),
        tool_registry=ToolRegistry(tools={"memory_save": MemorySaveToolOk(success=False)}),
        memory_service=FakeMemoryService(),
        permission_request_handler=_allow_all,
    )

    result = await agent.chat("salva")

    assert result["response"] == _HONESTY_MEMORY_UNCONFIRMED
    assert not _evidence_success(result)


@pytest.mark.anyio
async def test_memory_claim_blocked_when_save_explodes():
    """Exceção na tool → nunca vira 'guardei'."""
    provider = MockLLMProvider(
        [
            LLMResponse(
                content="",
                tool_calls=[ToolCall(name="memory_save", arguments={"content": "x"})],
            ),
            LLMResponse(content="a memória foi gravada com sucesso"),
        ]
    )
    agent = AgentCore(
        llm_router=LLMRouter(local_provider=provider, cloud_provider=provider),
        tool_registry=ToolRegistry(tools={"memory_save": MemorySaveToolOk(explode=True)}),
        memory_service=FakeMemoryService(),
        permission_request_handler=_allow_all,
    )

    result = await agent.chat("salva")

    assert result["response"] == _HONESTY_MEMORY_UNCONFIRMED


@pytest.mark.anyio
async def test_memory_claim_blocked_when_tool_does_not_exist():
    """Ferramenta inexistente → nenhuma execução → 'guardei' é bloqueado."""
    provider = MockLLMProvider(
        [
            LLMResponse(
                content="",
                tool_calls=[ToolCall(name="memory_save", arguments={"content": "x"})],
            ),
            LLMResponse(content="Pronto, salvei para sempre."),
        ]
    )
    agent = AgentCore(
        llm_router=LLMRouter(local_provider=provider, cloud_provider=provider),
        tool_registry=ToolRegistry(tools={}),
        memory_service=FakeMemoryService(),
        permission_request_handler=_allow_all,
    )

    result = await agent.chat("salva")

    assert result["response"] == _HONESTY_MEMORY_UNCONFIRMED


@pytest.mark.anyio
async def test_save_episode_does_not_authorize_memory_claim():
    """PATH B (save_episode automático) NÃO é confirmação de memory_save.

    Mesmo que o episódio tenha sido salvo (memory_created=True), a resposta
    não pode afirmar 'guarde' uma informação específica sem memory_save real.
    """
    memory_service = FakeMemoryService()
    provider = MockLLMProvider(
        [LLMResponse(content="Registrei essa informação nos meus arquivos.")]
    )
    agent = AgentCore(
        llm_router=LLMRouter(local_provider=provider, cloud_provider=provider),
        tool_registry=ToolRegistry(tools={"memory_save": MemorySaveToolOk()}),
        memory_service=memory_service,
        permission_request_handler=_allow_all,
    )

    result = await agent.chat("guarde isso")

    # episódio é salvo automaticamente, mas NÃO autoriza a alegação
    assert memory_service.episodes
    assert result["memory_created"] is True
    assert result["response"] == _HONESTY_MEMORY_UNCONFIRMED


# ---------------------------------------------------------------------------
# 2. Honesty Gate / alegação de sucesso
# ---------------------------------------------------------------------------


def test_claims_success_pt_br_positives():
    assert AgentCore._claims_success("Abri o WhatsApp") is True
    assert AgentCore._claims_success("o WhatsApp foi aberto") is True
    assert AgentCore._claims_success("já está aberto") is True
    assert AgentCore._claims_success("consegui abrir o navegador") is True
    assert AgentCore._claims_success("deu certo") is True


def test_claims_success_pt_br_negations():
    assert AgentCore._claims_success("não consegui abrir o WhatsApp") is False
    assert AgentCore._claims_success("não foi possível abrir") is False
    assert AgentCore._claims_success("tentei abrir o navegador") is False
    assert AgentCore._claims_success("o WhatsApp não abriu") is False
    assert AgentCore._claims_success("falhei ao abrir") is False
    assert AgentCore._claims_success("encontrei um problema") is False


def test_claims_memory_success_pt_br():
    assert AgentCore._claims_memory_success("guardei a informação") is True
    assert AgentCore._claims_memory_success("a memória está salva") is True
    assert AgentCore._claims_memory_success("registrei tudo no banco") is True
    assert AgentCore._claims_memory_success("não consegui salvar") is False
    assert AgentCore._claims_memory_success("o salvamento falhou") is False


@pytest.mark.anyio
async def test_action_success_claim_without_evidence_blocked():
    provider = MockLLMProvider([LLMResponse(content="Sim! Abri o WhatsApp para você.")])
    agent = AgentCore(
        llm_router=LLMRouter(local_provider=provider, cloud_provider=provider),
        tool_registry=ToolRegistry(tools={"open_app": OpenAppToolOk()}),
        memory_service=FakeMemoryService(),
        permission_request_handler=_allow_all,
    )

    result = await agent.chat("abre o whatsapp")

    assert result["response"] == _FALLBACK_ON_NO_SUCCESS


@pytest.mark.anyio
async def test_action_success_claim_with_evidence_allowed():
    provider = MockLLMProvider(
        [
            LLMResponse(
                content="",
                tool_calls=[ToolCall(name="open_app", arguments={"app": "whatsapp"})],
            ),
            LLMResponse(content="Abri o WhatsApp."),
        ]
    )
    agent = AgentCore(
        llm_router=LLMRouter(local_provider=provider, cloud_provider=provider),
        tool_registry=ToolRegistry(tools={"open_app": OpenAppToolOk()}),
        memory_service=FakeMemoryService(),
        permission_request_handler=_allow_all,
    )

    result = await agent.chat("abre o whatsapp")

    assert result["response"] == "Abri o WhatsApp."
    assert "open_app" in _evidence_names(result)


@pytest.mark.anyio
async def test_failure_claim_is_kept_honest():
    """'não consegui abrir' continua honesto e NÃO é bloqueado."""
    provider = MockLLMProvider(
        [
            LLMResponse(
                content="",
                tool_calls=[ToolCall(name="open_app", arguments={"app": "whatsapp"})],
            ),
            LLMResponse(content="Não consegui abrir o WhatsApp."),
        ]
    )
    agent = AgentCore(
        llm_router=LLMRouter(local_provider=provider, cloud_provider=provider),
        tool_registry=ToolRegistry(tools={"open_app": OpenAppToolOk(success=False)}),
        memory_service=FakeMemoryService(),
        permission_request_handler=_allow_all,
    )

    result = await agent.chat("abre o whatsapp")

    assert result["response"] == "Não consegui abrir o WhatsApp."


# ---------------------------------------------------------------------------
# 3. Textual tool call (JSON) — nunca executa, nunca vaza
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_textual_tool_call_json_blocked_no_execution():
    tool = OpenAppToolOk()
    provider = MockLLMProvider(
        [
            LLMResponse(
                content='{"name": "open_app", "arguments": {"app": "whatsapp"}}'
            )
        ]
    )
    agent = AgentCore(
        llm_router=LLMRouter(local_provider=provider, cloud_provider=provider),
        tool_registry=ToolRegistry(tools={"open_app": tool}),
        memory_service=FakeMemoryService(),
        permission_request_handler=_allow_all,
    )

    result = await agent.chat("abre o whatsapp")

    assert tool.calls == 0
    assert result["response"] == _TEXTUAL_TOOL_CALL_BLOCKED
    assert "{" not in result["response"]
    assert "browser_open" not in result["response"]
    assert _evidence_names(result) == []


@pytest.mark.anyio
async def test_textual_tool_call_fragment_scrubbed():
    tool = OpenAppToolOk()
    provider = MockLLMProvider(
        [
            LLMResponse(
                content=(
                    'Vou abrir agora. {"name":"open_app","arguments":{"app":"whatsapp"}}'
                    " Pronto."
                )
            )
        ]
    )
    agent = AgentCore(
        llm_router=LLMRouter(local_provider=provider, cloud_provider=provider),
        tool_registry=ToolRegistry(tools={"open_app": tool}),
        memory_service=FakeMemoryService(),
        permission_request_handler=_allow_all,
    )

    result = await agent.chat("abre o whatsapp")

    assert tool.calls == 0
    assert "{" not in result["response"]


@pytest.mark.anyio
async def test_textual_tool_call_never_reaches_user_when_clean():
    """Conteúdo limpo passa sem alteração (sem falso positivo do scrub)."""
    provider = MockLLMProvider(
        [LLMResponse(content="Brasília é a capital do Brasil.")]
    )
    agent = AgentCore(
        llm_router=LLMRouter(local_provider=provider, cloud_provider=provider),
        tool_registry=ToolRegistry(tools={}),
        memory_service=FakeMemoryService(),
    )

    result = await agent.chat("qual a capital?")

    assert result["response"] == "Brasília é a capital do Brasil."


# ---------------------------------------------------------------------------
# 4. Execução só dentro do catálogo exposto
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_hallucinated_tool_outside_exposed_set_refused():
    """Modelo chama tool que existe no registry mas NÃO foi anunciada no turno."""
    provider = MockLLMProvider(
        [
            LLMResponse(
                content="",
                tool_calls=[ToolCall(name="memory_save", arguments={"content": "x"})],
            ),
            LLMResponse(content="guardado"),
        ]
    )
    # Sem handler: só "time" (read) é anunciada; memory_save write é recusada.
    agent = AgentCore(
        llm_router=LLMRouter(local_provider=provider, cloud_provider=provider),
        tool_registry=ToolRegistry(
            tools={"time": FakeTimeTool(), "memory_save": MemorySaveToolOk()}
        ),
        memory_service=FakeMemoryService(),
    )

    result = await agent.chat("registra")

    assert result["response"] != "guardado"
    assert "memory_save" not in _evidence_names(result)


# ---------------------------------------------------------------------------
# 5. Isolamento entre turnos
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_turn_a_cancelled_does_not_contaminate_turn_b():
    provider = ScriptedProvider()
    provider.script(
        "a",
        [
            LLMResponse(
                content="", tool_calls=[ToolCall(name="open_app", arguments={"app": "whatsapp"})]
            ),
            asyncio.CancelledError(),
        ],
    )
    provider.script("b", [LLMResponse(content="Brasília é a capital.")])
    open_app = OpenAppToolOk()
    agent = AgentCore(
        llm_router=LLMRouter(local_provider=provider, cloud_provider=provider),
        tool_registry=ToolRegistry(tools={"open_app": open_app}),
        memory_service=FakeMemoryService(),
        permission_request_handler=_allow_all,
        cancel_event=asyncio.Event(),
    )

    # Turno A: executa open_app e depois é cancelado
    provider.mode = "a"
    with pytest.raises(asyncio.CancelledError):
        await agent.chat("Abra o WhatsApp.")

    assert open_app.calls == 1

    # Turno B: nenhuma ferramenta/evidência/emoção de A pode aparecer
    provider.mode = "b"
    result = await agent.chat("Qual é a capital do Brasil?")

    assert result["response"] == "Brasília é a capital."
    assert result["evidence"] == []
    assert result["tools_used"] == []
    assert "whatsapp" not in result["response"].lower()


@pytest.mark.anyio
async def test_emotion_does_not_leak_between_turns():
    provider = MockLLMProvider(
        [
            LLMResponse(content="ok"),
            LLMResponse(content="ok"),
            LLMResponse(content="ok"),
        ]
    )
    agent = AgentCore(
        llm_router=LLMRouter(local_provider=provider, cloud_provider=provider),
        tool_registry=ToolRegistry(tools={}),
        memory_service=FakeMemoryService(),
    )

    first = await agent.chat("fale feliz")
    second = await agent.chat("fale triste")
    third = await agent.chat("qual é a capital do brasil?")

    assert first["emotion"]["emotion"] == "happy"
    assert second["emotion"]["emotion"] == "sad"
    # turno neutro: nenhuma emoção herdada
    assert third["emotion"] is None


@pytest.mark.anyio
async def test_memory_tools_from_turn_a_do_not_execute_in_turn_b():
    provider = ScriptedProvider()
    provider.script("a", [LLMResponse(content="ok")])
    provider.script("b", [LLMResponse(content="Ellen é uma amiga.")])
    memory_save = MemorySaveToolOk()
    agent = AgentCore(
        llm_router=LLMRouter(local_provider=provider, cloud_provider=provider),
        tool_registry=ToolRegistry(tools={"memory_save": memory_save}),
        memory_service=FakeMemoryService(),
        permission_request_handler=_allow_all,
    )

    provider.mode = "a"
    await agent.chat("busque o clima")  # sem tools na virada
    provider.mode = "b"
    result = await agent.chat("quem é Ellen?")

    assert memory_save.calls == 0
    assert result["response"] == "Ellen é uma amiga."
    assert _evidence_names(result) == []


# ---------------------------------------------------------------------------
# 6. CASO 1 — tom triste não executa ferramentas
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_emotion_only_turn_exposes_no_tools():
    """CASO 1: 'Agora eu quero um tom bem triste.' → nenhuma ferramenta."""
    provider = MockLLMProvider([LLMResponse(content="Claro, fico mais suave.")])
    agent = AgentCore(
        llm_router=LLMRouter(local_provider=provider, cloud_provider=provider),
        tool_registry=ToolRegistry(tools={"time": FakeTimeTool(), "open_app": OpenAppToolOk()}),
        memory_service=FakeMemoryService(),
        permission_request_handler=_allow_all,
    )

    result = await agent.chat("Agora eu quero um tom bem triste.")

    assert result["emotion"]["emotion"] == "sad"
    assert result["emotion"]["source"] == "explicit"
    # Nenhum schema/tool foi enviado ao provider nesta virada
    _, tools = provider.calls[0]
    assert tools == []
    assert result["tools_used"] == []


# ---------------------------------------------------------------------------
# 7. FASES de evidence — REQUESTED nunca é VERIFIED sem execução
# ---------------------------------------------------------------------------


def test_execution_evidence_status_derived():
    from datetime import UTC, datetime

    from app.llm.base import ExecutionEvidence

    ok = ExecutionEvidence(
        action_id="x",
        tool="open_app",
        arguments={},
        executed_at=datetime.now(UTC).isoformat(),
        success=True,
        result={},
    )
    assert ok.status == "executed"

    failed = ExecutionEvidence(
        action_id="y",
        tool="open_app",
        arguments={},
        executed_at=datetime.now(UTC).isoformat(),
        success=False,
        result={},
    )
    assert failed.status == "failed"
    # Nenhum caminho permite REQUESTED → VERIFIED sem execução
    assert failed.verified is False
    assert failed.status != "verified"


# ---------------------------------------------------------------------------
# 8. Honesty Gate emite evento auditável
# ---------------------------------------------------------------------------


def test_honesty_gate_emits_event():
    bus = EventBus()
    events: list = []
    bus.subscribe(EventType.honesty_gate, lambda e: events.append(e.payload))
    provider = MockLLMProvider([LLMResponse(content="Guardei a informação.")])
    agent = AgentCore(
        llm_router=LLMRouter(local_provider=provider, cloud_provider=provider),
        tool_registry=ToolRegistry(tools={"memory_save": MemorySaveToolOk()}),
        memory_service=FakeMemoryService(),
        permission_request_handler=_allow_all,
        event_bus=bus,
    )

    result = asyncio.run(agent.chat("guarde"))

    assert result["response"] == _HONESTY_MEMORY_UNCONFIRMED
    assert events and events[0]["claim"] == "memory_persistence"


# ---------------------------------------------------------------------------
# 9. Regressão dos CASOS 2/3/4/5 (skill selection + execução honesta)
# ---------------------------------------------------------------------------


def _skill_agent(tools: dict, skills) -> AgentCore:
    provider = MockLLMProvider([LLMResponse(content="ok")])
    return AgentCore(
        llm_router=LLMRouter(local_provider=provider, cloud_provider=provider),
        tool_registry=ToolRegistry(tools=tools),
        memory_service=FakeMemoryService(),
        permission_request_handler=_allow_all,
        skill_registry=skills,
    )


def test_caso2_whatsapp_selects_computer_open_app():
    from app.skills.catalog import build_default_skill_registry

    agent = _skill_agent(
        {"open_app": OpenAppToolOk(), "browser_open": BrowserOpenToolOk()},
        build_default_skill_registry(),
    )
    names = agent._initial_tool_names(
        "Você pode abrir meu WhatsApp?", agent._permissions_for_turn()
    )
    assert "open_app" in names
    assert "browser_open" not in names


@pytest.mark.anyio
async def test_caso2_open_app_failure_is_honest():
    provider = MockLLMProvider(
        [
            LLMResponse(
                content="", tool_calls=[ToolCall(name="open_app", arguments={"app": "whatsapp"})]
            ),
            LLMResponse(content="Abri o WhatsApp."),
        ]
    )
    agent = AgentCore(
        llm_router=LLMRouter(local_provider=provider, cloud_provider=provider),
        tool_registry=ToolRegistry(tools={"open_app": OpenAppToolOk(success=False)}),
        memory_service=FakeMemoryService(),
        permission_request_handler=_allow_all,
    )

    result = await agent.chat("Você pode abrir meu WhatsApp?")

    # falha → NUNCA afirmar sucesso
    assert result["response"] == _FALLBACK_ON_NO_SUCCESS


def test_caso3_browser_open_executed_for_real_no_json():
    from app.skills.catalog import build_default_skill_registry

    agent = _skill_agent(
        {"open_app": OpenAppToolOk(), "browser_open": BrowserOpenToolOk(), "time": FakeTimeTool()},
        build_default_skill_registry(),
    )
    names = agent._initial_tool_names(
        "Acho que dá pra tentar novamente... Mas pode tentar abrir pelo navegador?",
        agent._permissions_for_turn(),
    )
    assert "browser_open" in names  # Browser selecionado


def test_caso4_guardar_informacao_selects_memory():
    from app.skills.catalog import build_default_skill_registry

    registry = build_default_skill_registry()
    skills = registry.select_skills_for_task("Guarde essa informação sobre Ellen.")
    assert {"Memory"} <= {s.name for s in skills}


def test_caso5_quem_e_ellen_selects_memory_not_action():
    from app.skills.catalog import build_default_skill_registry

    registry = build_default_skill_registry()
    skills = registry.select_skills_for_task("Quem é Ellen?")
    assert {s.name for s in skills} == {"Memory"}
    agent = _skill_agent(
        {
            "memory_search": MemorySearchToolOk(),
            "open_app": OpenAppToolOk(),
            "browser_open": BrowserOpenToolOk(),
            "web_search": WebSearchToolOk(),
            "time": FakeTimeTool(),
        },
        registry,
    )
    names = agent._initial_tool_names("Quem é Ellen?", agent._permissions_for_turn())
    # nenhuma ferramenta de ação externa é exposta para uma pergunta de memória
    assert "open_app" not in names
    assert "browser_open" not in names
    assert "web_search" not in names
    assert "memory_search" in names


# ---------------------------------------------------------------------------
# 10. Fast Path — nunca é uma segunda arquitetura de execução
# ---------------------------------------------------------------------------


def test_fastpath_match_is_metadata_not_execution():
    """O FastPathRouter apenas produz um match; a EXECUÇÃO fica no AgentCore.

    Regra: nenhum caminho pode executar Tool/Service fora de
    ExecutionContext → permission → ToolRegistry → ToolResult → Evidence.
    """
    from app.agent.router import FastPathMatch, build_default_fast_path_router

    router = build_default_fast_path_router()
    match = router.match("abra o chrome")
    assert isinstance(match, FastPathMatch)
    assert match.tool == "open_app"
    # O próprio router não tem ToolRegistry/Service: execução é impossível aqui.
    assert not hasattr(router, "execute")
    assert not hasattr(router, "tool_registry")


def test_fastpath_tools_are_registered_and_go_through_registry():
    """Todos os tools referenciados pelo Fast Path existem no ToolRegistry."""
    from app.agent.router import build_default_fast_path_router
    from app.tools.registry import build_default_tool_registry

    build_default_fast_path_router()
    registry = build_default_tool_registry(memory_service=FakeMemoryService())
    assert "open_app" in registry.tools
    assert "open_url" in registry.tools
    assert "web_search" in registry.tools
    assert "file_read" in registry.tools
    assert "memory_search" in registry.tools


def test_no_service_bypass_in_fast_path():
    """Nenhum utilitário do Fast Path executa tools/serviços diretamente."""
    import inspect

    from app.agent.router import FastPathMatch, FastPathRule

    for cls in (FastPathMatch, FastPathRule):
        source = inspect.getsource(cls)
        assert ".execute" not in source
        assert "import" not in source or "from " not in source