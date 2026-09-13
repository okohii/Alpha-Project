from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Win32 imports
try:
    import ctypes
    import ctypes.wintypes

    _user32 = ctypes.windll.user32

    def _get_cursor_pos() -> tuple[int, int]:
        pt = ctypes.wintypes.POINT()
        _user32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y

    def _window_from_point(x: int, y: int) -> int:
        return _user32.WindowFromPoint(ctypes.wintypes.POINT(x, y))

    def _get_window_text(hwnd: int) -> str:
        length = _user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        _user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value

    def _get_foreground_window() -> int:
        return _user32.GetForegroundWindow()

    def _get_foreground_window_title() -> str | None:
        hwnd = _get_foreground_window()
        if not hwnd:
            return None
        title = _get_window_text(hwnd)
        return title if title else None

    _HAS_WIN32 = True
except Exception:
    _HAS_WIN32 = False

    def _get_cursor_pos() -> tuple[int, int]:
        return 0, 0

    def _window_from_point(x: int, y: int) -> int:
        return 0

    def _get_window_text(hwnd: int) -> str:
        return ""

    def _get_foreground_window() -> int:
        return 0

    def _get_foreground_window_title() -> str | None:
        return None


@dataclass
class RecordedStep:
    """Um passo gravado durante a sessão de gravação."""

    step_type: str
    params: dict[str, Any]
    description: str
    timestamp: float = field(default_factory=time.time)
    wait_after: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_type": self.step_type,
            "params": self.params,
            "description": self.description,
            "wait_after": self.wait_after,
        }


