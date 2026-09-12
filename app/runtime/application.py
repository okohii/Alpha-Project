from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from app.agent.serialized import SerializedAgentCore
from app.calendar.service import CalendarRepository, CalendarService
from app.core.config import get_settings
from app.llm.configured_ollama import ConfiguredOllamaProvider
from app.llm.router import LLMRouter
from app.memory.embeddings import LocalEmbeddingProvider
from app.memory.repository import SqliteMemoryRepository
from app.memory.service import MemoryService
from app.reminders.service import ReminderRepository, ReminderService
from app.security import SENSITIVE_PREFIX
from app.skills.catalog import build_default_skill_registry
from app.skills.files.service import FileManager
from app.skills.tasks import TaskCreateTool, TaskExecuteTool, TaskListTool, TaskRegisterPathTool
from app.tasks.service import ManagedPathRepository, TaskExecutorService, TaskRepository
from app.tools.registry import build_default_tool_registry

logger = logging.getLogger("app.runtime.application")


async def build_agent(
    session: Any,
    permission_prompt: Callable[[str], Awaitable[bool]] | None = None,
    event_bus: Any | None = None,
    cancel_event: asyncio.Event | None = None,
) -> SerializedAgentCore:
    memory_repository = SqliteMemoryRepository(session)
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
        calendar_service = CalendarService(CalendarRepository(session))
    except Exception:
        calendar_service = None

    def _document_indexer_factory() -> Any:
        from app.documents.indexer import DocumentIndexer, DocumentRepository
        return DocumentIndexer(
            file_manager=file_manager,
            repository=DocumentRepository(session),
            embedding_provider=LocalEmbeddingProvider(),
        )

    try:
        tool_registry = build_default_tool_registry(
            file_manager=file_manager,
            memory_service=memory_service,
            task_service=task_service,
            reminder_service=reminder_service,
            calendar_service=calendar_service,
            document_indexer_factory=_document_indexer_factory,
        )
    except TypeError:
        tool_registry = build_default_tool_registry(
            file_manager=file_manager,
            memory_service=memory_service,
            task_service=task_service,
            reminder_service=reminder_service,
            calendar_service=calendar_service,
        )

    if hasattr(tool_registry, "tools"):
        for tool_class in (TaskCreateTool, TaskExecuteTool, TaskListTool, TaskRegisterPathTool):
            tool_registry.tools.setdefault(tool_class.name, tool_class(task_service))

    skill_registry = build_default_skill_registry(
        tools_in_registry=tool_registry.tools if hasattr(tool_registry, "tools") else None
    )
    missing_tools = skill_registry.validate_tools(
        tool_registry.tools if hasattr(tool_registry, "tools") else {}
    )
    if missing_tools:
        logger.warning(
            "skills com tools ausentes do registro (não serão expostas ao LLM): %s",
            ", ".join(missing_tools),
        )

    async def _permission_request(candidate: str) -> bool:
        if permission_prompt is None:
            return False
        is_action_confirmation = candidate.startswith(SENSITIVE_PREFIX)
        display = candidate[len(SENSITIVE_PREFIX):] if is_action_confirmation else candidate
        granted = await permission_prompt(display)
        if not granted:
            return False
        if is_action_confirmation:
            return True
        normalized = Path(candidate).expanduser().resolve()
        if normalized not in file_manager.allowed_directories:
            file_manager.allowed_directories.append(normalized)
        await task_service.register_allowed_path(
            path=str(normalized), entry_type="directory", source="permission_request"
        )
        return True

    return SerializedAgentCore(
        llm_router=LLMRouter(local_provider=ConfiguredOllamaProvider()),
        tool_registry=tool_registry,
        memory_service=memory_service,
        allowed_directories=[str(path) for path in allowed_directories],
        permission_request_handler=_permission_request,
        allowed_directories_resolver=lambda: [str(path) for path in file_manager.allowed_directories],
        db_session=session,
        event_bus=event_bus,
        cancel_event=cancel_event,
        skill_registry=skill_registry,
    )
