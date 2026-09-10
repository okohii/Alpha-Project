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
from app.security import (
    EXECUTE_TOOLS,
    SENSITIVE_PREFIX,
    AccessDeniedError,
    SecurityDecision,
    classify_action,
    risk_requires_confirmation,
)
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
        "web_search",
    }
)

# Ferramentas cujo resultado vem de fonte não confiável (conteúdo de páginas,
# telas, arquivos ou execução de JS de terceiros). O resultado dessas tools é
# marcado como não confiável para o modelo — os delimitadores no prompt evitam
# prompt injection via conteúdo externo.
UNTRUSTED_CONTENT_TOOLS = frozenset(
    {
        "browser_text",
        "browser_html",
        "browser_js",
        "browser_click",
        "browser_screenshot",
        "web_search",
        "read_ui",
        "screenshot",
        "verify_screen",
        "file_read",
        "file_search",
        "file_write",
    }
)

_FALLBACK_ON_NO_SUCCESS = (
    "Não consegui concluir com evidência: as ferramentas necessárias falharam "
    "ou não retornaram um resultado de sucesso. Verifique os erros relatados "
    "e tente novamente."
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
        granted_permissions: set[ToolPermission] | None = None,
        facilitator: Any | None = None,
        planner: Any | None = None,
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
        # Permissões pré-autorizadas. ``None`` = deriva por padrão seguro:
        # leitura sempre; escrita apenas quando há interface de confirmação
        # (ou flag explícita); sensíveis NUNCA entram aqui (são confirmadas
        # por chamada em ``_execute_tool``).
        self.granted_permissions = (
            set(granted_permissions) if granted_permissions is not None else None
        )
        self.events: list[SystemEvent] = []
        self._tools_used: list[str] = []
        self._evidence: list[dict[str, Any]] = []
        # Trilha de auditoria de decisões de segurança do turno corrente.
        self._security_log: list[dict[str, Any]] = []
        self.event_bus = event_bus
        self.cancel_event = cancel_event
        self.skill_registry = skill_registry
        # Camada COMPREENDER (opcional): separa entendimento de execução.
        # Quando presente, cumprimentos/perguntas simples respondem sem LLM e
        # sem tools; intents ambíguos viram pergunta de esclarecimento. O
        # Facilitator NUNCA executa tools nem decide segurança.
        self.facilitator = facilitator
        self.planner = planner
        self._facilitator_goal: Any | None = None

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
        self._security_log = []
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
        self._security_log = []
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
            # Drena a fila enquanto a task roda. A cada evento aguardado,
            # observa a conclusão da task sem perder eventos já emitidos —
            # evita a race entre ``task.done()`` e ``queue.get()`` que
            # podia bloquear o stream indefinidamente.
            while not task.done():
                waiter = asyncio.create_task(queue.get())
                try:
                    done, _ = await asyncio.wait(
                        {waiter, task}, return_when=asyncio.FIRST_COMPLETED
                    )
                    if waiter in done:
                        yield waiter.result()
                    else:
                        # Task concluiu antes de produzir o próximo evento.
                        break
                finally:
                    if not waiter.done():
                        waiter.cancel()
                        try:
                            await waiter
                        except asyncio.CancelledError:
                            pass

            # Task concluída: drena eventos remanescentes emitidos antes de
            # terminar e propaga exceções pendentes.
            while True:
                try:
                    yield queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            await task
            self._emit(
                EventType.agent_finished,
                {"conversation_id": conversation_id},
                duration_ms=_duration_ms(started_at),
            )
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
        finally:
            unsubscribe()
            # Garante que a task em background não fica pendente se o
            # consumidor parar antes (ex.: GeneratorExit por aclose()).
            if not task.done():
                task.cancel()
                try:
                    await task
                except BaseException:
                    pass

    async def _chat_impl(
        self,
        message: str,
        conversation_id: str,
        stream_tokens: bool = False,
    ) -> dict[str, Any]:
        conversation_id = conversation_id or str(uuid4())
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

        # Camada COMPREENDER (opcional): cumprimentos/perguntas simples respondem
        # sem LLM/sem tools; intents ambíguos pedem esclarecimento. Tudo que
        # precisa de execução vira Goal para a camada EXECUTA (loop normal).
        self._facilitator_goal = None
        if self.facilitator is not None:
            outcome = await self.facilitator.process(
                self._facilitator_request(message, conversation_id)
            )
            if outcome.kind == "clarification":
                self._emit(
                    EventType.waiting_input,
                    {"prompt": outcome.response},
                )
                return self._fast_result(
                    response=outcome.response,
                    conversation_id=conversation_id,
                    provider_class=provider_class,
                    provider_model=provider_model,
                    provider_base=provider_base,
                )
            if outcome.kind == "direct":
                direct = (outcome.response or "").strip()
                self._emit(
                    EventType.assistant_message,
                    payload={"preview": direct[:120], "content": direct},
                )
                return self._fast_result(
                    response=direct,
                    conversation_id=conversation_id,
                    provider_class=provider_class,
                    provider_model=provider_model,
                    provider_base=provider_base,
                )
            if outcome.goal is not None:
                self._facilitator_goal = outcome.goal
            else:
                self._emit(EventType.agent_progress, {"message": outcome.intent.name})

        if self._facilitator_goal is not None and self.planner is not None:
            from app.agent.planner import Planner as _Planner

            self._plan = _Planner().build_plan(self._facilitator_goal)

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

        system_prompt = await self._build_system_prompt()
        messages = [LLMMessage(role="system", content=system_prompt)]
        if self._facilitator_goal is not None:
            try:
                from app.assistant.facilitator import format_goal_context

                messages.append(
                    LLMMessage(role="system", content=format_goal_context(self._facilitator_goal))
                )
            except Exception:  # pragma: no cover - bloco opcional não quebra o chat
                pass
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

        permissions = self._permissions_for_turn()
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
            "security_audit": list(self._security_log),
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

        A sequência enviada ao modelo é sempre:

            user -> assistant(tool_calls) -> tool(resultado) -> assistant(fim)

        A mensagem ``assistant`` com as chamadas é preservada antes dos
        resultados (pairing por ``tool_call_id``), repetições da mesma chamada
        são bloqueadas e o limite ``AGENT_MAX_TOOL_ITERATIONS`` é respeitado.
        """
        allowed_names = self._initial_tool_names(task, permissions)
        evidence: list[ExecutionEvidence] = []
        new_messages: list[LLMMessage] = []
        executed_signatures: set[str] = set()

        last_response = await self._provider_turn(
            provider, messages, self._schemas_for(allowed_names, permissions), stream_tokens
        )
        iterations = 0
        while last_response.tool_calls and iterations < self.settings.agent_max_tool_iterations:
            self._raise_if_cancelled()
            # Mantém a mensagem assistant que originou as chamadas ANTES dos
            # resultados das ferramentas — nunca tool(result) sem assistant(tool_calls).
            assistant_turn = LLMMessage(
                role="assistant",
                content=last_response.content or "",
                tool_calls=last_response.tool_calls,
            )
            messages.append(assistant_turn)
            new_messages.append(assistant_turn)

            tool_messages: list[LLMMessage] = []
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

        content = last_response.content or ""
        if not content and evidence and not any(item.success for item in evidence):
            content = _FALLBACK_ON_NO_SUCCESS
        final = LLMMessage(role="assistant", content=content)
        messages.append(final)
        new_messages.append(final)
        self._evidence = [item.to_dict() for item in evidence]
        self._emit(
            EventType.assistant_message,
            payload={"preview": content[:120], "content": content},
        )
        return LLMResponse(content=content, raw=last_response.raw), new_messages

    @staticmethod
    def _call_signature(tool_call: ToolCall) -> str:
        args = json.dumps(
            tool_call.arguments or {}, sort_keys=True, ensure_ascii=False, default=str
        )
        return f"{tool_call.name}:{args}"

    def _repeated_call_message(self, tool_call: ToolCall) -> LLMMessage:
        name = tool_call.name
        self._emit(
            EventType.tool_failed,
            {
                "tool": name,
                "error": (
                    f"chamada repetida de '{name}' com os mesmos argumentos no mesmo turno. "
                    "Não repita: troque de estratégia."
                ),
            },
        )
        return self._tool_result_message(
            name,
            success=False,
            response={},
            error=(
                f"'{name}' já foi chamada com os mesmos argumentos neste turno e não será "
                "executada de novo. Explore outra abordagem ou peça nova instrução."
            ),
            tool_call_id=tool_call.id,
        )

    async def _execute_tool(
        self,
        tool_call: ToolCall,
        permissions: set[ToolPermission],
        conversation_id: str | None,
        allowed_names: set[str],
    ) -> tuple[LLMMessage, ExecutionEvidence | None]:
        self._raise_if_cancelled()
        try:
            tool = self.tool_registry.get(tool_call.name)
        except ToolNotFoundError:
            alternatives = sorted(n for n in allowed_names if n != tool_call.name)[:8]
            self._emit(
                EventType.tool_failed,
                {"tool": tool_call.name, "error": "ferramenta inexistente"},
            )
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
                    tool_call_id=tool_call.id,
                ),
                None,
            )

        # Gate de permissão (least privilege):
        # - observe/read: automático (autorização pré-concedida do turno);
        # - write: depende do risco (medium/high exigem confirmação da
        #   interface; low é automático);
        # - execute/sensitive: confirmação obrigatória por chamada.
        action = classify_action(tool.name, tool.permission)
        needs_confirm = risk_requires_confirmation(tool.name, tool.permission)
        decision = SecurityDecision(
            action=action,
            tool=tool.name,
            permission_needed=tool.permission,
            access_granted=sorted(p.value for p in permissions),
            confirmation_required=needs_confirm,
            decision="pending",
            reason="",
            result="not_executed",
            arguments=dict(tool_call.arguments or {}),
        )

        confirmed: bool | None = None
        deny_reason = ""
        if needs_confirm:
            if tool.permission is ToolPermission.sensitive or tool.name in EXECUTE_TOOLS:
                confirmed = await self._confirm_sensitive(tool.name, tool_call.arguments)
            else:
                confirmed = await self._confirm_risk_write(tool.name, tool_call.arguments)
            if confirmed is not True:
                if (
                    tool.permission is ToolPermission.sensitive
                    or tool.name in EXECUTE_TOOLS
                ):
                    deny_reason = "uso sensível não confirmado pela interface"
                    deny_message = "Uso negado pelo usuário (ferramenta sensível)."
                elif self.permission_request_handler is None:
                    deny_reason = "escrita de risco sem interface de confirmação"
                    deny_message = (
                        f"Uso negado: a ferramenta '{tool.name}' não está "
                        "autorizada neste turno."
                    )
                else:
                    deny_reason = "escrita de risco não confirmada pela interface"
                    deny_message = "Uso negado pelo usuário."
                decision.decision = "declined"
                decision.reason = deny_reason
                self._audit_decision(decision)
                self._emit(
                    EventType.tool_failed,
                    {"tool": tool.name, "error": deny_reason},
                )
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
                        error=deny_message,
                        tool_call_id=tool_call.id,
                    ),
                    None,
                )
            decision.decision = (
                "confirmed" if self.permission_request_handler is not None else "auto_allowed"
            )
            decision.reason = "confirmação concedida pela interface"
        elif tool.permission not in permissions:
            decision.decision = "denied_not_authorized"
            decision.reason = (
                f"nível de permissão {tool.permission.value} não autorizado neste turno"
            )
            self._audit_decision(decision)
            self._emit(
                EventType.tool_failed,
                {
                    "tool": tool.name,
                    "error": f"nível de permissão {tool.permission.value} não autorizado",
                },
            )
            return (
                self._tool_result_message(
                    tool.name,
                    success=False,
                    response={},
                    error=(
                        f"Uso negado: a ferramenta '{tool.name}' não está autorizada neste turno."
                    ),
                    tool_call_id=tool_call.id,
                ),
                None,
            )
        else:
            decision.decision = "allowed"
            decision.reason = "ação autorizada com a permissão pré-concedida do turno"

        if not isinstance(tool_call.arguments, dict):
            decision.decision = "invalid_arguments"
            decision.reason = "argumentos não são um objeto JSON"
            self._audit_decision(decision)
            self._emit(
                EventType.tool_failed,
                {"tool": tool.name, "error": "argumentos inválidos"},
            )
            return (
                self._tool_result_message(
                    tool.name,
                    success=False,
                    response={},
                    error=f"Argumentos inválidos para '{tool.name}': esperava-se um objeto JSON.",
                    tool_call_id=tool_call.id,
                ),
                None,
            )

        validation_error = self._validate_tool_arguments(tool, tool_call.arguments)
        if validation_error:
            decision.decision = "invalid_arguments"
            decision.reason = validation_error
            self._audit_decision(decision)
            self._emit(
                EventType.tool_failed,
                {"tool": tool.name, "error": validation_error},
            )
            return (
                self._tool_result_message(
                    tool.name,
                    success=False,
                    response={},
                    error=validation_error,
                    tool_call_id=tool_call.id,
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
                            # macro_run é sensível: o auto-redirect NUNCA faz
                            # bypass da confirmação exigida por chamada.
                            confirmed = await self._confirm_sensitive(
                                "macro_run", {"macro_id": macro.id}
                            )
                            if not confirmed:
                                decision.decision = "declined"
                                decision.reason = "macro sensível não confirmada no auto-redirect"
                                decision.result = "not_executed"
                                self._audit_decision(decision)
                                self._emit(
                                    EventType.tool_failed,
                                    {"tool": tool.name, "error": "uso negado pelo usuário"},
                                )
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
                                        error=(
                                            "Uso negado pelo usuário "
                                            "(ferramenta sensível)."
                                        ),
                                        tool_call_id=tool_call.id,
                                    ),
                                    None,
                                )
                            decision.decision = (
                                "confirmed"
                                if self.permission_request_handler is not None
                                else "auto_allowed"
                            )
                            decision.reason = "macro confirmada via auto-redirect"
                            result = await macro_tool.execute(
                                macro_id=macro.id
                            )
                            decision.result = (
                                "success" if result.success else "failure"
                            )
                            self._audit_decision(decision)
                            self._emit(
                                EventType.tool_finished,
                                {"tool": tool.name, "success": result.success},
                                duration_ms=_duration_ms(started_at),
                            )
                            if not result.success:
                                self._emit(
                                    EventType.tool_failed,
                                    {
                                        "tool": tool.name,
                                        "error": str(result.error)
                                        if result.error
                                        else "macro falhou",
                                    },
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
                                tool_call_id=tool_call.id,
                                trusted=tool.name not in UNTRUSTED_CONTENT_TOOLS,
                            )
                            return msg, execution
            except Exception:
                pass  # Se falhar, continua com a ferramenta original

        try:
            result = await asyncio.wait_for(
                tool.execute(**tool_call.arguments),
                timeout=self.settings.agent_tool_timeout_seconds,
            )
        except TimeoutError:
            result = ToolResult(
                name=tool.name,
                success=False,
                data={},
                error=f"a ferramenta {tool.name!r} excedeu o tempo máximo de "
                f"{self.settings.agent_tool_timeout_seconds:.0f}s",
            )
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
                try:
                    result = await asyncio.wait_for(
                        tool.execute(**tool_call.arguments),
                        timeout=self.settings.agent_tool_timeout_seconds,
                    )
                except TimeoutError:
                    result = ToolResult(
                        name=tool.name,
                        success=False,
                        data={},
                        error=f"a ferramenta {tool.name!r} excedeu o tempo máximo de "
                        f"{self.settings.agent_tool_timeout_seconds:.0f}s",
                    )
                except Exception as exc:
                    result = ToolResult(
                        name=tool.name,
                        success=False,
                        data={},
                        error=f"falha inesperada da ferramenta {tool.name!r}: {exc!r}",
                    )
        decision.result = "success" if result.success else "failure"
        self._audit_decision(decision)
        self._emit(
            EventType.tool_finished,
            {"tool": tool.name, "success": result.success},
            duration_ms=_duration_ms(started_at),
        )
        if not result.success:
            self._emit(
                EventType.tool_failed,
                {
                    "tool": tool.name,
                    "error": str(result.error) if result.error else "falha desconhecida",
                },
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
                tool_call_id=tool_call.id,
                trusted=tool.name not in UNTRUSTED_CONTENT_TOOLS,
            ),
            execution,
        )

    @staticmethod
    def _validate_tool_arguments(tool: Any, arguments: dict[str, Any]) -> str | None:
        """Valida os argumentos contra o schema da ferramenta antes de executar.

        Retorna a descrição do erro ou ``None`` quando os argumentos são válidos.
        """
        schema = tool.schema()
        function_schema = schema["function"] if isinstance(schema, dict) else {}
        parameters = function_schema.get("parameters") or {}
        required = parameters.get("required") or []
        missing = [name for name in required if name not in arguments]
        if missing:
            return (
                f"Argumentos inválidos para '{tool.name}': campos obrigatórios ausentes — "
                + ", ".join(missing)
            )
        return None

    def _tool_result_message(
        self,
        name: str,
        *,
        success: bool,
        response: dict[str, Any],
        error: str | None = None,
        alternatives: list[str] | None = None,
        tool_call_id: str | None = None,
        trusted: bool = True,
    ) -> LLMMessage:
        payload: dict[str, Any] = {
            "type": "function_response",
            "name": name,
            "success": bool(success),
            "response": response or {},
            "error": error,
            "tool_call_id": tool_call_id,
            "trusted": bool(trusted),
        }
        if alternatives:
            payload["available_alternatives"] = alternatives
        return LLMMessage(
            role="tool", content=json.dumps(payload, ensure_ascii=False, default=str)
        )

    def _permissions_for_turn(self) -> set[ToolPermission]:
        """Deriva a autorização pré-concedida do turno.

        ``read`` sempre é autorizado. ``write`` entrou apenas quando há
        interface de confirmação interativa (handler) ou flag explícita.
        ``sensitive`` nunca entra aqui: é confirmada por chamada.
        """
        if self.granted_permissions is not None:
            return set(self.granted_permissions)
        permissions = {ToolPermission.read}
        if (
            self.permission_request_handler is not None
            or self.settings.agent_allow_write_default
        ):
            permissions.add(ToolPermission.write)
        return permissions

    # ---- seleção de ferramentas por skill ----

    def _can_expose_sensitive(self) -> bool:
        """Há caminho para confirmar uso de ferramenta sensível?

        Sensíveis só são anunciadas ao modelo quando existe interface de
        confirmação (handler) ou autorização automática explícita. Sem esse
        caminho, a exposição seria inútil e desnecessária.
        """
        return bool(
            self.permission_request_handler is not None
            or self.settings.agent_auto_approve_sensitive
        )

    def _advertised_permissions(
        self, permissions: set[ToolPermission]
    ) -> set[ToolPermission]:
        """Permissões das tools que podem ser ANUNCIADAS neste turno.

        Permissões pré-concedidas + sensíveis apenas quando há caminho de
        confirmação. Aplica a política ANTES de expor a tool ao modelo.
        """
        advertised = set(permissions)
        if self._can_expose_sensitive():
            advertised.add(ToolPermission.sensitive)
        return advertised

    def _initial_tool_names(
        self, task: str, permissions: set[ToolPermission]
    ) -> set[str]:
        advertised = self._advertised_permissions(permissions)
        available = {tool.name for tool in self.tool_registry.list(advertised)}
        if self.skill_registry is None or not self.settings.agent_tool_selection:
            return set(available)
        # Seleção determinística via SkillRegistry (sem chamada extra ao LLM).
        skills = self.skill_registry.select_skills_for_task(
            task, self.settings.agent_tool_selection_min_confidence
        )
        names: set[str] = set()
        if skills:
            names = set(
                self.skill_registry.get_tools_for_skills(
                    [skill.name for skill in skills]
                )
            )
            names &= available
        if not names:
            # Fallback seguro: sem skill, baixa confiança ou tarefa genérica.
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
        advertised = self._advertised_permissions(permissions)
        for name in sorted(names):
            try:
                tool = self.tool_registry.get(name)
            except ToolNotFoundError:
                continue
            if tool.permission in advertised:
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

    def _confirmation_candidate(self, tool_name: str, arguments: dict) -> str:
        """Candidato estruturado para confirmação de action no handler.

        O prefixo ``SENSITIVE_PREFIX`` diferencia de forma inequívoca a
        confirmação de action de candidatos que são caminhos de filesystem
        (não depende de heurística de formato ``\": \"``).
        """
        rendered = json.dumps(arguments, ensure_ascii=False, default=str)
        return f"{SENSITIVE_PREFIX}{tool_name}: {rendered}"

    @staticmethod
    def _facilitator_request(message: str, conversation_id: str | None) -> Any:
        """Monta o Request para o Facilitator sem acoplar agent -> assistant."""
        from app.assistant.intent import Request

        return Request(text=message, conversation_id=conversation_id)

    def _fast_result(
        self,
        *,
        response: str,
        conversation_id: str,
        provider_class: str | None,
        provider_model: Any,
        provider_base: Any,
    ) -> dict[str, Any]:
        """Resposta rápida do Facilitator (sem LLM e sem tools) no schema do chat."""
        return {
            "response": response,
            "conversation_id": conversation_id,
            "memory_created": False,
            "tools_used": [],
            "evidence": [],
            "security_audit": [],
            "facilitator": True,
            "provider": {
                "provider_class": provider_class,
                "model": provider_model,
                "base_url": provider_base,
                "mode": self.settings.llm_mode,
            },
        }

    async def _request_permission(self, candidate: str) -> bool:
        if self.permission_request_handler is None:
            return False
        try:
            return await self.permission_request_handler(candidate)
        except Exception:
            return False

    def _audit_decision(self, decision: SecurityDecision) -> None:
        """Registra a decisão de segurança no log do turno e no barramento.

        A auditoria é estrutural (não confia no LLM): quem emite é o próprio
        gate de permissão, com os fatos que ele usou para decidir.
        """
        record = decision.to_dict()
        self._security_log.append(record)
        self._emit(
            EventType.permission_decision,
            {
                "action": record["action"],
                "tool": record["tool"],
                "permission_needed": record["permission_needed"],
                "decision": record["decision"],
                "reason": record["reason"],
                "result": record["result"],
            },
        )

    async def _confirm_risk_write(self, tool_name: str, arguments: dict) -> bool:
        """Pede confirmação para escrita de risco (medium/high).

        Sem interface de confirmação (API sem handler) a escrita de risco é
        negada: a ausência de interface não autoriza nada automaticamente.
        """
        if self.permission_request_handler is None:
            return False
        candidate = self._confirmation_candidate(tool_name, arguments)
        return await self._request_permission(candidate)

    async def _confirm_sensitive(self, tool_name: str, arguments: dict) -> bool:
        """Pede confirmação antes de executar ferramenta sensível quando há handler.

        Sem handler (ex.: API), a ferramenta NÃO é autorizada por padrão
        (``agent_auto_approve_sensitive=False``): ausência de interface de
        confirmação não significa autorização automática.
        """
        if self.permission_request_handler is None:
            return self.settings.agent_auto_approve_sensitive
        candidate = self._confirmation_candidate(tool_name, arguments)
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
        """Persiste user + assistant(tool_calls) + assistant(final).

        Mensagens ``role="tool"`` NÃO são persistidas — a arquitetura
        atual reconstrói o histórico a partir do assistant serializado.
        """
        await self._save_message(conversation_id, "user", user_message)
        for message in turn_messages:
            if message.role == "tool":
                continue
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
                        {
                            "id": call.id,
                            "name": call.name,
                            "arguments": call.arguments or {},
                        }
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

    async def _build_system_prompt(self) -> str:
        system_prompt = self._load_system_prompt()
        project_context = self._project_context()
        if project_context:
            system_prompt = f"{system_prompt}\n\nContexto do projeto:\n{project_context}"

        # Injeta lista de macros disponíveis no prompt (consulta async,
        # sem bloquear o event loop com threads + .result()).
        try:
            from sqlalchemy import select

            from app.db.session import AsyncSessionLocal
            from app.macros.models import MacroRecord

            async def _load_macros() -> list:
                async with AsyncSessionLocal() as session:
                    result = await session.execute(
                        select(MacroRecord).where(MacroRecord.enabled == 1)
                    )
                    return list(result.scalars().all())

            macros = await _load_macros()

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