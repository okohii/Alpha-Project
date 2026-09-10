from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.config import get_settings
from app.core.events import EventBus, EventType, SystemEvent
from app.llm.base import ExecutionEvidence, LLMMessage, LLMProvider, LLMResponse, ToolCall
from app.llm.router import FaultTolerantProvider, LLMRouter
from app.memory.service import MemoryService
from app.security import AccessDeniedError
from app.skills.registry import SkillRegistry
from app.tools.base import ToolPermission, ToolResult
from app.tools.errors import ToolNotFoundError
from app.tools.registry import ToolRegistry

logger = logging.getLogger("app.agent.agent")

# Ferramentas sempre disponíveis: custam pouco e dão o contexto essencial
# (hora, sistema, memória) em qualquer turno.
CORE_TOOLS = frozenset({"time", "system_info", "memory_search"})

# Conjunto padrão quando nenhuma skill casa com o pedido: controle geral de
# PC + arquivos. Muito menor que o catálogo completo, mas mantém as ações
# básicas disponíveis sem vazar o catálogo inteiro para o modelo.
FALLBACK_TOOLS = frozenset(
    CORE_TOOLS
    | {
        "open_app",
        "open_url",
        "type_text",
        "press_key",
        "mouse_click",
        "screenshot",
        "file_search",
        "file_read",
    }
)


@dataclass(slots=True)
class AgentResult:
    response: str
    conversation_id: str
    memory_created: bool = False
    tool_calls: list[dict[str, Any]] | None = None
    evidence: list[dict[str, Any]] | None = None


