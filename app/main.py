from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import FastAPI

from app.api.routes_chat import router as chat_router
from app.api.routes_conversations import router as conversations_router
from app.api.routes_documents import router as documents_router
from app.api.routes_health import router as health_router
from app.api.routes_macros import router as macros_router
from app.api.routes_memory import router as memory_router
from app.api.routes_settings import router as settings_router
from app.api.routes_tasks import router as tasks_router
from app.api.routes_voice import router as voice_router
from app.avatar import avatar_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import AsyncSessionLocal, initialize_database
from app.macros.service import macro_service
from app.notification import play_notification_sound, show_notification
from app.overlay import overlay_router
from app.reminders.runner import SchedulerRunner

logger = logging.getLogger("app.main")

configure_logging()
settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0")

_scheduler_runner: SchedulerRunner | None = None
_purge_task: Any | None = None


async def _purge_memory_loop() -> None:
    """P32: expurga memórias expiradas periodicamente (não só no startup)."""
    while True:
        try:
            async with AsyncSessionLocal() as session:
                from app.memory.embeddings import LocalEmbeddingProvider
                from app.memory.repository import SqliteMemoryRepository
                from app.memory.service import MemoryService

                service = MemoryService(SqliteMemoryRepository(session), LocalEmbeddingProvider())
                purged = await service.purge_expired()
                if purged:
                    logger.info("[memory] purge_expired removed=%d", purged)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - ciclo não derruba o backend
            logger.exception("[memory] purge_expired failed noisily")
        await asyncio.sleep(max(1.0, settings.memory_purge_interval_hours * 3600))


def _notify_blocking(message: str) -> None:
    """Parte bloqueante da notificação (som + toast) — roda fora do event loop."""
    play_notification_sound()
    show_notification("ALPHA - Lembrete", message)


def _on_reminder_notification(message: str) -> None:
    """Chamado quando um lembrete é disparado (despacha para off-thread)."""
    try:
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, _notify_blocking, message)
    except RuntimeError:
        _notify_blocking(message)


@app.on_event("startup")
async def app_startup() -> None:
    global _scheduler_runner, _purge_task
    await initialize_database()
    _scheduler_runner = SchedulerRunner(
        AsyncSessionLocal,
        interval_seconds=settings.scheduler_interval_seconds,
        on_notify=_on_reminder_notification,
    )
    await _scheduler_runner.start()
    await macro_service.start_scheduler()
    _purge_task = asyncio.create_task(_purge_memory_loop())


@app.on_event("shutdown")
async def app_shutdown() -> None:
    global _purge_task
    if _scheduler_runner is not None:
        await _scheduler_runner.stop()
    await macro_service.stop_scheduler()
    if _purge_task is not None:
        _purge_task.cancel()
        try:
            await _purge_task
        except asyncio.CancelledError:
            pass
        _purge_task = None


app.include_router(health_router)
app.include_router(chat_router)
app.include_router(voice_router)
app.include_router(memory_router)
app.include_router(documents_router)
app.include_router(macros_router)
app.include_router(conversations_router)
app.include_router(settings_router)
app.include_router(tasks_router)
app.include_router(overlay_router)
app.include_router(avatar_router)
