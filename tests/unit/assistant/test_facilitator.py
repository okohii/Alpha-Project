"""Testes da camada Assistant Facilitator (COMPREENDER != EXECUTAR).

Cobre: intent simples (fast path direto), intent complexa (Goal estruturado),
extração de entidades, ambiguidade (referente não resolvido), baixa confiança
(empate fraco de skills), esclarecimento com continuidade, conversa sem tool
(sem LLM/sem tools) e integração incremental com o AgentCore sem quebrar a
API de chat (cumprimento direto, Goal injetado, esclarecimento aguardando).
"""
from __future__ import annotations

import pytest

from app.agent.agent import AgentCore
from app.assistant.context import ConversationContext
from app.assistant.entities import EntityExtractor
from app.assistant.facilitator import (
    AssistantFacilitator,
    format_goal_context,
)
from app.assistant.intent import Request
from app.llm.base import LLMResponse
from app.llm.mock import MockLLMProvider
from app.llm.router import LLMRouter
from app.skills.catalog import build_default_skill_registry
from app.tools.base import Tool
from app.tools.registry import ToolRegistry


class FakeMemoryService:
    async def search_memories(self, query: str, limit: int = 5):
        return []

    async def load_profile(self, limit: int = 50):
        return []

    async def save_episode(
        self, user_message: str, response: str, tool_names: list[str] | None = None
    ):
        return None


@pytest.fixture
def facilitator() -> AssistantFacilitator:
    registry = build_default_skill_registry()
    return AssistantFacilitator(
        skill_registry=registry, context=ConversationContext()
    )


def _agent(provider: MockLLMProvider, tools: dict[str, Tool] | None = None) -> AgentCore:
    return AgentCore(
        llm_router=LLMRouter(local_provider=provider, cloud_provider=provider),
        tool_registry=ToolRegistry(tools=tools or {}),
        memory_service=FakeMemoryService(),
    )


# ---- 1. Intent simples: fast path direto, sem LLM e sem tools ----

@pytest.mark.anyio
async def test_simple_greeting_returns_direct(facilitator: AssistantFacilitator):
    outcome = await facilitator.process(Request(text="olá", conversation_id="c1"))

    assert outcome.kind == "direct"
    assert outcome.intent.name == "greeting"
    assert outcome.response.startswith("Oi!")
    assert outcome.goal is None


@pytest.mark.anyio
async def test_thanks_and_farewell_are_direct(facilitator: AssistantFacilitator):
    thanks = await facilitator.process(Request(text="obrigado", conversation_id="c1"))
    bye = await facilitator.process(Request(text="tchau", conversation_id="c1"))

    assert thanks.kind == "direct" and thanks.intent.name == "thanks"
    assert bye.kind == "direct" and bye.intent.name == "farewell"


# ---- 2. Intent complexa: vira Goal estruturado (execução fica com o Agent) ----

@pytest.mark.anyio
async def test_complex_request_becomes_structured_goal(
    facilitator: AssistantFacilitator,
):
    outcome = await facilitator.process(
        Request(text="Abra o Chrome e procure por notícias sobre IA", conversation_id="c2")
    )

    assert outcome.kind == "goal"
    assert outcome.intent.name == "web_search"
    assert outcome.intent.confidence >= 0.6
    assert len(outcome.goal.tasks) == 2
    # Multi-step (Fase 4.2): abrir o navegador + pesquisar.
    search_task = [task for task in outcome.goal.tasks if task.tool_hint == "web_search"]
    assert search_task, "deve existir uma task de web_search"
    assert search_task[0].entities["query"] == "notícias sobre IA"
    assert search_task[0].required_permission == "read"


@pytest.mark.anyio
async def test_goal_context_is_structured_serialization(
    facilitator: AssistantFacilitator,
):
    outcome = await facilitator.process(
        Request(text="Abra o Chrome e procure por notícias sobre IA", conversation_id="c2")
    )
    block = format_goal_context(outcome.goal)

    assert "PLANO ESTRUTURADO DO FACILITADOR" in block
    assert "intent: web_search" in block
    assert "query: notícias sobre IA" in block
    assert "etapa: web_search" in block


# ---- 3. Extração de entidades (determinística, nunca inventa) ----

def test_entity_extraction_browser_and_query():
    entities = EntityExtractor().extract(
        "Abra o Chrome e procure por notícias sobre IA"
    )

    assert entities["browser"].value == "Chrome" and entities["browser"].resolved
    assert entities["query"].value == "notícias sobre IA" and entities["query"].resolved


def test_entity_extraction_contact_and_referent():
    entities = EntityExtractor().extract("mande isso para o João")

    assert entities["referent"].value == "isso"
    assert entities["referent"].resolved is False
    # _find_contact normaliza acentos (João -> Joao) por robustez.
    assert entities["contact"].value == "Joao"
    assert entities["contact"].resolved is False


def test_entity_extraction_app():
    entities = EntityExtractor().extract("abra o spotify")
    assert entities["app"].value == "Spotify"


def test_entity_extraction_nothing_invented():
    assert EntityExtractor().extract("olá tudo bem") == {}


# ---- 4. Ambiguidade: referente/contato não resolvidos pedem esclarecimento ----

@pytest.mark.anyio
async def test_unresolved_referent_asks_for_clarification(
    facilitator: AssistantFacilitator,
):
    outcome = await facilitator.process(
        Request(text="mande isso para o João", conversation_id="c3")
    )

    assert outcome.kind == "clarification"
    assert outcome.intent.needs_clarification is True
    assert "isso" in outcome.intent.clarification_reason
    assert "esclarecer" in outcome.response
    # Nada foi executado: não há goal.
    assert outcome.goal is None


