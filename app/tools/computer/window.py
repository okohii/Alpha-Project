"""Gerenciamento de janelas e monitores no Windows."""
from __future__ import annotations

import ctypes
import os
import subprocess
from pathlib import Path
from typing import Any

from app.tools.base import Tool, ToolPermission, ToolResult

_GWL_EXSTYLE = -20
_WS_EX_NOACTIVATE = 0x08000000
_SWP_NOZORDER = 0x0004
_SWP_SHOWWINDOW = 0x0040
_MONITORINFOF_PRIMARY = 1
_UINT_MAX = 0xFFFFFFFF


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("rcMonitor", _RECT),
        ("rcWork", _RECT),
        ("dwFlags", ctypes.c_ulong),
        ("szDevice", ctypes.c_wchar * 32),
    ]


def list_monitors() -> list[dict[str, Any]]:
    if os.name != "nt":
        return []
    monitors: list[dict[str, Any]] = []

    MONITORENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_bool,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(_RECT),
        ctypes.c_void_p,
    )

    def _callback(monitor, hdc, rect, data) -> bool:
        info = _MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(info)
        if not ctypes.windll.user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return True
        bounds = info.rcMonitor
        index = len(monitors) + 1
        monitors.append(
            {
                "monitor": index,
                "name": info.szDevice.rstrip("\x00"),
                "left": bounds.left,
                "top": bounds.top,
                "width": bounds.right - bounds.left,
                "height": bounds.bottom - bounds.top,
                "primary": bool(info.dwFlags & _MONITORINFOF_PRIMARY),
            }
        )
        return True

    ctypes.windll.user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(_callback), None)
    return monitors


def _windows_matching_stem(stem: str) -> set[int]:
    """Janelas visíveis cujo processo tenha o stem fornecido (ex.: 'notepad')."""
    stem = Path(stem).stem.lower()
    found: set[int] = set()

    def _callback(hwnd, _) -> bool:
        if not ctypes.windll.user32.IsWindowVisible(hwnd):
            return True
        pid = ctypes.c_ulong(0)
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        proc = _process_name_for_pid(pid.value)
        if proc and stem in Path(proc).stem:
            found.add(int(hwnd))
        return True

    ctypes.windll.user32.EnumWindows(
        ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(_callback),
        None,
    )
    return found


def _process_name_for_pid(pid: int) -> str | None:
    kernel32 = ctypes.windll.kernel32
    process = kernel32.OpenProcess(0x1000 | 0x0010, False, pid)  # QUERY_LIMITED_INFORMATION
    if not process:
        return None
    try:
        buffer = ctypes.create_unicode_buffer(1024)
        size = ctypes.c_ulong(1024)
        if kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
            return Path(buffer.value).name.lower()
        return None
    finally:
        kernel32.CloseHandle(process)


def find_window_title(title_part: str) -> int | None:
    if os.name != "nt":
        return None
    titles: list[int] = []

    def _callback(hwnd, _) -> bool:
        if not ctypes.windll.user32.IsWindowVisible(hwnd):
            return True
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buffer, length + 1)
        if title_part.lower() in buffer.value.lower():
            titles.append(int(hwnd))
        return True

    ctypes.windll.user32.EnumWindows(
        ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(_callback),
        None,
    )
    return titles[0] if titles else None


def bring_to_front(hwnd: int) -> None:
    if os.name == "nt":
        ctypes.windll.user32.SetForegroundWindow(hwnd)


def move_window(hwnd: int, monitor: dict[str, Any], maximize: bool = False) -> None:
    if os.name != "nt":
        raise RuntimeError("Mover janelas só é suportado no Windows.")
    x = int(monitor["left"])
    y = int(monitor["top"])
    width = int(monitor["width"])
    height = int(monitor["height"])
    user32 = ctypes.windll.user32
    ctypes.windll.user32.SetWindowPos(
        hwnd,
        None,
        x,
        y,
        width,
        height,
        _SWP_NOZORDER | _SWP_SHOWWINDOW,
    )
    if maximize:
        user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE


def find_app_window(
    app_name: str,
    resolved_path: str | None = None,
) -> tuple[int, str | None]:
    """Acha uma janela visível do app. Retorna (hwnd, processo_nome) ou (0, None)."""
    if os.name != "nt":
        raise RuntimeError("Controle de janelas só é suportado no Windows.")
    candidates = app_name.strip().lower()
    stem = Path(resolved_path).stem.lower() if resolved_path else ""
    windows: list[tuple[int, str | None]] = []

    def _callback(hwnd, _) -> bool:
        if not ctypes.windll.user32.IsWindowVisible(hwnd):
            return True
        pid = ctypes.c_ulong(0)
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        proc = _process_name_for_pid(pid.value)
        if proc:
            windows.append((int(hwnd), proc))
        return True

    ctypes.windll.user32.EnumWindows(
        ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(_callback),
        None,
    )

    def _matches(proc: str) -> bool:
        base = Path(proc).stem
        if stem:
            return stem in base or base in stem
        return candidates in proc or base in candidates or candidates in base

    for hwnd, proc in windows:
        if _matches(proc):
            return hwnd, proc
    return 0, None


