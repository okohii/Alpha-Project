from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from typing import Any

from app.agent.agent import AgentCore
from app.core.events import EventType
from app.llm.base import ExecutionEvidence, LLMMessage, LLMProvider, LLMResponse

_TOOL_INTENT_RE = re.compile(
    r"(?:vou|vamos|irei|iremos|usarei|utilizarei)\s+[^.\n]{0,180}",
    re.IGNORECASE,
)
_SYNTHETIC_TOOL_RESPONSE_RE = re.compile(
    r"<\s*(?:tool_response|tool_result|function_response)\b|"
    r"\[\s*(?:resultado da ferramenta|tool_response)\b",
    re.IGNORECASE,
)
_WEATHER_CLAIM_RE = re.compile(
    r"\b(?:previs[aã]o(?:\s+do\s+tempo)?|clima|temperatura|chuva|tempo\s+(?:de\s+hoje|hoje|amanh[aã]))\b",
    re.IGNORECASE,
)
_WEATHER_EVIDENCE_TOOLS = frozenset(
    {"web_search", "browser_text", "browser_html", "browser_js", "read_ui", "verify_screen"}
)


class SerializedAgentCore(AgentCore):
    """AgentCore com isolamento operacional e integridade de tool calls."""

    _conversation_by_bus: dict[int, str] = {}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._turn_lock = asyncio.Lock()

    def _conversation_id_for_turn(self, conversation_id: str | None) -> str:
        if conversation_id:
            return conversation_id
        bus = getattr(self, "event_bus", None)
        key = id(bus) if bus is not None else id(self)
        existing = self._conversation_by_bus.get(key)
        if existing is not None:
            return existing
        from uuid import uuid4
        created = str(uuid4())
        self._conversation_by_bus[key] = created
        return created

    async def chat(self, message: str, conversation_id: str | None = None) -> dict[str, Any]:
        async with self._turn_lock:
            return await super().chat(message, self._conversation_id_for_turn(conversation_id))

    async def chat_stream(self, message: str, conversation_id: str | None = None) -> AsyncIterator[Any]:
        async with self._turn_lock:
            conversation_id = self._conversation_id_for_turn(conversation_id)
            async for event in super().chat_stream(message, conversation_id):
                yield event

    async def _provider_turn(
        self,
        provider: LLMProvider,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]],
        stream_tokens: bool,
    ) -> LLMResponse:
        response = await super()._provider_turn(provider, messages, tools, stream_tokens)
        if response.tool_calls or not response.content or not tools:
            return response

        content = response.content.strip()
        available_names = self._available_tool_names(tools)
        lower = content.lower()
        mentions_known_tool = any(name.lower() in lower for name in available_names)
        strong_intent = bool(_TOOL_INTENT_RE.search(content)) and mentions_known_tool

        if _SYNTHETIC_TOOL_RESPONSE_RE.search(content):
            self._emit(EventType.agent_progress, {
                "kind": "synthetic_tool_response_blocked",
                "available_tools": sorted(available_names),
            })
            return LLMResponse(
                content="Não posso considerar uma ferramenta executada sem uma chamada nativa real.",
                tool_calls=None,
                raw=response.raw,
            )

        if not strong_intent:
            return response

        self._emit(EventType.agent_progress, {
            "kind": "tool_intent_without_call",
            "available_tools": sorted(available_names),
        })
        retry_messages = list(messages)
        retry_messages.append(LLMMessage(
            role="system",
            content=(
                "INTEGRIDADE DE TOOL CALL: a resposta anterior mencionou uma ferramenta "
                "disponível, mas não emitiu uma chamada nativa. Se a tarefa exige essa "
                "ferramenta, emita UMA tool call nativa agora. Não escreva JSON, XML, "
                "<tool_response>, <tool_result> ou simulação textual. Se não conseguir "
                "emitir a chamada nativa, responda honestamente sem alegar execução."
            ),
        ))
        retry = await super()._provider_turn(provider, retry_messages, tools, stream_tokens)
        if not retry.tool_calls:
            self._emit(EventType.agent_progress, {
                "kind": "tool_intent_unresolved",
                "available_tools": sorted(available_names),
            })
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
        return any(name in lower for name in available) and bool(_TOOL_INTENT_RE.search(content))

    @staticmethod
    def _scrub_synthetic_tool_response(content: str) -> str:
        if not content:
            return content
        if _SYNTHETIC_TOOL_RESPONSE_RE.search(content):
            return "Não posso considerar uma ferramenta executada sem uma chamada nativa real."
        return content

    def _expand_tools(self, allowed: set[str], called: list[str]) -> set[str]:
        return set(allowed)

    async def _load_history(self, conversation_id: str, limit: int) -> list[LLMMessage]:
        # O AgentCore antigo chama com 30; o orçamento configurado deve ser a
        # autoridade final para manter o contexto curto e reduzir latência.
        return await super()._load_history(
            conversation_id,
            limit=max(1, min(limit, self.settings.agent_history_limit)),
        )

    def _apply_honesty_gate(
        self,
        content: str,
        evidence: list[ExecutionEvidence],
    ) -> str:
        # Um open_url/browser_open bem-sucedido prova apenas abertura da URL.
        # Não prova que uma previsão/clima foi lida ou verificada.
        if content and _WEATHER_CLAIM_RE.search(content):
            successful = [item for item in evidence if item.success]
            if successful and not any(item.tool.split("(", 1)[0] in _WEATHER_EVIDENCE_TOOLS for item in successful):
                self._emit(EventType.honesty_gate, {
                    "claim": "weather_result",
                    "executed": True,
                    "verified": False,
                })
                return (
                    "Abri a página solicitada, mas não consegui verificar a previsão "
                    "do tempo a partir do conteúdo da página."
                )
        return super()._apply_honesty_gate(content, evidence)

    async def _save_turn(
        self,
        conversation_id: str,
        user_message: str,
        turn_messages: list[LLMMessage],
    ) -> None:
        await self._save_message(conversation_id, "user", user_message)
        for message in turn_messages:
            if message.role not in {"assistant", "tool"}:
                continue
            await self._save_message(
                conversation_id,
                message.role,
                self._scrub_synthetic_tool_response(message.content),
                tool_calls=message.tool_calls,
            )


__all__ = ["SerializedAgentCore"]
