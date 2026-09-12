from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from app.agent.agent import AgentCore
from app.llm.base import LLMMessage


class SerializedAgentCore(AgentCore):
    """AgentCore com isolamento operacional entre turnos.

    O AgentCore mantém algumas trilhas de execução em atributos de instância.
    O lock impede que duas chamadas concorrentes sobrescrevam evidências,
    tools usadas, auditoria ou estado do Facilitator.

    Também corrige o protocolo persistido do histórico: uma mensagem
    ``assistant(tool_calls)`` precisa continuar acompanhada pelos respectivos
    ``tool`` resultados. Sem isso, o próximo turno recebe um contexto causal
    incompleto e pode interpretar uma ação antiga como pendente ou concluída.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._turn_lock = asyncio.Lock()

    async def chat(
        self,
        message: str,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        async with self._turn_lock:
            return await super().chat(message, conversation_id)

    async def chat_stream(
        self,
        message: str,
        conversation_id: str | None = None,
    ) -> AsyncIterator[Any]:
        async with self._turn_lock:
            async for event in super().chat_stream(message, conversation_id):
                yield event

    async def _save_turn(
        self,
        conversation_id: str,
        user_message: str,
        turn_messages: list[LLMMessage],
    ) -> None:
        """Persiste a cadeia causal completa do turno.

        Ordem obrigatória:
        user -> assistant(tool_calls) -> tool(result) -> assistant(final)

        O AgentCore original descartava ``role=tool``. Isso tornava o histórico
        incompatível com a mensagem assistant(tool_calls) que era preservada,
        criando contexto incompleto no turno seguinte.
        """
        await self._save_message(conversation_id, "user", user_message)
        for message in turn_messages:
            if message.role not in {"assistant", "tool"}:
                continue
            await self._save_message(
                conversation_id,
                message.role,
                message.content,
                tool_calls=message.tool_calls,
            )


__all__ = ["SerializedAgentCore"]
