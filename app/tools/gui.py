"""Automação de interface no Windows: mouse, teclado (atalhos) e captura de tela."""

from __future__ import annotations

import ctypes
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from app.tools.base import Tool, ToolPermission, ToolResult
from app.tools.pc import KEYEVENTF_KEYUP, _send_key

MODIFIER_VK: dict[str, int] = {
    "ctrl": 0x11,
    "control": 0x11,
    "shift": 0x10,
    "alt": 0x12,
    "win": 0x5B,
    "windows": 0x5B,
}

SPECIAL_VK: dict[str, int] = {
    "enter": 0x0D,
    "return": 0x0D,
    "tab": 0x09,
    "esc": 0x1B,
    "escape": 0x1B,
    "space": 0x20,
    "backspace": 0x08,
    "delete": 0x2E,
    "del": 0x2E,
    "insert": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
    "capslock": 0x14,
}
for _f in range(1, 25):
    SPECIAL_VK[f"f{_f}"] = 0x6F + _f

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


def _key_vk(key: str) -> int | None:
    k = (key or "").strip().lower()
    if k in SPECIAL_VK:
        return SPECIAL_VK[k]
    if len(k) == 1 and k.isalpha() and k.isascii():
        return ord(k.upper())
    return None


def press_sequence(sequence: str) -> int:
    if os.name != "nt":
        raise RuntimeError("Simular teclado só é suportado no Windows.")
    parts = [p.strip() for p in str(sequence).replace(" ", "").split("+") if p.strip()]
    if not parts:
        raise ValueError("Informe uma tecla ou combinação, ex.: 'ctrl+k', 'enter'.")
    main = parts[-1]
    vk = _key_vk(main)
    if vk is None:
        raise ValueError(f"Tecla não reconhecida: {main}")
    mods: list[int] = []
    for modifier in parts[:-1]:
        if modifier in MODIFIER_VK:
            mods.append(MODIFIER_VK[modifier])
        else:
            raise ValueError(f"Modificador não reconhecido: {modifier}")
    for mod in mods:
        _send_key(mod, 0, 0)
    _send_key(vk, 0, 0)
    _send_key(vk, 0, KEYEVENTF_KEYUP)
    for mod in reversed(mods):
        _send_key(mod, 0, KEYEVENTF_KEYUP)
    return 1


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


def capture_screen(path: str) -> str:
    if os.name != "nt":
        raise RuntimeError("Capturar tela só é suportado no Windows.")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    escaped = str(target).replace("'", "''")
    script = (
        "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
        "$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
        "$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height; "
        "$g = [System.Drawing.Graphics]::FromImage($bmp); "
        "$g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size); "
        f"$bmp.Save('{escaped}'); "
        "$g.Dispose(); $bmp.Dispose()"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0 or not target.exists():
        detail = (result.stderr or "falha ao capturar a tela").strip()
        raise RuntimeError(detail)
    return str(target)


class PressKeyTool(Tool):
    name = "press_key"
    description = (
        "Aperta uma tecla ou combinação na janela ativa do computador. "
        "Ex.: 'ctrl+k', 'enter', 'tab', 'alt+tab', 'ctrl+shift+tab', 'espaço'."
    )
    permission = ToolPermission.write

    async def execute(self, **kwargs: Any) -> ToolResult:
        key = str(kwargs.get("key", "") or "")
        try:
            sent = press_sequence(key)
        except (ValueError, OSError, RuntimeError) as exc:
            return ToolResult(name=self.name, success=False, data={}, error=str(exc))
        return ToolResult(name=self.name, success=True, data={"key": key, "pressed": sent})

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Tecla ou combinação, ex.: 'ctrl+k'"},
            },
            "required": ["key"],
        }


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


class ScreenshotTool(Tool):
    name = "screenshot"
    description = (
        "Captura a tela inteira e salva um PNG dentro das pastas permitidas; "
        "retorna o caminho do arquivo e, se o modelo de visão estiver configurado, "
        "uma descrição visual da tela (apps e botões com coordenadas aproximadas)."
    )
    permission = ToolPermission.write

    def __init__(self, file_manager: Any, vision: Any = None) -> None:
        self.file_manager = file_manager
        self.vision = vision

    async def execute(self, **kwargs: Any) -> ToolResult:
        path = str(kwargs.get("path", "") or "").strip()
        try:
            if path:
                target = self.file_manager._resolve_input(path, search=False)
            else:
                base = (
                    self.file_manager.allowed_directories[0]
                    if self.file_manager.allowed_directories
                    else Path.cwd()
                )
                folder = Path(base) / "alpha_screenshots"
                folder.mkdir(parents=True, exist_ok=True)
                target = folder / f"screen_{int(time.time())}.png"
            saved = capture_screen(str(target))
        except (ValueError, OSError, RuntimeError) as exc:
            return ToolResult(name=self.name, success=False, data={}, error=str(exc))
        data: dict[str, Any] = {"path": saved, "saved": True}
        if self.vision is not None and self.vision.available():
            try:
                data["screen"] = await self.vision.describe(saved)
                data["vision"] = True
            except Exception as exc:
                data["vision"] = False
                data["vision_error"] = str(exc)
        return ToolResult(
            name=self.name,
            success=True,
            data={
                **data,
                "hint": (
                    "Confira a descrição 'screen' (com coordenadas) para clicar "
                    "em botões com mouse_click."
                ),
            },
        )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Opcional: caminho do PNG dentro das pastas permitidas",
                },
            },
        }


class VerifyScreenTool(Tool):
    name = "verify_screen"
    description = (
        "Tira um screenshot, envia ao modelo de visão e responde se uma meta foi atingida. "
        "Útil para confirmar que uma ação (clique, digitação, abertura de app) teve o efeito "
        "esperado. Retorne JSON com achieved, feedback e attempts."
    )
    permission = ToolPermission.read

    def __init__(self, file_manager: Any, verifier: Any | None = None) -> None:
        self.file_manager = file_manager
        self.verifier = verifier

    async def execute(self, **kwargs: Any) -> ToolResult:
        if self.verifier is None or not self.verifier.available():
            return ToolResult(
                name=self.name,
                success=False,
                data={},
                error="Verificação visual indisponível (defina OLLAMA_VISION_MODEL).",
            )
        goal = str(kwargs.get("goal", "") or "").strip()
        max_retries = int(kwargs.get("max_retries", 0) or 0)
        if not goal:
            return ToolResult(
                name=self.name,
                success=False,
                data={},
                error="Informe a meta a verificar.",
            )
        base = (
            self.file_manager.allowed_directories[0]
            if self.file_manager.allowed_directories
            else Path.cwd()
        )
        folder = Path(base) / "alpha_screenshots"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"verify_{int(time.time())}.png"
        try:
            saved = capture_screen(str(target))
        except (OSError, RuntimeError) as exc:
            return ToolResult(name=self.name, success=False, data={}, error=str(exc))
        result = await self.verifier.verify(saved, goal, max_retries=max_retries)
        return ToolResult(
            name=self.name,
            success=True,
            data={
                "path": saved,
                "achieved": result["achieved"],
                "attempts": result["attempts"],
                "feedback": result["last"]["feedback"],
                "details": result.get("details", []),
            },
        )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": (
                        "O que você espera ver na tela após a ação "
                        "(ex.: 'github aberto no navegador')."
                    ),
                },
                "max_retries": {
                    "type": "integer",
                    "description": (
                        "Quantas novas capturas pode tirar caso não confirme "
                        "de primeira (padrão 0)."
                    ),
                },
            },
            "required": ["goal"],
        }
