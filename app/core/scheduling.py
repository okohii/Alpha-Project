"""Primitivas compartilhadas de tempo usadas por Calendar e Reminder."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

BRASILIA_TZ = timezone(timedelta(hours=-3), name="America/Sao_Paulo")


def as_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def now_utc() -> datetime:
    return datetime.now(UTC)


def as_local(value: datetime | None) -> datetime | None:
    normalized = as_utc(value)
    return normalized.astimezone(BRASILIA_TZ) if normalized is not None else None


def format_local(value: datetime | None) -> str | None:
    local = as_local(value)
    return local.strftime("%Y-%m-%d %H:%M") if local else None
