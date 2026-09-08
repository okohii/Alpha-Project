"""Controle do PC no Windows: fechar processos e digitar texto em janelas."""
from __future__ import annotations

import ctypes
import os
import subprocess
from pathlib import Path
from typing import Any

from app.tools.apps import ApplicationLauncher
from app.tools.base import Tool, ToolPermission, ToolResult

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_RETURN = 0x0D
VK_TAB = 0x09


def running_process_names() -> list[str]:
    if os.name != "nt":
        return []
    try:
        output = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    names: list[str] = []
    for line in output.splitlines():
        parts = line.split('","')
        if len(parts) >= 2:
            name = parts[0].strip('"').strip()
            if name.lower().endswith(".exe"):
                names.append(name.lower())
    return names


def close_processes(names: list[str]) -> dict[str, Any]:
    if os.name != "nt":
        raise RuntimeError("Fechar aplicativos só é suportado no Windows.")
    killed: list[str] = []
    errors: list[str] = []
    for name in {n.lower() for n in names if n}:
        result = subprocess.run(
            ["taskkill", "/F", "/IM", name],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode == 0:
            killed.append(name)
        else:
            detail = (result.stderr or result.stdout or "").strip()
            errors.append(detail if detail else name)
    return {"killed": killed, "errors": errors}


def candidate_process_names(app_name: str, resolved_path: str | None) -> list[str]:
    names: list[str] = []
    if resolved_path:
        path = Path(resolved_path)
        names.append(path.stem.lower())
        names.append(path.name.lower())
    norm = app_name.strip().lower()
    if norm:
        names.append(norm)
    return list(dict.fromkeys(names))


def _match_running(candidates: list[str], running: list[str]) -> list[str]:
    running_noext = [name[:-4] for name in running]
    matched: list[str] = []
    for candidate in candidates:
        c = candidate.lower()
        for name, noext in zip(running, running_noext, strict=True):
            same = c == noext or c == name
            close = len(c) >= 4 and (c in noext or noext in c)
            if (same or close) and name not in matched:
                matched.append(name)
    return matched


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.c_ulong), ("u", _INPUTUNION)]


def _send_key(vk: int, scan: int, flags: int) -> None:
    user32 = ctypes.windll.user32
    extra = ctypes.c_ulong(0)
    inp = _INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki.wVk = vk
    inp.ki.wScan = scan
    inp.ki.dwFlags = flags
    inp.ki.dwExtraInfo = ctypes.pointer(extra)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))


def type_text(text: str) -> int:
    if os.name != "nt":
        raise RuntimeError("Digitar texto só é suportado no Windows.")
    sent = 0
    for char in str(text):
        if char == "\n":
            _send_key(VK_RETURN, 0, 0)
            _send_key(VK_RETURN, 0, KEYEVENTF_KEYUP)
        elif char == "\t":
            _send_key(VK_TAB, 0, 0)
            _send_key(VK_TAB, 0, KEYEVENTF_KEYUP)
        else:
            _send_key(0, ord(char), KEYEVENTF_UNICODE)
            _send_key(0, ord(char), KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)
        sent += 1
    return sent


def activate_window(app_name: str) -> bool:
    if os.name != "nt":
        return False
    escaped = (app_name or "").replace("'", "''")
    script = (
        f"$wshell = New-Object -ComObject wscript.shell; "
        f"$wshell.AppActivate('{escaped}')"
    )
    if not escaped:
        return False
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip().lower() == "true"


class CloseAppTool(Tool):
    name = "close_app"
    description = (
        "Fecha um aplicativo que está aberto no computador pelo nome. "
        "Ex.: 'feche o chrome', 'fecha o discord'. Encerra o processo do programa."
    )
    permission = ToolPermission.write

    def __init__(self, launcher: ApplicationLauncher) -> None:
        self.launcher = launcher

    async def execute(self, **kwargs: Any) -> ToolResult:
        app = str(kwargs.get("app", "")).strip()
        if not app:
            return ToolResult(
                name=self.name, success=False, data={}, error="Informe o aplicativo a fechar."
            )
        try:
            info = self.launcher.resolve(app)
        except ValueError as exc:
            return ToolResult(name=self.name, success=False, data={}, error=str(exc))

        running = running_process_names()
        candidates = candidate_process_names(info.get("app", ""), info.get("path"))
        matched = _match_running(candidates, running)
        if not matched:
            return ToolResult(
                name=self.name,
                success=True,
                data={"app": info.get("app", app), "running": False},
                error=None,
            )
        result = close_processes(matched)
        return ToolResult(
            name=self.name,
            success=not result["errors"],
            data={"app": info.get("app", app), **result},
            error="; ".join(result["errors"]) if result["errors"] else None,
        )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "app": {
                    "type": "string",
                    "description": "Nome do aplicativo a fechar (ex.: 'chrome')",
                },
            },
            "required": ["app"],
        }


class TypeTextTool(Tool):
    name = "type_text"
    description = (
        "Digita texto na janela ativa do computador. Aceita acentos e '\n' para Enter. "
        "Ex.: 'escreva olá mundo no bloco de notas'. Se passar 'app', tenta ativar a janela "
        "do aplicativo antes de digitar."
    )
    permission = ToolPermission.write

    def __init__(self, launcher: ApplicationLauncher) -> None:
        self.launcher = launcher

    async def execute(self, **kwargs: Any) -> ToolResult:
        text = str(kwargs.get("text", ""))
        if not text:
            return ToolResult(
                name=self.name, success=False, data={}, error="Informe o texto a digitar."
            )
        window = str(kwargs.get("app", "") or "").strip()
        focused = True
        if window:
            try:
                info = self.launcher.resolve(window)
                names = candidate_process_names(info.get("app", ""), info.get("path"))
                focused = any(activate_window(candidate) for candidate in names)
            except ValueError:
                activate_window(window)
        try:
            typed = type_text(text)
        except (OSError, RuntimeError) as exc:
            return ToolResult(name=self.name, success=False, data={}, error=str(exc))
        return ToolResult(
            name=self.name,
            success=True,
            data={"typed_chars": typed, "window": window or "focused", "focused": focused},
        )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Texto a digitar"},
                "app": {
                    "type": "string",
                    "description": "Opcional: nome do aplicativo cuja janela deve receber o texto",
                },
            },
            "required": ["text"],
        }