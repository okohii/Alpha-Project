"""Controle de mouse no Windows: mover, clicar e rolar."""

from __future__ import annotations

import ctypes
import os
from typing import Any

from app.tools.base import Tool, ToolPermission, ToolResult

MOUSE_DOWN: dict[str, int] = {
    "left": 0x0002,
    "right": 0x0008,
    "middle": 0x0020,
    "x1": 0x0080,
    "x2": 0x0200,
}
MOUSE_UP: dict[str, int] = {
    "left": 0x0004,
    "right": 0x0010,
    "middle": 0x0040,
    "x1": 0x0100,
    "x2": 0x0400,
}


def _native_set_cursor_pos(x: int, y: int) -> None:
    ctypes.windll.user32.SetCursorPos(int(x), int(y))


def _native_mouse_event(flags: int, data: int = 0) -> None:
    ctypes.windll.user32.mouse_event(flags, 0, 0, int(data), 0)


def mouse_move(x: int, y: int) -> None:
    if os.name != "nt":
        raise RuntimeError("Controlar o mouse só é suportado no Windows.")
    _native_set_cursor_pos(x, y)


def mouse_click(
    x: int | None = None,
    y: int | None = None,
    button: str = "left",
    clicks: int = 1,
) -> None:
    if os.name != "nt":
        raise RuntimeError("Controlar o mouse só é suportado no Windows.")
    if x is not None and y is not None:
        mouse_move(x, y)
    button = (button or "left").lower()
    down = MOUSE_DOWN.get(button, MOUSE_DOWN["left"])
    up = MOUSE_UP.get(button, MOUSE_UP["left"])
    for _ in range(max(1, int(clicks))):
        _native_mouse_event(down)
        _native_mouse_event(up)


def mouse_scroll(delta: int) -> None:
    if os.name != "nt":
        raise RuntimeError("Rolar o mouse só é suportado no Windows.")
    _native_mouse_event(0x0800, int(delta) * 120)


class MouseClickTool(Tool):
    name = "mouse_click"
    description = (
        "Move o ponteiro do mouse até (x, y) em pixels da tela e clica. "
        "Ex.: 'clique no botão' → mouse_click x=560 y=340. "
        "button: left/right/middle; clicks: número de cliques (por padrão 1)."
    )
    permission = ToolPermission.write

    async def execute(self, **kwargs: Any) -> ToolResult:
        x = kwargs.get("x")
        y = kwargs.get("y")
        button = str(kwargs.get("button", "left") or "left")
        clicks = int(kwargs.get("clicks", 1) or 1)
        try:
            mouse_click(x, y, button=button, clicks=clicks)
        except (ValueError, OSError, RuntimeError) as exc:
            return ToolResult(name=self.name, success=False, data={}, error=str(exc))
        return ToolResult(
            name=self.name,
            success=True,
            data={"x": x, "y": y, "button": button, "clicks": clicks},
        )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "x": {
                    "type": "integer",
                    "description": "Coordenada X em pixels (opcional — usa a posição atual)",
                },
                "y": {"type": "integer", "description": "Coordenada Y em pixels (opcional)"},
                "button": {
                    "type": "string",
                    "description": "Botão: left, right ou middle (padrão left)",
                },
                "clicks": {
                    "type": "integer",
                    "description": "Número de cliques (padrão 1)",
                },
            },
        }


class MouseScrollTool(Tool):
    name = "mouse_scroll"
    description = "Rola a janela ativa do computador. Positivo rola para baixo, negativo para cima."
    permission = ToolPermission.write

    async def execute(self, **kwargs: Any) -> ToolResult:
        delta = int(kwargs.get("delta", 0) or 0)
        try:
            mouse_scroll(delta)
        except (ValueError, OSError, RuntimeError) as exc:
            return ToolResult(name=self.name, success=False, data={}, error=str(exc))
        return ToolResult(name=self.name, success=True, data={"delta": delta})

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "delta": {
                    "type": "integer",
                    "description": "Clicks de rolagem (3 = desce, -3 = sobe)",
                },
            },
            "required": ["delta"],
        }