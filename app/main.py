from __future__ import annotations

from fastapi import FastAPI

from app.api.routes_chat import router as chat_router
from app.api.routes_conversations import router as conversations_router
from app.api.routes_documents import router as documents_router
from app.api.routes_health import router as health_router
from app.api.routes_memory import router as memory_router
from app.api.routes_settings import router as settings_router
from app.api.routes_tasks import router as tasks_router
from app.api.routes_voice import router as voice_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import AsyncSessionLocal, initialize_database
from app.reminders.runner import SchedulerRunner

configure_logging()
settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0")

_scheduler_runner: SchedulerRunner | None = None


@app.on_event("startup")
async def app_startup() -> None:
    global _scheduler_runner
    await initialize_database()
    if settings.scheduler_enabled:
        _scheduler_runner = SchedulerRunner(
            AsyncSessionLocal, interval_seconds=settings.scheduler_interval_seconds
        )
        await _scheduler_runner.start()


@app.on_event("shutdown")
async def app_shutdown() -> None:
    if _scheduler_runner is not None:
        await _scheduler_runner.stop()


app.include_router(health_router)
app.include_router(chat_router)
app.include_router(voice_router)
app.include_router(memory_router)
app.include_router(documents_router)
app.include_router(conversations_router)
app.include_router(settings_router)
app.include_router(tasks_router)