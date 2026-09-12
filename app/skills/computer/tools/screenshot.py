"""Captura de tela no Windows e tools de screenshot/verificação visual."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any

from app.tools.base import Tool, ToolPermission, ToolResult


def capture_screen(path: str) -> str:
    """Capture the complete Windows virtual desktop, including every monitor.

    Using VirtualScreen instead of PrimaryScreen is intentional: verification must
    be able to find a target on any connected display, including monitors arranged
    to the left/top of the primary display (negative virtual coordinates).
    """
    if os.name != "nt":
        raise RuntimeError("Capturar tela só é suportado no Windows.")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    escaped = str(target).replace("'", "''")
    script = (
        "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
        "$b = [System.Windows.Forms.SystemInformation]::VirtualScreen; "
        "$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height; "
        "$g = [System.Drawing.Graphics]::FromImage($bmp); "
        "$g.CopyFromScreen($b.Left, $b.Top, 0, 0, $b.Size); "
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
        detail = (result.stderr or "falha ao capturar o desktop virtual").strip()
        raise RuntimeError(detail)
    return str(target)


class ScreenshotTool(Tool):
    name = "screenshot"
    description = (
        "Captura o desktop virtual inteiro (todos os monitores) e salva um PNG dentro "
        "das pastas permitidas; retorna o caminho e, se a visão estiver configurada, "
        "uma descrição visual dos apps e botões com coordenadas aproximadas."
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
        data: dict[str, Any] = {"path": saved, "saved": True, "scope": "virtual_desktop_all_monitors"}
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
                    "A imagem cobre todos os monitores. Use as coordenadas no espaço "
                    "virtual do Windows ao clicar com mouse_click."
                ),
            },
        )


class VerifyScreenTool(Tool):
    name = "verify_screen"
    description = (
        "Tira um screenshot do desktop virtual inteiro (todos os monitores), envia ao "
        "modelo de visão e responde se uma meta foi atingida. Útil para confirmar que "
        "uma ação teve o efeito esperado em qualquer monitor."
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
            return ToolResult(name=self.name, success=False, data={}, error="Informe a meta a verificar.")
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
                "scope": "virtual_desktop_all_monitors",
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
                "goal": {"type": "string", "description": "O que você espera ver após a ação."},
                "max_retries": {"type": "integer", "description": "Número de novas verificações visuais."},
            },
            "required": ["goal"],
        }
