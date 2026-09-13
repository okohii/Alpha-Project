"""Controle de teclado no Windows: digitar texto e pressionar combinações de teclas."""

import asyncio
import ctypes
import os
import subprocess
import time
from typing import Any

from app.skills.computer.service import ApplicationLauncher
from app.skills.computer.tools.process import candidate_process_names
from app.tools.base import Tool, ToolPermission, ToolResult

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_RETURN = 0x0D
VK_TAB = 0x09

# Estruturas para SendInput
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


# GetForegroundWindow + GetWindowText para detectar a janela ativa real
_user32 = ctypes.windll.user32
_user32.GetForegroundWindow.restype = ctypes.c_void_p
_user32.GetWindowTextW.restype = ctypes.c_int
_user32.GetWindowTextLengthW.restype = ctypes.c_int


def _get_foreground_window_title() -> str | None:
    """Retorna o título da janela em primeiro plano (None se não houver)."""
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return None
    length = _user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return None
    buf = ctypes.create_unicode_buffer(length + 1)
    _user32.GetWindowTextW(hwnd, buf, length + 1)
    title = buf.value.strip()
    return title if title else None


def _send_key(vk: int, scan: int, flags: int) -> None:
    extra = ctypes.c_ulong(0)
    inp = _INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki.wVk = vk
    inp.ki.wScan = scan
    inp.ki.dwFlags = flags
    inp.ki.dwExtraInfo = ctypes.pointer(extra)
    _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))


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
        time.sleep(0.01)
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
        "Digita texto na janela ativa do computador. Aceita acentos e '\\n' para Enter. "
        "Ex.: 'escreva olá mundo no bloco de notas'. Se passar 'app', ativa a janela do "
        "aplicativo ANTES de digitar; se a ativação falhar, a ferramenta FALHA e não digita "
        "(para evitar digitar na janela errada). Sem 'app', digita na janela ativa e reporta "
        "qual janela recebeu o texto."
    )
    permission = ToolPermission.write

    def __init__(self, launcher: ApplicationLauncher) -> None:
        self.launcher = launcher

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            data = await asyncio.to_thread(self._execute_blocking, kwargs)
        except (OSError, RuntimeError, ValueError) as exc:
            return ToolResult(name=self.name, success=False, data={}, error=str(exc))
        return ToolResult(name=self.name, success=True, data=data)

    def _execute_blocking(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        text = str(kwargs.get("text", ""))
        if not text:
            raise ValueError("Informe o texto a digitar.")
        window = str(kwargs.get("app", "") or "").strip()

        foreground = _get_foreground_window_title()
        focused = False
        activated = False

        if window:
            target_names = [window]
            try:
                info = self.launcher.resolve(window)
                names = candidate_process_names(info.get("app", ""), info.get("path"))
                target_names = names
            except ValueError:
                pass

            activated = False
            for candidate in target_names:
                if activate_window(candidate):
                    activated = True
                    break

            if not activated:
                foreground = _get_foreground_window_title()
                if foreground and any(
                    t.lower() in foreground.lower() or foreground.lower() in t.lower()
                    for t in target_names
                ):
                    focused = True
                else:
                    raise RuntimeError(
                        f"Não consegui focar a janela do '{window}'. "
                        "Verifique se o aplicativo está aberto e tente novamente."
                    )
            focused = True
            activated = True
        else:
            focused = foreground is not None
            activated = False

        typed = type_text(text)
        return {
            "typed_chars": typed,
            "window": window or "active",
            "focused": focused,
            "activated": activated,
            "foreground": foreground,
        }

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
            sent = await asyncio.to_thread(press_sequence, key)
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