class AgentCore:
    def __init__(
        self,
        llm_router: LLMRouter,
        tool_registry: ToolRegistry,
        memory_service: MemoryService | None = None,
        allowed_directories: list[str | Path] | None = None,
        permission_request_handler: Callable[[str], Awaitable[bool]] | None = None,
        allowed_directories_resolver: Callable[[], list[str]] | None = None,
        db_session: Any | None = None,
        event_bus: EventBus | None = None,
        cancel_event: asyncio.Event | None = None,
        skill_registry: SkillRegistry | None = None,
    ) -> None:
        self.llm_router = llm_router
        self.tool_registry = tool_registry
        self.memory_service = memory_service
        self.settings = get_settings()
        self.allowed_directories = [
            str(Path(path).resolve()) for path in (allowed_directories or [])
        ]
        self.permission_request_handler = permission_request_handler
        self.allowed_directories_resolver = allowed_directories_resolver
        self.db_session = db_session
        self.events: list[SystemEvent] = []
        self._tools_used: list[str] = []
        self._evidence: list[dict[str, Any]] = []
        self.event_bus = event_bus
        self.cancel_event = cancel_event
        self.skill_registry = skill_registry

    def _emit(
        self,
        event_type: EventType,
        payload: dict[str, Any] | None = None,
        duration_ms: int | None = None,
    ) -> SystemEvent:
        event = SystemEvent(
            type=event_type, payload=dict(payload or {}), duration_ms=duration_ms
        )
        self.events.append(event)
        if self.event_bus is not None:
            self.event_bus.emit(event_type, event.payload, duration_ms)
        return event

    def _is_cancelled(self) -> bool:
        return self.cancel_event is not None and self.cancel_event.is_set()

    def _raise_if_cancelled(self) -> None:
        if self._is_cancelled():
            self._emit(EventType.agent_cancelled)
            raise asyncio.CancelledError()

    async def chat(self, message: str, conversation_id: str | None = None) -> dict[str, Any]:
        started_at = time.perf_counter()
        conversation_id = conversation_id or str(uuid4())
        self._tools_used = []
        self._evidence = []
        self._emit(EventType.user_message, {"conversation_id": conversation_id})
        self._emit(EventType.agent_started, {"conversation_id": conversation_id})
        try:
            result = await self._chat_impl(message, conversation_id)
            self._emit(
                EventType.agent_finished,
                {"conversation_id": conversation_id},
                duration_ms=_duration_ms(started_at),
            )
            return result
        except asyncio.CancelledError:
            self._emit(
                EventType.agent_cancelled,
                {"conversation_id": conversation_id},
                duration_ms=_duration_ms(started_at),
            )
            raise
        except Exception as exc:
            self._emit(
                EventType.agent_failed,
                {"error": str(exc)},
                duration_ms=_duration_ms(started_at),
            )
            raise

    async def chat_stream(
        self,
        message: str,
        conversation_id: str | None = None,
    ) -> Any:
        """Processa a mensagem emitindo cada ``SystemEvent`` em tempo real.

        Gera o mesmo ciclo de eventos de ``chat`` (``user_message``,
        ``agent_started``, ``agent_finished``/``agent_failed``/
        ``agent_cancelled``), transmitindo os tokens via ``token_stream``.
        """
        conversation_id = conversation_id or str(uuid4())
        self._tools_used = []
        self._evidence = []
        if self.event_bus is None:
            result = await self.chat(message, conversation_id)
            yield SystemEvent(
                type=EventType.assistant_message,
                payload={"content": result["response"]},
            )
            return

        started_at = time.perf_counter()
        queue: asyncio.Queue[SystemEvent] = asyncio.Queue()
        unsubscribe = self.event_bus.subscribe_all(
            lambda event: queue.put_nowait(event)
        )
        self._emit(EventType.user_message, {"conversation_id": conversation_id})
        self._emit(EventType.agent_started, {"conversation_id": conversation_id})

        async def _task_fn() -> dict[str, Any]:
            return await self._chat_impl(message, conversation_id, stream_tokens=True)

        task = asyncio.create_task(_task_fn())
        try:
            while True:
                try:
                    event = queue.get_nowait()
                except asyncio.QueueEmpty:
                    if task.done():
                        break
                    event = await queue.get()
                yield event
            await task
            self._emit(
                EventType.agent_finished,
                {"conversation_id": conversation_id},
                duration_ms=_duration_ms(started_at),
            )
        except asyncio.CancelledError:
            task.cancel()
            self._emit(
                EventType.agent_cancelled,
                {"conversation_id": conversation_id},
                duration_ms=_duration_ms(started_at),
            )
            raise
        except Exception as exc:
            self._emit(
                EventType.agent_failed,
                {"error": str(exc)},
                duration_ms=_duration_ms(started_at),
            )
            raise
        finally:
            unsubscribe()

    async def _chat_impl(
        self,
        message: str,
        conversation_id: str,
        stream_tokens: bool = False,
    ) -> dict[str, Any]:
        conversation_id = conversation_id or str(uuid4())
        history: list[LLMMessage] = []
        if self.db_session is not None:
            await self._ensure_conversation(conversation_id, message)
            history = await self._load_history(conversation_id, limit=30)

        memory_context: list[str] = []
        if self.memory_service is not None:
            memories = await self.memory_service.search_memories(
                message, limit=self.settings.rag_top_k
            )
            memory_context = [
                self._memory_context_line(memory)
                for memory in memories
                if self._memory_context_line(memory)
            ]

        profile_context: list[str] = []
        if self.memory_service is not None:
            profile = await self.memory_service.load_profile()
            profile_context = [
                self._memory_context_line(memory)
                for memory in profile
                if self._memory_context_line(memory)
            ]

        provider = self.llm_router.choose(message)
        # Build provider metadata for the response
        provider_class = provider.__class__.__name__
        provider_model = getattr(provider, "model", None)
        provider_base = getattr(provider, "base_url", None)
        if isinstance(provider, FaultTolerantProvider):
            # prefer cloud metadata when available
            cloud = getattr(provider, "cloud", None)
            local = getattr(provider, "local", None)
            provider_model = getattr(cloud, "model", None) or getattr(local, "model", None)
            provider_base = getattr(cloud, "base_url", None) or getattr(local, "base_url", None)
        system_prompt = self._build_system_prompt()
        messages = [LLMMessage(role="system", content=system_prompt)]
        if profile_context:
            messages.append(
                LLMMessage(
                    role="system",
                    content=(
                        "Perfil consolidado do usuário (fatos estáveis, use como referência "
                        "de quem ele é e como ele opera):\n- "
                        + "\n- ".join(profile_context)
                    ),
                )
            )
        if memory_context:
            messages.append(
                LLMMessage(
                    role="system",
                    content=(
                        "Registros de conversas anteriores (HISTÓRICO: preferências e fatos, "
                        "NÃO são ações executadas agora e não substituem a ação atual):\n- "
                        + "\n- ".join(memory_context)
                    ),
                )
            )
        messages.extend(history)
        messages.append(LLMMessage(role="user", content=message))

        permissions = {
            ToolPermission.read,
            ToolPermission.write,
            ToolPermission.sensitive,
        }
        response, turn_messages = await self._run_agent_loop(
            provider,
            messages,
            permissions,
            conversation_id,
            stream_tokens=stream_tokens,
            task=message,
        )

        if self.db_session is not None:
            await self._save_turn(conversation_id, message, turn_messages)

        memory_created = False
        if self.memory_service is not None:
            saved = await self.memory_service.save_episode(
                message, response.content, self._tools_used
            )
            memory_created = saved is not None
            if memory_created:
                self._emit(
                    EventType.memory_created, {"conversation_id": conversation_id}
                )

        return {
            "response": response.content,
            "conversation_id": conversation_id,
            "memory_created": memory_created,
            "tools_used": list(self._tools_used),
            "evidence": list(self._evidence),
            "provider": {
                "provider_class": provider_class,
                "model": provider_model,
                "base_url": provider_base,
                "mode": self.settings.llm_mode,
            },
        }

    async def _run_agent_loop(
        self,
        provider: LLMProvider,
        messages: list[LLMMessage],
        permissions: set[ToolPermission],
        conversation_id: str | None = None,
        stream_tokens: bool = False,
        task: str = "",
    ) -> tuple[LLMResponse, list[LLMMessage]]:
        """Executa o ciclo Agent ↔ Tools preservando o protocolo correto.

        Para cada turno com ``tool_calls`` o modelo recebe:

            user -> assistant(tool_calls) -> tool(resultado) -> assistant(fim)

        A mensagem ``assistant`` com as chamadas é mantida no histórico (ao
        contrário do que acontecia), e os resultados das ferramentas são
        registrados como ``ExecutionEvidence`` e injetados como contexto
        observado no turno seguinte.
        """
        allowed_names = self._initial_tool_names(task, permissions)
        evidence: list[ExecutionEvidence] = []
        new_messages: list[LLMMessage] = []

        last_response = await self._provider_turn(
            provider, messages, self._schemas_for(allowed_names, permissions), stream_tokens
        )
        iterations = 0
        while last_response.tool_calls and iterations < self.settings.agent_max_tool_iterations:
            self._raise_if_cancelled()
            # Mantém a mensagem assistant que originou as chamadas.
            assistant_turn = LLMMessage(
                role="assistant",
                content=last_response.content or "",
                tool_calls=last_response.tool_calls,
            )
            messages.append(assistant_turn)
            new_messages.append(assistant_turn)

            tool_messages: list[LLMMessage] = []
            for tool_call in last_response.tool_calls:
                tool_msg, execution = await self._execute_tool(
                    tool_call, permissions, conversation_id, allowed_names
                )
                tool_messages.append(tool_msg)
                if execution is not None:
                    evidence.append(execution)
            messages.extend(tool_messages)
            new_messages.extend(tool_messages)

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

        final = LLMMessage(role="assistant", content=last_response.content)
        messages.append(final)
        new_messages.append(final)
        self._evidence = [item.to_dict() for item in evidence]
        self._emit(
            EventType.assistant_message,
            payload={"preview": last_response.content[:120], "content": last_response.content},
        )
        return last_response, new_messages

    async def _execute_tool(
        self,
        tool_call: ToolCall,
        permissions: set[ToolPermission],
        conversation_id: str | None,
        allowed_names: set[str],
    ) -> tuple[LLMMessage, ExecutionEvidence | None]:
        try:
            tool = self.tool_registry.get(tool_call.name)
        except ToolNotFoundError:
            alternatives = sorted(n for n in allowed_names if n != tool_call.name)[:8]
            return (
                self._tool_result_message(
                    tool_call.name,
                    success=False,
                    response={},
                    error=(
                        f"Ferramenta inexistente '{tool_call.name}'. "
                        "Use apenas as ferramentas disponíveis neste turno."
                    ),
                    alternatives=alternatives or None,
                ),
                None,
            )

        if tool.permission not in permissions:
            return (
                self._tool_result_message(
                    tool.name,
                    success=False,
                    response={},
                    error=(
                        f"Uso negado: a ferramenta '{tool.name}' não está autorizada neste turno."
                    ),
                ),
                None,
            )

        if tool.permission is ToolPermission.sensitive:
            confirmed = await self._confirm_sensitive(tool.name, tool_call.arguments)
            if not confirmed:
                self._emit(
                    EventType.tool_finished,
                    {"tool": tool.name, "success": False},
                    duration_ms=0,
                )
                return (
                    self._tool_result_message(
                        tool.name,
                        success=False,
                        response={},
                        error="Uso negado pelo usuário (ferramenta sensível).",
                    ),
                    None,
                )

        started_at = time.perf_counter()
        self._emit(
            EventType.tool_started,
            {"tool": tool.name, "arguments": tool_call.arguments},
        )

        # Auto-redirect: se é ferramenta de ação, verifica se há macro correspondente
        action_tools = {"open_app", "open_url", "type_text", "press_key", "click"}
        if tool.name in action_tools:
            try:
                from app.macros.service import macro_service

                macros = await macro_service.list_macros(enabled_only=True)
                for macro in macros:
                    # Verifica se o nome da macro corresponde à ação
                    macro_name_lower = macro.name.lower()
                    args_str = str(tool_call.arguments).lower()
                    if any(
                        kw in args_str
                        for kw in macro_name_lower.split()
                        if len(kw) > 3
                    ):
                        # Encontrou macro correspondente - executa ela
                        macro_tool = self.tool_registry.get("macro_run")
                        if macro_tool:
                            result = await macro_tool.execute(
                                macro_id=macro.id
                            )
                            self._emit(
                                EventType.tool_finished,
                                {"tool": tool.name, "success": result.success},
                                duration_ms=_duration_ms(started_at),
                            )
                            self._tools_used.append(tool.name)
                            execution = ExecutionEvidence(
                                action_id=str(uuid4())[:8],
                                tool=f"{tool.name}(macro:{macro.name})",
                                arguments=dict(tool_call.arguments or {}),
                                executed_at=datetime.now(UTC).isoformat(),
                                success=result.success,
                                result=result.data or {},
                                error=str(result.error) if result.error else None,
                            )
                            msg = self._tool_result_message(
                                tool.name,
                                success=result.success,
                                response=result.data or {},
                                error=result.error,
                            )
                            return msg, execution
            except Exception:
                pass  # Se falhar, continua com a ferramenta original

        try:
            result = await tool.execute(**tool_call.arguments)
        except Exception as exc:
            result = ToolResult(
                name=tool.name,
                success=False,
                data={},
                error=f"falha inesperada da ferramenta {tool.name!r}: {exc!r}",
            )
        if (
            not result.success
            and isinstance(result.error, AccessDeniedError)
            and result.error.candidate
        ):
            granted = await self._request_permission(result.error.candidate)
            if granted:
                result = await tool.execute(**tool_call.arguments)
        self._emit(
            EventType.tool_finished,
            {"tool": tool.name, "success": result.success},
            duration_ms=_duration_ms(started_at),
        )
        self._tools_used.append(tool.name)
        await self._record_tool_execution(
            conversation_id,
            tool_name=tool.name,
            input_data=tool_call.arguments,
            result=result,
        )

        execution = ExecutionEvidence(
            action_id=str(uuid4())[:8],
            tool=tool.name,
            arguments=dict(tool_call.arguments or {}),
            executed_at=datetime.now(UTC).isoformat(),
            success=result.success,
            result=result.data or {},
            error=str(result.error) if result.error else None,
        )
        return (
            self._tool_result_message(
                tool.name,
                success=result.success,
                response=result.data or {},
                error=str(result.error) if result.error else None,
            ),
            execution,
        )

    def _tool_result_message(
        self,
        name: str,
        *,
        success: bool,
        response: dict[str, Any],
        error: str | None = None,
        alternatives: list[str] | None = None,
    ) -> LLMMessage:
        payload: dict[str, Any] = {
            "type": "function_response",
            "name": name,
            "success": bool(success),
            "response": response or {},
            "error": error,
        }
        if alternatives:
            payload["available_alternatives"] = alternatives
        return LLMMessage(
            role="tool", content=json.dumps(payload, ensure_ascii=False, default=str)
        )

    # ---- seleção de ferramentas por skill ----

    def _initial_tool_names(
        self, task: str, permissions: set[ToolPermission]
    ) -> set[str]:
        available = {tool.name for tool in self.tool_registry.list(permissions)}
        if self.skill_registry is None or not self.settings.agent_tool_selection:
            return set(available)
        best_skill = self.skill_registry.best_skill_for_task(task)
        if best_skill is None:
            # Sem skill clara, empate no topo, ou par composto -> usa TODAS as skills casando
            skills = self.skill_registry.skills_for_task(task)
            names: set[str] = set()
            for skill in skills:
                names.update(self.skill_registry.get_tools_for_skills([skill.name]))
            names &= available
            if not names:
                names = {name for name in FALLBACK_TOOLS if name in available}
            names |= {name for name in CORE_TOOLS if name in available}
            return names
        names = set(self.skill_registry.get_tools_for_skills([best_skill.name]))
        names &= available
        if not names:
            names = {name for name in FALLBACK_TOOLS if name in available}
        names |= {name for name in CORE_TOOLS if name in available}
        return names

    def _expand_tools(self, allowed: set[str], called: list[str]) -> set[str]:
        """Amplia as ferramentas quando uma chamada revela a skill necessária."""
        expanded = set(allowed)
        if self.skill_registry is None:
            return expanded
        for name in called:
            skill_name = self.skill_registry.skill_for_tool(name)
            if skill_name is None:
                continue
            for tool_name in self.skill_registry.get_tools_for_skills([skill_name]):
                if tool_name in self.tool_registry.tools:
                    expanded.add(tool_name)
        return expanded

    def _schemas_for(
        self, names: set[str], permissions: set[ToolPermission]
    ) -> list[dict[str, Any]]:
        schemas: list[dict[str, Any]] = []
        for name in sorted(names):
            try:
                tool = self.tool_registry.get(name)
            except ToolNotFoundError:
                continue
            if tool.permission in permissions:
                schemas.append(tool.schema())
        return schemas

    def _with_execution_context(
        self,
        task: str,
        messages: list[LLMMessage],
        evidence: list[ExecutionEvidence],
    ) -> list[LLMMessage]:
        """Injeta o objetivo e os resultados observados no turno seguinte."""
        blocks: list[str] = []
        if task:
            blocks.append(f"OBJETIVO: {task}")
        if evidence:
            lines: list[str] = []
            for item in evidence[-8:]:
                status = "sucesso" if item.success else "falha"
                verified = "verificado" if item.verified else "não verificado"
                lines.append(
                    f"- {item.tool} → {status} ({verified}){self._compact_result(item.result)}"
                )
            blocks.append(
                "ÚLTIMOS RESULTADOS OBSERVADOS (fatos reais, não suposições):\n"
                + "\n".join(lines)
            )
        if not blocks:
            return messages
        insert_at = 0
        for index, message in enumerate(messages):
            if message.role == "system":
                insert_at = index + 1
            else:
                break
        context = LLMMessage(role="system", content="\n\n".join(blocks))
        return messages[:insert_at] + [context] + messages[insert_at:]

    @staticmethod
    def _compact_result(data: dict[str, Any]) -> str:
        if not data:
            return ""
        parts: list[str] = []
        for key, value in list(data.items())[:3]:
            if isinstance(value, (dict, list)):
                rendered = json.dumps(value, ensure_ascii=False, default=str)[:80]
            else:
                rendered = str(value)[:80]
            parts.append(f"{key}={rendered}")
        return " | " + ", ".join(parts)

    # ---- provider / permissões ----

    async def _provider_turn(
        self,
        provider: LLMProvider,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]],
        stream_tokens: bool,
    ) -> LLMResponse:
        """Chama o provedor, transmitindo tokens quando ``stream_tokens``.

        Provedores sem suporte a streaming caem de volta para ``complete``.
        """
        stream_turn = getattr(provider, "stream_turn", None)
        if stream_tokens and callable(stream_turn):
            streamed = await stream_turn(messages, tools)
            buffer: list[str] = []
            async for token in streamed:
                buffer.append(token)
                self._emit(EventType.token_stream, {"token": token})
            return LLMResponse(
                content="".join(buffer),
                tool_calls=streamed.tool_calls,
                raw=None,
            )
        return await provider.complete(messages, tools=tools)

    async def _request_permission(self, candidate: str) -> bool:
        if self.permission_request_handler is None:
            return False
        try:
            return await self.permission_request_handler(candidate)
        except Exception:
            return False

    async def _confirm_sensitive(self, tool_name: str, arguments: dict) -> bool:
        """Pede confirmação antes de executar ferramenta sensível quando há handler.

        Sem handler (ex.: API), a ferramenta NÃO é autorizada por padrão
        (``agent_auto_approve_sensitive=False``): ausência de interface de
        confirmação não significa autorização automática.
        """
        if self.permission_request_handler is None:
            return self.settings.agent_auto_approve_sensitive
        candidate = f"{tool_name}: {json.dumps(arguments, ensure_ascii=False, default=str)}"
        started_at = time.perf_counter()
        self._emit(
            EventType.waiting_confirmation,
            {
                "tool": tool_name,
                "arguments": arguments,
                "message": f"Confirma o uso de {tool_name}?",
            },
        )
        try:
            return await self._request_permission(candidate)
        finally:
            self._emit(
                EventType.waiting_confirmation_end,
                {"tool": tool_name},
                duration_ms=_duration_ms(started_at),
            )

    # ---- persistência da conversa ----

    async def _ensure_conversation(self, conversation_id: str, first_message: str) -> None:
        try:
            from app.db.models import Conversation

            existing = await self.db_session.get(Conversation, conversation_id)
            if existing is None:
                self.db_session.add(
                    Conversation(id=conversation_id, title=first_message[:60] or "Nova conversa")
                )
                await self.db_session.commit()
        except Exception as exc:  # pragma: no cover - manter chat resiliente
            logger.debug("Falha ao garantir conversa %s: %s", conversation_id, exc)

    async def _load_history(self, conversation_id: str, limit: int) -> list[LLMMessage]:
        try:
            from sqlalchemy import select

            from app.db.models import Message

            result = await self.db_session.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(limit)
            )
            rows = list(result.scalars().all())
        except Exception as exc:  # pragma: no cover
            logger.debug("Falha ao carregar histórico %s: %s", conversation_id, exc)
            return []
        return [self._message_from_row(row) for row in reversed(rows)]

    @staticmethod
    def _message_from_row(row: Any) -> LLMMessage:
        role = row.role
        content = row.content
        if role == "assistant":
            try:
                parsed = json.loads(content)
            except (TypeError, ValueError):
                parsed = None
            if isinstance(parsed, dict) and parsed.get("tool_calls"):
                calls = [
                    ToolCall(
                        name=call.get("name", ""),
                        arguments=call.get("arguments") or {},
                    )
                    for call in parsed["tool_calls"]
                    if isinstance(call, dict)
                ]
                if calls:
                    return LLMMessage(
                        role="assistant",
                        content=parsed.get("content", ""),
                        tool_calls=calls,
                    )
        return LLMMessage(role=role, content=content)

    async def _save_turn(
        self,
        conversation_id: str,
        user_message: str,
        turn_messages: list[LLMMessage],
    ) -> None:
        """Persiste o turno completo: user + assistant(tool_calls) + tool + final."""
        await self._save_message(conversation_id, "user", user_message)
        for message in turn_messages:
            await self._save_message(
                conversation_id, message.role, message.content, tool_calls=message.tool_calls
            )

    async def _save_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        tool_calls: list[ToolCall] | None = None,
    ) -> None:
        if not content and role == "assistant" and not tool_calls:
            return
        if role == "assistant" and tool_calls:
            content = json.dumps(
                {
                    "content": content or "",
                    "tool_calls": [
                        {"name": call.name, "arguments": call.arguments or {}}
                        for call in tool_calls
                    ],
                },
                ensure_ascii=False,
                default=str,
            )
        try:
            from app.db.models import Message

            self.db_session.add(
                Message(
                    conversation_id=conversation_id,
                    role=role,
                    content=content or "",
                    metadata_={},
                )
            )
            await self.db_session.commit()
        except Exception as exc:  # pragma: no cover
            logger.debug("Falha ao salvar mensagem (%s): %s", role, exc)

    async def _record_tool_execution(
        self,
        conversation_id: str | None,
        *,
        tool_name: str,
        input_data: dict[str, Any],
        result: Any,
    ) -> None:
        if self.db_session is None:
            return
        try:
            from app.db.models import ToolExecution

            self.db_session.add(
                ToolExecution(
                    conversation_id=conversation_id,
                    tool_name=tool_name,
                    status="success" if result.success else "error",
                    input_data=dict(input_data or {}),
                    output_data=result.data if result.success else None,
                    error=str(result.error) if result.error else None,
                )
            )
            await self.db_session.commit()
        except Exception as exc:  # pragma: no cover
            logger.debug("Falha ao registrar execução de %s: %s", tool_name, exc)

    def _build_system_prompt(self) -> str:
        system_prompt = self._load_system_prompt()
        project_context = self._project_context()
        if project_context:
            system_prompt = f"{system_prompt}\n\nContexto do projeto:\n{project_context}"

        # Injeta lista de macros disponíveis no prompt
        try:
            import asyncio
            import concurrent.futures

            from sqlalchemy import select

            from app.db.session import AsyncSessionLocal
            from app.macros.models import MacroRecord

            async def _load_macros() -> list:
                async with AsyncSessionLocal() as session:
                    result = await session.execute(
                        select(MacroRecord).where(MacroRecord.enabled == 1)
                    )
                    return list(result.scalars().all())

            try:
                asyncio.get_running_loop()
                # Já há um loop rodando - usa thread para rodar
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    macros = pool.submit(asyncio.run, _load_macros()).result()
            except RuntimeError:
                macros = asyncio.run(_load_macros())

            if macros:
                macro_lines = []
                for m in macros:
                    desc = m.description or m.name
                    macro_lines.append(f"- {m.name}: {desc}")
                macro_list_str = "\n".join(macro_lines)
                macro_section = (
                    "\n\n## Macros disponíveis"
                    " (USE macro_run para executar):\n"
                    f"{macro_list_str}"
                )
                system_prompt += macro_section
        except Exception:
            pass

        return system_prompt

    @staticmethod
    def _memory_context_line(memory: Any) -> str:
        content = memory.content
        if getattr(memory, "metadata", {}).get("episode"):
            content, sep, _ = content.partition("| resultado:")
            if sep:
                content = content.rstrip(" |")
        return content.strip()

    def _project_context(self) -> str:
        import platform

        workdir = Path.cwd().resolve()
        if self.allowed_directories_resolver is not None:
            allowed_paths = self.allowed_directories_resolver()
        else:
            allowed_paths = self.allowed_directories or [
                str(path.resolve()) for path in self.settings.allowed_directories
            ]
        normalized_allowed = [str(Path(path).resolve().as_posix()) for path in allowed_paths] or [
            workdir.as_posix()
        ]
        lines = [
            f"- Nome do app: {self.settings.app_name}",
            f"- Diretório atual: {workdir.as_posix()}",
            f"- Sistema operacional: {platform.platform()}",
            f"- Rotas permitidas: {', '.join(normalized_allowed)}",
            f"- Modo de IA: {self.settings.llm_mode}",
            f"- Ambiente: {self.settings.app_env}",
            "- Capabilidades de PC: abrir aplicativos (open_app), abrir arquivos/pastas "
            "(open_file), ler/editar arquivos permitidos, pesquisar na web, lembrar contexto.",
        ]
        return "\n".join(lines)

    def _load_system_prompt(self) -> str:
        prompt_path = self.settings.system_prompt_path
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        return "Você é o ALPHA."


def _duration_ms(started_at: float) -> int:
    return int((time.perf_counter() - started_at) * 1000)