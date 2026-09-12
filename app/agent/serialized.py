from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from app.agent.agent import AgentCore


class SerializedAgentCore(AgentCore):
    """AgentCore com isolamento de estado operacional entre turnos.

    O AgentCore atual mantém algumas trilhas de execução em atributos de
    instância (``_tools_used``, ``_evidence`` e ``_security_log``). Isso é
    seguro quando há um único turno por vez, mas duas chamadas concorrentes ao
    mesmo agente podem sobrescrever essas estruturas e contaminar a resposta.

    O lock cobre o turno inteiro, inclusive o consumo do async generator de
    ``chat_stream``. Assim um agente compartilhado por CLI, overlay ou avatar
    nunca mistura evidências, tools usadas ou auditoria de uma execução com
    outra.
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


__all__ = ["SerializedAgentCore"]
