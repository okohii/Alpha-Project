from __future__ import annotations

from fastapi import APIRouter

from app.llm.ollama import OllamaProvider
from app.services.health.metrics import metrics

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
    """Verificação REAL da conexão com o banco (SELECT 1)."""
    from sqlalchemy import text

    from app.db.session import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - health não derruba
        return {"status": "down", "detail": str(exc)}
    return {"status": "ok"}


@router.get("/metrics")
async def metrics_endpoint() -> dict:
    """Métricas em formato Prometheus text."""
    return {"status": "ok", "metrics": metrics.render()}


async def collect_health() -> dict:
    from app.services.health import collect_health as _collect_health

    return await _collect_health()