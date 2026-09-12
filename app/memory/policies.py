from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from app.memory.types import MemoryType


def utcnow() -> datetime:
    return datetime.now(UTC)


def normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def is_expired(expiration: datetime | None, *, now: datetime | None = None) -> bool:
    normalized = normalize_datetime(expiration)
    return normalized is not None and normalized <= (now or utcnow())


def recency_score(created_at: datetime | None, *, now: datetime | None = None, half_life_days: float = 30.0) -> float:
    created = normalize_datetime(created_at)
    if created is None:
        return 0.0
    age_seconds = max(0.0, ((now or utcnow()) - created).total_seconds())
    half_life = max(1.0, half_life_days * 86400.0)
    return math.exp(-math.log(2.0) * age_seconds / half_life)


def retrieval_score(
    similarity: float,
    importance: float,
    created_at: datetime | None,
    memory_type: str,
    *,
    context_score: float = 0.0,
    now: datetime | None = None,
) -> float:
    """Ranking final: relevância + importância + recência + contexto.

    Preferences recebem um pequeno bônus porque representam configuração
    persistente, mas continuam sujeitas à relevância da consulta.
    """
    relevance = max(0.0, min(1.0, similarity))
    importance_score = max(0.0, min(1.0, importance))
    recent = recency_score(created_at, now=now)
    contextual = max(0.0, min(1.0, context_score))
    type_bonus = 0.05 if memory_type == MemoryType.PREFERENCE else 0.0
    return (
        0.55 * relevance
        + 0.20 * importance_score
        + 0.15 * recent
        + 0.10 * contextual
        + type_bonus
    )


def preference_key(content: str, metadata: dict[str, Any] | None = None) -> str:
    metadata = metadata or {}
    explicit = str(metadata.get("key") or metadata.get("preference_key") or "").strip().lower()
    if explicit:
        return explicit
    words = " ".join((content or "").lower().split())
    return words[:160]


def is_valid_memory_type(value: str) -> bool:
    return value in {item.value for item in MemoryType}
