from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

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
from app.database.session import AsyncSessionLocal, initialize_database
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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory="frontend"), name="static")
app.include_router(health_router)
app.include_router(chat_router)
app.include_router(voice_router)
app.include_router(memory_router)
app.include_router(documents_router)
app.include_router(conversations_router)
app.include_router(settings_router)
app.include_router(tasks_router)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(Path("frontend") / "index.html")
