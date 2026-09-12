from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from typing import Any

from app.agent.agent import AgentCore
from app.core.events import EventType
from app.evidence import Evidence, EvidenceKind, VerificationPolicy, VerificationResult, VerificationService
from app.llm.base import ExecutionEvidence, LLMMessage, LLMProvider, LLMResponse, ToolCall

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

# Ferramentas cujo sucesso já representa o efeito final que o usuário pediu.
# Elas não precisam de uma segunda inferência do LLM para transformar o
# resultado em uma frase curta. Não incluímos browser/computer/messaging:
# nesses casos o ALPHA ainda precisa preservar a etapa de interpretação/
# verificação para não transformar "executado" em "verificado".
_FAST_POST_TOOL_TOOLS = frozenset({"memory_save", "file_write"})

# Ações externas em que "a tool retornou success" prova somente EXECUTADO.
# Exigem uma evidência explícita de pós-condição para virar VERIFICADO.
_STRICT_VERIFICATION_TOOLS = frozenset(
    {
        "browser_click",
        "browser_js",
        "browser_navigate",
        "open_app",
        "open_url",
        "mouse_click",
        "type_text",
        "press_key",
        "click_text",
        "run_shell",
        "run_code",
        "task_execute",
        "procedure_run",
        "macro_run",
    }
)


