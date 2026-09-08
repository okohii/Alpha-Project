from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from app.db.models import SystemEventRecord
from app.reminders.service import SAFE_ACTIONS, ReminderRepository, ReminderService
from app.tasks.service import ManagedPathRepository, TaskExecutorService, TaskRepository
from app.tools.files import FileManager
from app.tools.registry import build_default_tool_registry

logger = logging.getLogger("app.reminders.runner")

ActionRunner = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


class RegistryActionRunner:
    """Executa ações agendadas por meio do registro de ferramentas.

    Apenas ações seguras (SAFE_ACTIONS) + "notify" são permitidas; qualquer outra é
    rejeitada antes de tocar no sistema.
    """

    def __init__(self, session: Any) -> None:
        self.session = session
        self._registry = None

    async def run(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if action == "notify":
            message = str(params.get("message") or "")
            payload = {"message": message, **params}
            self.session.add(SystemEventRecord(type="reminder", payload=payload))
            await self.session.commit()
            return {"message": message, "notified": True}
        if action not in SAFE_ACTIONS:
            raise ValueError(f"Ação não permitida no agendador: {action}")
        registry = await self._registry_for_session()
        result = await registry.execute(action, **params)
        if not result.success:
            raise RuntimeError(str(result.error or "Falha desconhecida"))
        return dict(result.data or {})

    async def _registry_for_session(self) -> Any:
        if self._registry is not None:
            return self._registry
        records = await ManagedPathRepository(self.session).list()
        file_manager = FileManager()
        file_manager.allowed_directories = [
            Path(record.path).expanduser().resolve()
            for record in records
            if getattr(record, "is_allowed", 1) and getattr(record, "path", None)
        ]
        task_service = TaskExecutorService(
            task_repository=TaskRepository(self.session),
            managed_path_repository=ManagedPathRepository(self.session),
            file_manager=file_manager,
        )
        self._registry = build_default_tool_registry(
            file_manager=file_manager, task_service=task_service
        )
        return self._registry


class SchedulerRunner:
    """Loop assíncrono que verifica e executa lembretes vencidos."""

    def __init__(
        self,
        session_factory: Any,
        *,
        interval_seconds: float = 15.0,
        on_notify: Callable[[str], None] | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.interval_seconds = interval_seconds
        self.on_notify = on_notify
        self._task: asyncio.Task[Any] | None = None
        self._running = False

    async def tick(self) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            runner = RegistryActionRunner(session)
            service = ReminderService(ReminderRepository(session))
            results = await service.process_due(runner.run)
        for item in results:
            is_notify = item.get("success") and item.get("action") == "notify"
            if is_notify and self.on_notify is not None:
                message = (item.get("result") or {}).get("message") or item.get("title", "")
                if message:
                    self.on_notify(message)
        return results

    async def run_forever(self) -> None:
        while self._running:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - falha no ciclo não derruba o agendador
                logger.exception("Falha no ciclo do agendador")
            await asyncio.sleep(self.interval_seconds)

    async def start(self) -> asyncio.Task[Any]:
        if self._running:
            return self._task
        self._running = True
        self._task = asyncio.create_task(self.run_forever())
        return self._task

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None