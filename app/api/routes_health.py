from __future__ import annotations

from fastapi import APIRouter

from app.llm.ollama import OllamaProvider
from app.services.health import collect_health

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    return await collect_health()


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