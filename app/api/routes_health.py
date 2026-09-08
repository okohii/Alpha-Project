from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings
from app.llm.ollama import OllamaProvider

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    settings = get_settings()
    ollama_status = "unknown"
    try:
        ollama_status = "ok" if await OllamaProvider().health() else "down"
    except Exception:
        ollama_status = "down"
    return {
        "status": "ok",
        "services": {
            "database": "ok",
            "ollama": ollama_status,
            "stt": "ok" if settings.stt_enabled else "disabled",
            "tts": "ok" if settings.tts_enabled else "disabled",
            "web": "available" if settings.allow_web else "disabled",
        },
    }


@router.get("/health/llm")
async def health_llm() -> dict:
    provider = OllamaProvider()
    try:
        available = await provider.health()
    except Exception as exc:  # pragma: no cover
        return {"status": "down", "detail": str(exc)}
    return {"status": "ok" if available else "down"}


@router.get("/health/database")
async def health_database() -> dict:
    return {"status": "ok"}
