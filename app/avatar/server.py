from __future__ import annotations

import asyncio
import json
import logging
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

# Existing implementation above the avatar asset endpoint remains unchanged.

UI_DIR = Path(__file__).resolve().parent / "ui"
router = APIRouter(prefix="/avatar")


@router.get("/health")
async def avatar_health() -> dict[str, str]:
    return {"status": "ok", "service": "avatar"}


@router.get("/", include_in_schema=False)
async def avatar_index() -> FileResponse:
    return FileResponse(UI_DIR / "index.html")


@router.get("/ui/{file_path:path}", include_in_schema=False)
async def avatar_asset(file_path: str) -> FileResponse:
    """Serve a static avatar UI asset from the bundled UI directory."""
    root = UI_DIR.resolve()
    candidate = (root / file_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="asset not found")
    if not candidate.is_file():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="asset not found")
    return FileResponse(candidate)
