from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from app.agent.agent import AgentCore
from app.core.config import get_settings
from app.llm.ollama import OllamaProvider
from app.llm.router import LLMRouter
from app.memory.embeddings import LocalEmbeddingProvider
from app.memory.repository import MemoryRepository
from app.memory.service import MemoryService
from app.reminders.service import ReminderRepository, ReminderService
from app.security import SENSITIVE_PREFIX
from app.skills.catalog import build_default_skill_registry
from app.skills.files.service import FileManager
from app.skills.tasks import TaskCreateTool, TaskExecuteTool, TaskListTool, TaskRegisterPathTool
from app.tasks.service import ManagedPathRepository, TaskExecutorService, TaskRepository
from app.tools.registry import build_default_tool_registry


async def build_agent(
    session: Any,
    permission_prompt: Callable[[str], Awaitable[bool]] | None = None,
    event_bus: Any | None = None,
    cancel_event: asyncio.Event | None = None,
) -> AgentCore:
    memory_repository = MemoryRepository(session)
    memory_service = MemoryService(memory_repository, LocalEmbeddingProvider())

    managed_path_repository = ManagedPathRepository(session)
    allowed_records = await managed_path_repository.list()
    registered_directories = [
        Path(record.path).expanduser().resolve()
        for record in allowed_records
        if getattr(record, "is_allowed", 1) and getattr(record, "path", None)
    ]
    allowed_directories = registered_directories or list(get_settings().allowed_directories)

    file_manager = FileManager()
    file_manager.allowed_directories = allowed_directories

    task_service = TaskExecutorService(
        task_repository=TaskRepository(session),
        managed_path_repository=managed_path_repository,
        file_manager=file_manager,
    )

    reminder_service = ReminderService(ReminderRepository(session))

    try:
        tool_registry = build_default_tool_registry(
            file_manager=file_manager,
            task_service=task_service,
            reminder_service=reminder_service,
        )
    except TypeError:
        tool_registry = build_default_tool_registry(file_manager=file_manager)

    if hasattr(tool_registry, "tools"):
        for tool_class in (TaskCreateTool, TaskExecuteTool, TaskListTool, TaskRegisterPathTool):
            tool_registry.tools.setdefault(tool_class.name, tool_class(task_service))

    skill_registry = build_default_skill_registry(
        tools_in_registry=tool_registry.tools if hasattr(tool_registry, "tools") else None
    )

    async def _permission_request(candidate: str) -> bool:
        """Handler único de confirmação de permissão.

        Dois fluxos distintos passam por aqui, diferenciados por um prefixo
        estrutural (NÃO por heurística de formato):

        1. Confirmação de action      → candidate inicia com ``SENSITIVE_PREFIX``
           (tools sensíveis/arriscadas: ``"tool_name: {args_json}"``). O prefixo
           é removido para exibição na interface e NÃO deve poluir o whitelist
           de diretórios nem ser persistido no banco.

        2. AccessDeniedError         → candidate é um caminho de filesystem
           (ex.: ``C:/Users/foo/Downloads``). Só então é adicionado ao
           whitelist de diretórios autorizados e persistido.

        Nunca é o conteúdo/NUNCA o LLM que decide: a interface (handler) é a
        única fonte de autorização.
        """
        if permission_prompt is None:
            return False
        is_action_confirmation = candidate.startswith(SENSITIVE_PREFIX)
        display = (
            candidate[len(SENSITIVE_PREFIX) :]
            if is_action_confirmation
            else candidate
        )
        granted = await permission_prompt(display)
        if not granted:
            return False
        if is_action_confirmation:
            return True
        normalized = Path(candidate).expanduser().resolve()
        if normalized not in file_manager.allowed_directories:
            file_manager.allowed_directories.append(normalized)
        await task_service.register_allowed_path(
            path=str(normalized),
            entry_type="directory",
            source="permission_request",
        )
        return True

    return AgentCore(
        llm_router=LLMRouter(local_provider=OllamaProvider()),
        tool_registry=tool_registry,
        memory_service=memory_service,
        allowed_directories=[str(path) for path in allowed_directories],
        permission_request_handler=_permission_request,
        allowed_directories_resolver=lambda: [
            str(path) for path in file_manager.allowed_directories
        ],
        db_session=session,
        event_bus=event_bus,
        cancel_event=cancel_event,
        skill_registry=skill_registry,
    )