def launch_on_monitor(
    executable: str,
    monitor_index: int,
    args: list[str] | None = None,
    max_wait: float = 12.0,
) -> dict[str, Any]:
    import time

    if os.name != "nt":
        raise RuntimeError("Abrir em monitor específico só é suportado no Windows.")
    target = Path(executable)
    if not target.exists():
        raise FileNotFoundError(target)
    monitors = list_monitors()
    target_monitor = next(
        (monitor for monitor in monitors if monitor["monitor"] == int(monitor_index)), None
    )
    if target_monitor is None:
        raise ValueError(f"Monitor {monitor_index} não encontrado (há {len(monitors)}).")
    before = _windows_matching_stem(target.stem)
    process = subprocess.Popen([str(target), *(args or [])])
    deadline = time.monotonic() + max_wait
    hwnd = 0
    while time.monotonic() < deadline:
        new_windows = _windows_matching_stem(target.stem) - before
        if new_windows:
            hwnd = min(new_windows)
            break
        if target.suffix.lower() == ".exe" and process.poll() is not None:
            break
        time.sleep(0.2)
    if not hwnd:
        # Apps de instância única podem apenas focar a janela já aberta:
        # se não surgiu janela nova mas já existe uma, move ela para o monitor.
        existing = _windows_matching_stem(target.stem)
        if existing:
            hwnd = min(existing)
        else:
            try:
                process.terminate()
            except OSError:
                pass
            return {
                "app": target.stem,
                "moved": False,
                "error": "Janela do aplicativo não apareceu a tempo.",
            }
    move_window(hwnd, target_monitor)
    bring_to_front(hwnd)
    return {
        "app": target.stem,
        "moved": True,
        "monitor": target_monitor["monitor"],
        "monitor_name": target_monitor["name"],
    }


def move_app(name: str, monitor_index: int, resolved_path: str | None = None) -> dict[str, Any]:
    if os.name != "nt":
        raise RuntimeError("Mover janelas só é suportado no Windows.")
    monitors = list_monitors()
    target_monitor = next(
        (monitor for monitor in monitors if monitor["monitor"] == int(monitor_index)), None
    )
    if target_monitor is None:
        raise ValueError(f"Monitor {monitor_index} não encontrado (há {len(monitors)}).")
    hwnd, proc = find_app_window(name, resolved_path=resolved_path)
    if not hwnd:
        raise FileNotFoundError(f"Nenhuma janela aberta do app '{name}'.")
    move_window(hwnd, target_monitor)
    bring_to_front(hwnd)
    return {
        "app": name,
        "process": proc,
        "moved": True,
        "monitor": target_monitor["monitor"],
        "monitor_name": target_monitor["name"],
    }


class ListMonitorsTool(Tool):
    name = "list_monitors"
    description = (
        "Lista os monitores conectados ao computador com posição, "
        "resolução e se é o principal."
    )
    permission = ToolPermission.read

    async def execute(self, **kwargs: Any) -> ToolResult:
        monitors = list_monitors()
        return ToolResult(
            name=self.name,
            success=True,
            data={"monitors": monitors, "total": len(monitors)},
        )

    def parameters_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}


class MoveAppTool(Tool):
    name = "move_app"
    description = (
        "Move a janela de um aplicativo já aberto para outro monitor. "
        "Ex.: 'move o discord pro segundo monitor' → move_app app='discord' monitor=2. "
        "Use list_monitors para ver os monitores."
    )
    permission = ToolPermission.write

    def __init__(self, launcher: Any | None = None) -> None:
        self.launcher = launcher

    async def execute(self, **kwargs: Any) -> ToolResult:
        app = str(kwargs.get("app", "") or "").strip()
        monitor = int(kwargs.get("monitor", 0) or 0)
        if not app:
            return ToolResult(name=self.name, success=False, data={}, error="Informe o aplicativo.")
        if monitor <= 0:
            return ToolResult(
                name=self.name,
                success=False,
                data={},
                error="Informe o monitor (1, 2, ...).",
            )
        resolved_path = None
        if self.launcher is not None:
            try:
                resolved_path = self.launcher.resolve(app)["path"]
            except (ValueError, FileNotFoundError):
                pass
        try:
            result = move_app(app, monitor, resolved_path=resolved_path)
        except (ValueError, FileNotFoundError, OSError, RuntimeError) as exc:
            return ToolResult(name=self.name, success=False, data={}, error=exc)
        return ToolResult(name=self.name, success=True, data=result)

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "app": {"type": "string", "description": "Nome do aplicativo (ex.: 'discord')"},
                "monitor": {
                    "type": "integer",
                    "description": "Número do monitor (1, 2, ...) via list_monitors",
                },
            },
            "required": ["app", "monitor"],
        }