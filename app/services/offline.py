from __future__ import annotations

from enum import StrEnum

import httpx

from app.core.config import get_settings


class ConnectivityState(StrEnum):
    OFFLINE = "OFFLINE"
    ONLINE = "ONLINE"
    UNKNOWN = "UNKNOWN"


async def detect_connectivity() -> ConnectivityState:
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=settings.offline_timeout_seconds) as client:
            response = await client.get("https://example.com")
            return ConnectivityState.ONLINE if response.is_success else ConnectivityState.OFFLINE
    except Exception:
        return ConnectivityState.OFFLINE
