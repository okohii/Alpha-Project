from __future__ import annotations

import asyncio
import logging
import math
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware

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
from app.db.models import Memory
from app.db.session import AsyncSessionLocal, initialize_database
from app.macros.service import macro_service
from app.notification import play_notification_sound, show_notification
from app.overlay import overlay_router
from app.reminders.runner import SchedulerRunner

logger = logging.getLogger("app.main")

configure_logging()
settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["127.0.0.1", "localhost", "::1"],
)

_scheduler_runner: SchedulerRunner | None = None
_purge_task: Any | None = None


async def _prune_memories() -> int:
    """Mantém a memória limitada por idade, importância e quantidade."""
    now = datetime.now(UTC)
    removed = 0
    max_items = max(1, int(settings.memory_max_items))
    max_age_days = max(0.0, float(settings.memory_max_age_days))
    decay_days = max(1.0, float(settings.memory_importance_decay_days))
    cutoff = now - timedelta(days=max_age_days)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            __import__("sqlalchemy").select(Memory)
            .order_by(Memory.importance.desc(), Memory.updated_at.desc())
        )
        memories = list(result.scalars().all())

        for memory in memories:
            if memory.expiration is not None and memory.expiration <= now:
                await session.delete(memory)
                removed += 1
                continue
            created = memory.created_at
            if created is not None and created < cutoff and memory.memory_type not in {"profile", "preference"}:
                await session.delete(memory)
                removed += 1
                continue
            if created is not None:
                age_days = max(0.0, (now - created).total_seconds() / 86400.0)
                decay = math.exp(-age_days / decay_days)
                target_importance = max(0.05, min(1.0, float(memory.importance) * decay))
                if abs(target_importance - float(memory.importance)) >= 0.01:
                    memory.importance = target_importance

        await session.flush()
        survivors = [memory for memory in memories if memory not in session.deleted]
        if len(survivors) > max_items:
            survivors.sort(key=lambda item: (float(item.importance), item.updated_at or item.created_at or now))
            for memory in survivors[: len(survivors) - max_items]:
                await session.delete(memory)
                removed += 1
        await session.commit()
    return removed


async def _purge_memory_loop() -> None:
    """Expurga memórias expiradas e aplica retenção/decay periodicamente."""
    while True:
        try:
            purged = await _prune_memories()
            if purged:
                logger.info("[memory] retention_cleanup removed=%d", purged)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("[memory] retention cleanup failed noisily")
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
