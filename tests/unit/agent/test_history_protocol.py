"""Regressões para o protocolo histórico de tool calling.

Um assistant(tool_calls) sem os respectivos resultados tool no histórico
posterior deixa o próximo turno com contexto causal incompleto e pode induzir
o modelo a tratar uma ação antiga como ainda pendente ou já concluída.
"""
from __future__ import annotations

import json

import pytest

from app.agent.agent import AgentCore
from app.llm.base import LLMMessage, ToolCall
from app.llm.router import LLMRouter
from app.tools.registry import ToolRegistry


class _Provider:
    async def complete(self, messages, tools=None, temperature=0.2):
        raise AssertionError("não deve ser chamado neste teste")


@pytest.mark.anyio
async def test_save_turn_persists_tool_results_after_assistant_tool_calls():
    saved: list[tuple[str, str, str]] = []

    class _Session:
        def add(self, row):
            saved.append((row.role, row.content, row.conversation_id))

        async def commit(self):
            return None

    agent = AgentCore(
        llm_router=LLMRouter(local_provider=_Provider(), cloud_provider=_Provider()),
        tool_registry=ToolRegistry(tools={}),
        db_session=_Session(),
    )

    call = ToolCall(name="time", arguments={})
    await agent._save_turn(
        "conv-1",
        "que horas são?",
        [
            LLMMessage(role="assistant", content="", tool_calls=[call]),
            LLMMessage(
                role="tool",
                content=json.dumps(
                    {
                        "type": "function_response",
                        "name": "time",
                        "success": True,
                        "response": {"hour": 21},
                    }
                ),
            ),
            LLMMessage(role="assistant", content="São 21h."),
        ],
    )

    roles = [role for role, _, _ in saved]
    assert roles == ["user", "assistant", "tool", "assistant"]
    assert '"name": "time"' in saved[2][1]
    assert '"success": true' in saved[2][1]
