from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from app.agent.agent import AgentCore
from app.calendar.service import CalendarRepository, CalendarService
from app.core.config import get_settings
from app.documents.indexer import DocumentIndexer, DocumentRepository
from app.llm.ollama import OllamaProvider
from app.llm.router import LLMRouter
from app.memory.embeddings import LocalEmbeddingProvider
from app.memory.repository import MemoryRepository
from app.memory.service import MemoryService
from app.reminders.service import ReminderRepository, ReminderService
from app.tasks.service import ManagedPathRepository, TaskExecutorService, TaskRepository
from app.tools.files import FileManager
from app.tools.registry import build_default_tool_registry
from app.tools.tasks import TaskCreateTool, TaskExecuteTool, TaskListTool, TaskRegisterPathTool


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

    calendar_service = CalendarService(CalendarRepository(session))

    def _document_indexer_factory() -> DocumentIndexer:
        return DocumentIndexer(
            file_manager,
            DocumentRepository(session),
            LocalEmbeddingProvider(),
        )

    try:
        tool_registry = build_default_tool_registry(
            file_manager=file_manager,
            task_service=task_service,
            reminder_service=reminder_service,
            calendar_service=calendar_service,
            document_indexer_factory=_document_indexer_factory,
        )
    except TypeError:
        tool_registry = build_default_tool_registry(file_manager=file_manager)

    if hasattr(tool_registry, "tools"):
        for tool_class in (TaskCreateTool, TaskExecuteTool, TaskListTool, TaskRegisterPathTool):
            tool_registry.tools.setdefault(tool_class.name, tool_class(task_service))

    async def _permission_request(candidate: str) -> bool:
        if permission_prompt is None:
            return False
        granted = await permission_prompt(candidate)
        if not granted:
            return False
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
    )