class InputRecorder:
    """
    Grava ações do usuário via hooks globais de teclado e mouse.

    Uso:
        recorder = InputRecorder()
        recorder.start()
        # ... usuário interage ...
        steps = recorder.stop()
    """

    def __init__(self):
        self._steps: deque[RecordedStep] = deque()
        self._recording = False
        self._last_mouse_click_time: float = 0.0
        self._text_buffer: list[str] = []
        self._text_flush_timer: threading.Timer | None = None
        self._on_step_callback: Any = None
        self._last_step_time: float = 0.0

        # Hooks
        self._keyboard_hook_id: Any = None
        self._mouse_hook_id: Any = None

    def set_on_step(self, callback: Any) -> None:
        """Callback chamado a cada passo gravado."""
        self._on_step_callback = callback

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def steps(self) -> list[RecordedStep]:
        return list(self._steps)

    def start(self) -> None:
        """Inicia a gravação."""
        if self._recording:
            return
        self._steps.clear()
        self._text_buffer.clear()
        self._recording = True
        self._last_step_time = time.time()
        self._install_hooks()
        logger.info("Gravação de entrada iniciada")

    def stop(self) -> list[RecordedStep]:
        """Para a gravação e retorna os passos."""
        if not self._recording:
            return []
        self._recording = False
        self._flush_text_buffer()
        self._remove_hooks()
        logger.info("Gravação parada: %d passos", len(self._steps))
        return list(self._steps)

    def cancel(self) -> None:
        """Cancela a gravação sem salvar."""
        self._recording = False
        self._flush_text_buffer()
        self._remove_hooks()
        self._steps.clear()

    # ── Hooks ──────────────────────────────────────────────────────────

    def _install_hooks(self) -> None:
        try:
            import keyboard

            self._keyboard_hook_id = keyboard.hook(
                self._on_keyboard_event, suppress=False
            )
            logger.info("Hook de teclado instalado")
        except Exception as exc:
            logger.warning("Falha ao instalar hook de teclado: %s", exc)

        try:
            import mouse

            self._mouse_hook_id = mouse.hook(self._on_mouse_event)
            logger.info("Hook de mouse instalado")
        except Exception as exc:
            logger.warning("Falha ao instalar hook de mouse: %s", exc)

    def _remove_hooks(self) -> None:
        try:
            if self._keyboard_hook_id is not None:
                import keyboard

                keyboard.unhook(self._keyboard_hook_id)
                self._keyboard_hook_id = None
        except Exception:
            pass
        try:
            if self._mouse_hook_id is not None:
                import mouse

                mouse.unhook(self._mouse_hook_id)
                self._mouse_hook_id = None
        except Exception:
            pass

    # ── Teclado ────────────────────────────────────────────────────────

    def _on_keyboard_event(self, event: Any) -> None:
        if not self._recording:
            return
        if event.event_type != "down":
            return

        key = event.name

        # Ignora modificadores puros
        modifier_keys = {
            "ctrl", "ctrl l", "ctrl r", "alt", "alt l", "alt r",
            "shift", "shift l", "shift r", "win", "win l", "win r",
        }
        if key.lower() in modifier_keys:
            return

        # Combinações (Ctrl+C, Ctrl+V, Alt+Tab, etc.)
        try:
            import keyboard as kb

            active_mods = []
            if kb.is_pressed("ctrl"):
                active_mods.append("ctrl")
            if kb.is_pressed("alt"):
                active_mods.append("alt")
            if kb.is_pressed("shift"):
                active_mods.append("shift")

            if active_mods:
                combo = "+".join(active_mods + key.split("+"))
                self._flush_text_buffer()

                # Se é Ctrl+V, salva o clipboard atual
                params: dict[str, Any] = {"key": combo}
                if combo.lower() == "ctrl+v":
                    try:
                        import pyperclip
                        params["clipboard"] = pyperclip.paste()
                    except Exception:
                        pass

                self._add_step("press_key", params, f"Atalho: {combo}")
                return
        except Exception:
            pass

        # Teclas especiais
        special_keys = {
            "enter", "tab", "escape", "backspace", "delete",
            "space", "up", "down", "left", "right",
            "home", "end", "page up", "page down",
        }
        if key.lower() in special_keys:
            self._flush_text_buffer()
            key_map = {
                "enter": "enter", "tab": "tab", "escape": "esc",
                "backspace": "backspace", "delete": "delete",
                "space": " ", "up": "up", "down": "down",
                "left": "left", "right": "right",
                "home": "home", "end": "end",
                "page up": "pageup", "page down": "pagedown",
            }
            mapped = key_map.get(key.lower(), key)
            self._add_step("press_key", {"key": mapped}, f"Tecla: {key}")
            return

        # Caractere normal → buffer
        if len(key) == 1:
            self._text_buffer.append(key)
            if self._text_flush_timer:
                self._text_flush_timer.cancel()
            self._text_flush_timer = threading.Timer(
                0.5, self._flush_text_buffer
            )
            self._text_flush_timer.start()

    def _flush_text_buffer(self) -> None:
        if self._text_flush_timer:
            self._text_flush_timer.cancel()
            self._text_flush_timer = None
        if not self._text_buffer:
            return
        text = "".join(self._text_buffer)
        self._text_buffer.clear()

        # Captura a janela ativa para o executor saber onde digitar
        window = _get_foreground_window_title() if _HAS_WIN32 else None
        params: dict[str, Any] = {"text": text}
        if window:
            params["app"] = window

        preview = text[:40] + ("..." if len(text) > 40 else "")
        window_info = f" em '{window}'" if window else ""
        self._add_step("type", params, f"Digitar: '{preview}'{window_info}")

    # ── Mouse ──────────────────────────────────────────────────────────

    def _on_mouse_event(self, event: Any) -> None:
        if not self._recording:
            return
        # Só processa cliques (ButtonEvent), ignora MoveEvent e WheelEvent
        try:
            import mouse

            if not isinstance(event, mouse.ButtonEvent):
                return
            if event.event_type != "down":
                return
        except Exception:
            return

        now = time.time()
        if now - self._last_mouse_click_time < 0.2:
            return
        self._last_mouse_click_time = now

        # Flush texto antes do clique
        self._flush_text_buffer()

        x, y = _get_cursor_pos()

        # Win32: obtém janela sob o cursor para contexto
        hwnd = _window_from_point(x, y) if _HAS_WIN32 else 0
        window_title = _get_window_text(hwnd) if hwnd else ""

        # Grava só com coordenadas - simples e robusto
        params: dict[str, Any] = {"x": x, "y": y}
        if window_title:
            params["window_hint"] = window_title

        desc = f"Clicar em ({x}, {y})"
        if window_title:
            desc = f"Clicar em '{window_title}' ({x}, {y})"

        self._add_step("click", params, desc)

    # ── Helpers ────────────────────────────────────────────────────────

    def _add_step(
        self, step_type: str, params: dict[str, Any], description: str
    ) -> None:
        now = time.time()

        # Insere wait entre passos se houve delay significativo
        if self._last_step_time > 0:
            delay = now - self._last_step_time
            if delay > 0.3:
                # Arredonda para 1 casa decimal
                seconds = round(delay, 1)
                wait_step = RecordedStep(
                    step_type="wait",
                    params={"seconds": seconds},
                    description=f"Aguardar {seconds}s",
                    timestamp=now,
                )
                self._steps.append(wait_step)
                if self._on_step_callback:
                    try:
                        self._on_step_callback(wait_step)
                    except Exception:
                        pass

        step = RecordedStep(
            step_type=step_type, params=params, description=description
        )
        self._steps.append(step)
        self._last_step_time = now
        logger.debug("Gravado: %s", description)
        if self._on_step_callback:
            try:
                self._on_step_callback(step)
            except Exception:
                pass


input_recorder = InputRecorder()
