"""Overlay Desktop do ALPHA.

Interface visual sobre o Alpha Core — NUNCA um agente novo.
Consome eventos do ``EventBus`` e apenas reflete o estado/falos do agente.
"""

from __future__ import annotations

from pathlib import Path

from app.overlay.server import router as overlay_router

UI_DIR = Path(__file__).parent / "ui"

__all__ = ["overlay_router", "UI_DIR"]