# ---- 5. Baixa confiança: empate fraco de skills = fallback seguro ----

@pytest.mark.anyio
async def test_low_confidence_weak_skill_tie_clarifies(
    facilitator: AssistantFacilitator,
):
    outcome = await facilitator.process(
        Request(text="lembra da rotina", conversation_id="c4")
    )

    assert outcome.intent.confidence == 0.2
    assert outcome.kind == "clarification"
    assert "certeza" in outcome.intent.clarification_reason
    assert "reformule" in outcome.response


# ---- 6. Esclarecimento com continuidade (não repetir o pedido) ----

@pytest.mark.anyio
async def test_clarification_then_answer_fills_slot(
    facilitator: AssistantFacilitator,
):
    first = await facilitator.process(Request(text="procure sobre isso", conversation_id="c5"))
    assert first.kind == "clarification"

    second = await facilitator.process(
        Request(text="é o último projeto", conversation_id="c5")
    )

    assert second.kind == "goal"
    assert second.intent.name == "web_search"
    assert second.intent.entities.get("query") == "último projeto"
    task = second.goal.tasks[0]
    assert task.entities["query"] == "último projeto"


# ---- 7. Conversa sem tool: direta, sem LLM e sem planejamento ----

@pytest.mark.anyio
async def test_direct_question_goes_to_llm(facilitator: AssistantFacilitator):
    outcome = await facilitator.process(
        Request(text="qual é a capital do Brasil", conversation_id="c6")
    )

    assert outcome.kind == "llm_answer"
    assert outcome.intent.name == "direct_question"
    assert outcome.intent.suggested_skill is None
    assert outcome.goal is None
    assert outcome.response is None


# ---- 8. Integração com o AgentCore (API de chat preservada) ----

@pytest.mark.anyio
async def test_agent_integration_greeting_is_direct_and_fast():
    """Cumprimento responde sem LLM: nenhuma tool nem turno de modelo."""
    provider = MockLLMProvider([])
    agent = _agent(provider)
    agent.facilitator = AssistantFacilitator(
        skill_registry=build_default_skill_registry()
    )

    result = await agent.chat("olá")

    assert result["response"] == "Oi! No que posso ajudar?"
    assert result["tools_used"] == []
    assert result["facilitator"] is True
    assert result["memory_created"] is False
    # Sinais de observabilidade do bloco direto.
    assert result["conversation_id"]


@pytest.mark.anyio
async def test_agent_integration_simple_question_answered_by_llm_default():
    """Pergunta factual gera turno de LLM real, sem expor ferramentas."""
    calls: list = []

    class CapturingProvider:
        async def complete(
            self, messages: list, tools: list | None = None
        ) -> LLMResponse:
            calls.append(messages)
            return LLMResponse(content="Brasília.")

    agent = _agent(CapturingProvider())  # type: ignore[arg-type]
    agent.facilitator = AssistantFacilitator(
        skill_registry=build_default_skill_registry()
    )
    result = await agent.chat("qual é a capital do Brasil")

    assert result["response"] == "Brasília."
    assert calls, "pergunta simples deve gerar pelo menos 1 turno de LLM"
    assert result["tools_used"] == []
    assert result["exposed_tools"] == []
    assert result["tool_selection_status"] == "unavailable"


@pytest.mark.anyio
async def test_facilitator_multi_step_goal():
    """'abra X e pesquise Y' produz um Goal com 2 Tasks (Fase 4.2)."""
    facilitator = AssistantFacilitator(
        skill_registry=build_default_skill_registry()
    )
    outcome = await facilitator.process(
        Request(text="abra o chrome e pesquise notícias sobre IA", conversation_id="c-multi")
    )

    assert outcome.kind == "goal"
    assert outcome.goal is not None
    assert len(outcome.goal.tasks) == 2
    assert outcome.goal.tasks[0].tool_hint != outcome.goal.tasks[1].tool_hint


@pytest.mark.anyio
async def test_agent_integration_goal_is_injected_and_runs_loop():
    """Goal injeta o bloco estruturado e segue o loop normal de execução."""
    calls: list = []

    class CapturingProvider:
        async def complete(
            self, messages: list, tools: list | None = None
        ) -> LLMResponse:
            calls.append(messages)
            return LLMResponse(content="busca concluída")

        async def stream_turn(
            self, messages: list, tools: list | None = None
        ) -> LLMResponse:
            return self.complete(messages, tools)

    agent = _agent(CapturingProvider())  # type: ignore[arg-type]
    agent.facilitator = AssistantFacilitator(
        skill_registry=build_default_skill_registry()
    )

    result = await agent.chat("Abra o Chrome e procure por notícias sobre IA")

    system_blocks = [m for m in calls[0] if m.role == "system"]
    assert any("PLANO ESTRUTURADO DO FACILITADOR" in m.content for m in system_blocks)
    assert any("query: notícias sobre IA" in m.content for m in system_blocks)
    assert result["response"] == "busca concluída"

    # O Facilitator NÃO executou tools nem decidiu permissão: o loop real fez tudo.
    assert "web_search" in result["tools_used"] or result["tools_used"] == []


@pytest.mark.anyio
async def test_agent_integration_ambiguity_waits_for_user_input():
    """Ambiguidade emite waiting_input e retorna a pergunta sem executar nada."""
    provider = MockLLMProvider([])
    agent = _agent(provider)
    agent.facilitator = AssistantFacilitator(
        skill_registry=build_default_skill_registry()
    )

    result = await agent.chat("mande isso para o João")

    assert "não consigo identificar o que é 'isso'" in result["response"]
    assert result["tools_used"] == []
    assert result["facilitator"] is True