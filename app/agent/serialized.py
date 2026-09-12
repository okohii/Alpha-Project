from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from typing import Any

from app.agent.agent import AgentCore
from app.core.events import EventType
from app.llm.base import LLMMessage, LLMProvider, LLMResponse


_TOOL_INTENT_RE = re.compile(
    r"(?:vou|vamos|irei|iremos|usarei|utilizarei|vou\s+usar|vou\s+realizar|"
    r"vou\s+fazer|vou\s+pesquisar|vou\s+consultar|vou\s+abrir|vou\s+salvar|"
    r"vou\s+executar|vou\s+verificar|vou\s+buscar)\s+[^.\n]{0,180}",
    re.IGNORECASE,
)


class SerializedAgentCore(AgentCore):
    """AgentCore com isolamento operacional e integridade de tool calls.

    Além de serializar turnos e preservar ``role=tool`` no histórico, esta
    camada impede que o modelo trate uma descrição textual de uma ferramenta
    como se ela tivesse sido executada. Quando o modelo diz que vai usar uma
    tool, mas não emite uma chamada nativa, fazemos UMA nova passagem pedindo
    explicitamente o tool calling nativo. Se falhar novamente, o texto não é
    convertido em execução.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._turn_lock = asyncio.Lock()

    async def chat(self, message: str, conversation_id: str | None = None) -> dict[str, Any]:
        async with self._turn_lock:
            if conversation_id is None:
                conversation_id = getattr(self, "_default_conversation_id", None)
                if conversation_id is None:
                    from uuid import uuid4

                    conversation_id = str(uuid4())
                    self._default_conversation_id = conversation_id
            return await super().chat(message, conversation_id)

    async def chat_stream(
        self,
        message: str,
        conversation_id: str | None = None,
    ) -> AsyncIterator[Any]:
        async with self._turn_lock:
            if conversation_id is None:
                conversation_id = getattr(self, "_default_conversation_id", None)
                if conversation_id is None:
                    from uuid import uuid4

                    conversation_id = str(uuid4())
                    self._default_conversation_id = conversation_id
            async for event in super().chat_stream(message, conversation_id):
                yield event

    async def _provider_turn(
        self,
        provider: LLMProvider,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]],
        stream_tokens: bool,
    ) -> LLMResponse:
        """Exige tool calling nativo quando o modelo só descreve a ação."""
        response = await super()._provider_turn(provider, messages, tools, stream_tokens)
        if response.tool_calls or not response.content or not tools:
            return response
        if not self._looks_like_tool_intent(response.content, tools):
            return response

        available_names = self._available_tool_names(tools)
        self._emit(
            EventType.agent_progress,
            {
                "kind": "tool_intent_without_call",
                "available_tools": sorted(available_names),
            },
        )
        retry_messages = list(messages)
        retry_messages.append(
            LLMMessage(
                role="system",
                content=(
                    "INTEGRIDADE DE TOOL CALL: sua resposta anterior descreveu uma "
                    "ferramenta, mas nenhuma chamada nativa foi emitida. NÃO diga que "
                    "vai usar a ferramenta. Se a tarefa realmente exige uma ferramenta "
                    "disponível, emita agora uma tool call nativa. Se não exigir, responda "
                    "sem alegar que pesquisou, abriu, salvou ou executou algo. "
                    "Nunca escreva JSON de tool call no texto."
                ),
            )
        )
        retry = await super()._provider_turn(provider, retry_messages, tools, stream_tokens)
        if not retry.tool_calls:
            self._emit(
                EventType.agent_progress,
                {
                    "kind": "tool_intent_unresolved",
                    "available_tools": sorted(available_names),
                },
            )
        return retry

    @staticmethod
    def _available_tool_names(tools: list[dict[str, Any]]) -> set[str]:
        names: set[str] = set()
        for schema in tools:
            function = schema.get("function") if isinstance(schema, dict) else None
            if isinstance(function, dict) and isinstance(function.get("name"), str):
                names.add(function["name"])
        return names

    @classmethod
    def _looks_like_tool_intent(cls, content: str, tools: list[dict[str, Any]]) -> bool:
        available = {name.lower() for name in cls._available_tool_names(tools)}
        if not available:
            return False
        lower = content.lower()
        # O modelo precisa mencionar uma tool conhecida ou uma intenção forte
        # de ação/pesquisa. Isso evita re-tentativas em conversa normal.
        mentions_tool = any(name in lower for name in available)
        strong_intent = bool(_TOOL_INTENT_RE.search(content))
        return mentions_tool or strong_intent

    def _expand_tools(self, allowed: set[str], called: list[str]) -> set[str]:
        """Não abre novas skills no meio da execução.

        A seleção inicial do SkillRegistry é a única fonte de exposição. Isso
        impede que uma chamada alucinada seja usada como pivô para revelar todo
        o catálogo de outra skill durante o mesmo turno.
        """
        return set(allowed)

    async def _save_turn(
        self,
        conversation_id: str,
        user_message: str,
        turn_messages: list[LLMMessage],
    ) -> None:
        """Persiste a cadeia causal completa do turno.

        Ordem obrigatória:
        user -> assistant(tool_calls) -> tool(result) -> assistant(final)
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
