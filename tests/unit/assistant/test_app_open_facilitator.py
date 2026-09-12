"""Facilitator: 'abrir bloco de notas' vira Goal app_open sem esclarecimento.

O nome do aplicativo pode ser livre ("bloco de notas", "notepad") — a
resolução do executável fica com a ferramenta open_app + catálogo desktop,
não com um dicionário fixo de entidades.
"""
from __future__ import annotations

import pytest

from app.assistant.facilitator import AssistantFacilitator, format_goal_context
from app.assistant.intent import Request
from app.skills.catalog import build_default_skill_registry


@pytest.fixture
def facilitator() -> AssistantFacilitator:
    return AssistantFacilitator(skill_registry=build_default_skill_registry())


@pytest.mark.anyio
async def test_abrir_bloco_de_notas_is_app_open_goal(facilitator):
    outcome = await facilitator.process(
        Request(text="abrir bloco de notas", conversation_id="d1")
    )

    assert outcome.kind == "goal"
    assert outcome.intent.name == "app_open"
    assert outcome.intent.suggested_skill == "computer"
    assert outcome.intent.needs_clarification is False
    assert outcome.goal is not None
    assert outcome.goal.tasks[0].tool_hint == "open_app"

    block = format_goal_context(outcome.goal)
    assert "intent: app_open" in block
    assert "etapa: open_app" in block


@pytest.mark.anyio
async def test_app_open_no_required_slot_does_not_clarify(facilitator):
    """App descentralizado nunca mais gera 'faltam informações: app'."""
    outcome = await facilitator.process(
        Request(text="abra o bloco de notas", conversation_id="d2")
    )
    assert outcome.kind == "goal"
    assert "esclarecer" not in (outcome.response or "")


@pytest.mark.anyio
async def test_known_app_entity_is_extracted(facilitator):
    outcome = await facilitator.process(
        Request(text="abra o bloco de notas", conversation_id="d3")
    )
    assert outcome.kind == "goal"
    assert outcome.intent.entities.get("app") == "Bloco de Notas"