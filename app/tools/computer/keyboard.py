"""Controle de teclado no Windows: digitar texto e pressionar combinações de teclas."""

from __future__ import annotations

import ctypes
import os
import subprocess
from typing import Any

from app.tools.base import Tool, ToolPermission, ToolResult
from app.tools.computer.application import ApplicationLauncher
from app.tools.computer.process import candidate_process_names

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_RETURN = 0x0D
VK_TAB = 0x09


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