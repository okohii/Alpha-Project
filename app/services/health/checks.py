from __future__ import annotations

from app.core.config import get_settings
from app.llm.ollama import OllamaProvider


async def collect_health() -> dict:
    settings = get_settings()
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