class SerializedAgentCore(AgentCore):
    """AgentCore com isolamento operacional e integridade de tool calls."""

    _conversation_by_bus: dict[int, str] = {}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._turn_lock = asyncio.Lock()
        self._verification_service = VerificationService(
            VerificationPolicy(require_evidence=True)
        )

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

    async def _execute_tool(
        self,
        tool_call: ToolCall,
        permissions: set[Any],
        conversation_id: str | None,
        allowed_names: set[str],
    ) -> tuple[LLMMessage, ExecutionEvidence | None]:
        """Executa a tool base e transforma o retorno em evidência verificável."""
        message, execution = await super()._execute_tool(
            tool_call, permissions, conversation_id, allowed_names
        )
        if execution is None:
            return message, None

        raw = execution.result if isinstance(execution.result, dict) else {}
        tool_name = execution.tool.split("(", 1)[0]
        verified = bool(raw.get("verified") is True or raw.get("postcondition_verified") is True)

        # Primeiro aplica o verificador genérico ao retorno. Isso confirma
        # execução/resultado da própria ferramenta, mas não converte ação GUI
        # em sucesso de objetivo.
        tool_result_evidence = Evidence(
            kind=EvidenceKind.TOOL_RESULT,
            tool_result={
                "success": execution.success,
                "response": raw,
                "error": execution.error,
            },
        )
        verification = self._verification_service.verify_with_policy(
            tool_result_evidence,
            action_name=tool_name,
        )

        if not execution.success:
            execution.verified = False
            execution.status = "failed"
        elif tool_name in _STRICT_VERIFICATION_TOOLS:
            execution.verified = verified
            execution.status = "verified" if verified else "executed_unverified"
        else:
            execution.verified = verification is VerificationResult.SUCCESS or verified
            execution.status = "verified" if execution.verified else "executed_unverified"

        if execution.success and tool_name in _STRICT_VERIFICATION_TOOLS and not execution.verified:
            self._emit(
                EventType.honesty_gate,
                {
                    "claim": "action_success",
                    "tool": tool_name,
                    "executed": True,
                    "verified": False,
                },
            )
        return message, execution

    @staticmethod
    def _fast_post_tool_response(execution: ExecutionEvidence) -> str | None:
        """Cria resposta final sem LLM quando a tool já encerra o objetivo.

        O fast path só aceita sucesso real e ferramentas em uma allowlist
        conservadora. Resultado de navegador/computador/mensageria nunca entra
        aqui, evitando alegações de verificação sem uma etapa explícita.
        """
        tool_name = execution.tool.split("(", 1)[0]
        if not execution.success or tool_name not in _FAST_POST_TOOL_TOOLS:
            return None
        if not isinstance(execution.result, dict):
            return None

        if tool_name == "memory_save":
            return "Pronto, salvei isso na memória."
        if tool_name == "file_write":
            return "Pronto, o arquivo foi salvo."
        return None

    async def _run_agent_loop(
        self,
        provider: LLMProvider,
        messages: list[LLMMessage],
        permissions: set[Any],
        conversation_id: str | None = None,
        stream_tokens: bool = False,
        task: str = "",
        context: Any | None = None,
        expose_tools: bool = True,
    ) -> tuple[LLMResponse, list[LLMMessage]]:
        """Executa o loop normal, com fast path determinístico pós-tool."""
        allowed_names = self._initial_tool_names(task, permissions) if expose_tools else set()
        evidence: list[ExecutionEvidence] = []
        new_messages: list[LLMMessage] = []
        executed_signatures: set[str] = set()

        last_response = await self._provider_turn(
            provider, messages, self._schemas_for(allowed_names, permissions), stream_tokens
        )
        iterations = 0
        while last_response.tool_calls and iterations < self.settings.agent_max_tool_iterations:
            self._raise_if_cancelled()
            assistant_turn = LLMMessage(
                role="assistant",
                content=AgentCore._scrub_internal_json(last_response.content or ""),
                tool_calls=last_response.tool_calls,
            )
            messages.append(assistant_turn)
            new_messages.append(assistant_turn)

            tool_messages: list[LLMMessage] = []
            iteration_executions: list[ExecutionEvidence] = []
            for tool_call in last_response.tool_calls:
                signature = self._call_signature(tool_call)
                if signature in executed_signatures:
                    tool_messages.append(self._repeated_call_message(tool_call))
                    continue
                executed_signatures.add(signature)
                tool_msg, execution = await self._execute_tool(
                    tool_call, permissions, conversation_id, allowed_names
                )
                tool_messages.append(tool_msg)
                if execution is not None:
                    evidence.append(execution)
                    iteration_executions.append(execution)
            messages.extend(tool_messages)
            new_messages.extend(tool_messages)

            # Fast Post-Tool Response: uma única tool determinística bem-sucedida
            # já produziu a evidência final. Evita o segundo round do LLM.
            if len(last_response.tool_calls) == 1 and len(iteration_executions) == 1:
                fast_content = self._fast_post_tool_response(iteration_executions[0])
                if fast_content is not None:
                    final = LLMMessage(role="assistant", content=fast_content)
                    messages.append(final)
                    new_messages.append(final)
                    self._evidence = [item.to_dict() for item in evidence]
                    if context is not None:
                        context.evidence = list(evidence)
                        context.exposed_tools = set(allowed_names)
                        context.response_candidate = fast_content
                    self._emit(
                        EventType.agent_progress,
                        {
                            "kind": "fast_post_tool_response",
                            "tool": iteration_executions[0].tool,
                        },
                    )
                    self._emit(
                        EventType.assistant_message,
                        payload={"preview": fast_content[:120], "content": fast_content},
                    )
                    return LLMResponse(content=fast_content, raw=last_response.raw), new_messages

            called_names = [tool_call.name for tool_call in last_response.tool_calls]
            allowed_names = self._expand_tools(allowed_names, called_names)

            turn_input = self._with_execution_context(task, messages, evidence)
            last_response = await self._provider_turn(
                provider,
                turn_input,
                self._schemas_for(allowed_names, permissions),
                stream_tokens,
            )
            iterations += 1

        content = last_response.content or ""
        content = AgentCore._scrub_internal_json(content)
        if content and content != content.strip():
            content = content.strip()
        content = self._apply_honesty_gate(content, evidence)
        if not content and evidence and not any(item.success for item in evidence):
            content = (
                "Não consegui concluir com evidência: as ferramentas necessárias falharam "
                "ou não retornaram um resultado de sucesso. Verifique os erros relatados "
                "e tente novamente."
            )
        final = LLMMessage(role="assistant", content=content)
        messages.append(final)
        new_messages.append(final)
        self._evidence = [item.to_dict() for item in evidence]
        if context is not None:
            context.evidence = list(evidence)
            context.exposed_tools = set(allowed_names)
            context.response_candidate = content
        self._emit(
            EventType.assistant_message,
            payload={"preview": content[:120], "content": content},
        )
        return LLMResponse(content=content, raw=last_response.raw), new_messages

    def _expand_tools(self, allowed: set[str], called: list[str]) -> set[str]:
        return set(allowed)

    async def _load_history(self, conversation_id: str, limit: int) -> list[LLMMessage]:
        return await super()._load_history(
            conversation_id,
            limit=max(1, min(limit, self.settings.agent_history_limit)),
        )

    def _apply_honesty_gate(
        self,
        content: str,
        evidence: list[ExecutionEvidence],
    ) -> str:
        if content and _WEATHER_CLAIM_RE.search(content):
            successful = [item for item in evidence if item.success]
            if successful and not any(
                item.tool.split("(", 1)[0] in _WEATHER_EVIDENCE_TOOLS
                for item in successful
            ):
                self._emit(EventType.honesty_gate, {
                    "claim": "weather_result",
                    "executed": True,
                    "verified": False,
                })
                return (
                    "Abri a página solicitada, mas não consegui verificar a previsão "
                    "do tempo a partir do conteúdo da página."
                )

        # Para ações estritas, sucesso sem pós-condição NÃO autoriza uma frase
        # de conclusão. Isso impede que "cliquei/enviado/abri" seja inferido
        # apenas do retorno da função.
        strict_unverified = [
            item for item in evidence
            if item.success
            and item.tool.split("(", 1)[0] in _STRICT_VERIFICATION_TOOLS
            and not item.verified
        ]
        if strict_unverified and content and (self._claims_success(content) or any(
            token in content.lower() for token in ("enviei", "mandei", "abri", "cliquei", "digitei")
        )):
            self._emit(EventType.honesty_gate, {
                "claim": "strict_action_success",
                "tools": [item.tool for item in strict_unverified],
                "executed": True,
                "verified": False,
            })
            return (
                "A ação foi executada, mas não consegui verificar a pós-condição. "
                "Não vou afirmar que ela foi concluída sem essa evidência."
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
