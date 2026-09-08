from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.config import get_settings
from app.core.events import EventType, SystemEvent
from app.core.security import AccessDeniedError
from app.llm.base import LLMMessage, LLMProvider, LLMResponse
from app.llm.router import FaultTolerantProvider, LLMRouter
from app.memory.service import MemoryService
from app.tools.base import ToolPermission, ToolResult
from app.tools.registry import ToolRegistry

logger = logging.getLogger("app.agent.agent")


@dataclass(slots=True)
class AgentResult:
    response: str
    conversation_id: str
    memory_created: bool = False
    tool_calls: list[dict[str, Any]] | None = None


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

    async def chat(self, message: str, conversation_id: str | None = None) -> dict[str, Any]:
        conversation_id = conversation_id or str(uuid4())
        self._tools_used = []
        self.events.append(
            SystemEvent(type=EventType.user_message, payload={"conversation_id": conversation_id})
        )

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

        permissions = {ToolPermission.read, ToolPermission.write}
        response = await self._run_agent_loop(provider, messages, permissions, conversation_id)

        if self.db_session is not None:
            await self._save_message(conversation_id, "user", message)
            await self._save_message(conversation_id, "assistant", response.content)

        memory_created = False
        if self.memory_service is not None:
            saved = await self.memory_service.save_episode(
                message, response.content, self._tools_used
            )
            memory_created = saved is not None
            if memory_created:
                self.events.append(
                    SystemEvent(
                        type=EventType.memory_created, payload={"conversation_id": conversation_id}
                    )
                )

        return {
            "response": response.content,
            "conversation_id": conversation_id,
            "memory_created": memory_created,
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
    ) -> LLMResponse:
        allowed_tools = self.tool_registry.schemas(permissions)
        last_response = await provider.complete(messages, tools=allowed_tools)
        iterations = 0
        while last_response.tool_calls and iterations < self.settings.agent_max_tool_iterations:
            tool_messages = []
            for tool_call in last_response.tool_calls:
                tool = self.tool_registry.get(tool_call.name)
                if tool.permission not in permissions:
                    continue
                self.events.append(
                    SystemEvent(type=EventType.tool_started, payload={"tool": tool.name})
                )
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
                        self.events.append(
                            SystemEvent(
                                type=EventType.tool_finished,
                                payload={"tool": tool.name, "success": True},
                            )
                        )
                        result = await tool.execute(**tool_call.arguments)
                self.events.append(
                    SystemEvent(
                        type=EventType.tool_finished,
                        payload={"tool": tool.name, "success": result.success},
                    )
                )
                self._tools_used.append(tool.name)
                await self._record_tool_execution(
                    conversation_id,
                    tool_name=tool.name,
                    input_data=tool_call.arguments,
                    result=result,
                )
                # For proper function-calling flows (Gemini), return a structured function response
                func_resp = {
                    "type": "function_response",
                    "name": result.name,
                    "success": result.success,
                    "response": result.data or {},
                    "error": str(result.error) if result.error else None,
                }
                tool_messages.append(
                    LLMMessage(
                        role="tool",
                        content=json.dumps(func_resp, default=str),
                    )
                )
            messages.extend(tool_messages)
            messages[0] = LLMMessage(role="system", content=self._build_system_prompt())
            last_response = await provider.complete(messages, tools=allowed_tools)
            iterations += 1
        self.events.append(
            SystemEvent(
                type=EventType.assistant_message, payload={"preview": last_response.content[:120]}
            )
        )
        return last_response

    async def _request_permission(self, candidate: str) -> bool:
        if self.permission_request_handler is None:
            return False
        try:
            return await self.permission_request_handler(candidate)
        except Exception:
            return False

    async def _ensure_conversation(self, conversation_id: str, first_message: str) -> None:
        try:
            from app.database.models import Conversation

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

            from app.database.models import Message

            result = await self.db_session.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .where(Message.role.in_(("user", "assistant")))
                .order_by(Message.created_at.desc())
                .limit(limit)
            )
            rows = list(result.scalars().all())
        except Exception as exc:  # pragma: no cover
            logger.debug("Falha ao carregar histórico %s: %s", conversation_id, exc)
            return []
        history = [LLMMessage(role=row.role, content=row.content) for row in reversed(rows)]
        return history

    async def _save_message(self, conversation_id: str, role: str, content: str) -> None:
        if not content and role == "assistant":
            return
        try:
            from app.database.models import Message

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
            from app.database.models import ToolExecution

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
