from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from app.db.models import SystemEventRecord
from app.skills.files.service import FileManager
from app.tasks.service import ManagedPathRepository, TaskExecutorService, TaskRepository
from app.tools.registry import build_default_tool_registry

logger = logging.getLogger("app.calendar.runner")

ActionRunner = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


class CalendarActionRunner:
    """Executa ações agendadas no calendário."""

    def __init__(self, session: Any) -> None:
        self.session = session
        self._registry = None

    async def run(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if action == "notify":
            message = str(params.get("message") or "")
            payload = {"message": message, **params}
            self.session.add(SystemEventRecord(type="calendar_event", payload=payload))
            await self.session.commit()
            return {"message": message, "notified": True}
        if action == "macro_run":
            from app.macros.service import macro_service
            macro_id = str(params.get("macro_id", "") or "")
            name = str(params.get("name", "") or "")
            if not macro_id and name:
                macro = await macro_service.search_macro(name)
                if macro:
                    macro_id = macro.id
            if macro_id:
                log = await macro_service.execute_macro(macro_id, params)
                return {"status": log.status, "steps_executed": log.steps_executed}
            return {"error": "Macro não encontrada"}
        if action in ("open_app", "open_url", "open_file", "task_execute"):
            registry = await self._registry_for_session()
            result = await registry.execute(action, **params)
            if not result.success:
                raise RuntimeError(str(result.error or "Falha desconhecida"))
            return dict(result.data or {})
        raise ValueError(f"Ação não permitida no calendário: {action}")

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


class CalendarRunner:
    """Loop assíncrono que verifica e executa eventos do calendário vencidos."""

    def __init__(
        self,
        session_factory: Any,
        *,
        interval_seconds: float = 30.0,
        on_notify: Callable[[str], None] | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.interval_seconds = interval_seconds
        self.on_notify = on_notify
        self._task: asyncio.Task[Any] | None = None
        self._running = False

    async def tick(self) -> list[dict[str, Any]]:
        from app.calendar.service import CalendarRepository, CalendarService
        
        async with self.session_factory() as session:
            runner = CalendarActionRunner(session)
            service = CalendarService(CalendarRepository(session))
            results = await service.process_due_events(runner.run)
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
            except Exception:  # noqa: BLE001 - falha no ciclo não derruba o runner
                logger.exception("Falha no ciclo do calendário")
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
