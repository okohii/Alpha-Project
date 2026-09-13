"""Overlay controller: lifecycle + thread-safe UI queue.

A fila ``UICommand`` garante que toda operação na janela webview
ocorra via pump thread → adapter → pywebview (que internamente usa
``Invoke`` para rotear para a UI thread). A thread principal (onde
``webview.start()`` bloqueia) só é afetada internamente pelo pywebview.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

logger = logging.getLogger(__name__)

_OVERLAY = "[OVERLAY]"


class Lifecycle(str, Enum):
    STARTING = "starting"
    WEBVIEW_CREATED = "webview_created"
    WEBVIEW_READY = "webview_ready"
    RUNNING = "running"
    CLOSING = "closing"
    CLOSED = "closed"


_TRANSITIONS: dict[Lifecycle, Lifecycle] = {
    Lifecycle.STARTING: Lifecycle.WEBVIEW_CREATED,
    Lifecycle.WEBVIEW_CREATED: Lifecycle.WEBVIEW_READY,
    Lifecycle.WEBVIEW_READY: Lifecycle.RUNNING,
    Lifecycle.RUNNING: Lifecycle.CLOSING,
    Lifecycle.CLOSING: Lifecycle.CLOSED,
}

_SENTINEL: Any = object()


@dataclass(frozen=True)
class Command:
    kind: str
    payload: dict[str, Any] | None = None


class WebViewAdapter(Protocol):
    def minimize(self) -> None: ...
    def close(self) -> None: ...
    def evaluate_js(self, script: str) -> None: ...


class OverlayController:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._lifecycle = Lifecycle.STARTING
        self._events: dict[Lifecycle, threading.Event] = {
            s: threading.Event() for s in Lifecycle
        }
        self._adapter: WebViewAdapter | None = None
        self._queue: queue.Queue[Command] = queue.Queue()
        self._pump: threading.Thread | None = None
        self._stop = threading.Event()
        self._started_at = time.monotonic()
        self._dropped: int = 0
        self._log(Lifecycle.STARTING)

    @property
    def lifecycle(self) -> Lifecycle:
        with self._lock:
            return self._lifecycle

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "lifecycle": self._lifecycle.value,
                "uptime_s": round(time.monotonic() - self._started_at, 1),
                "queued": self._queue.qsize(),
                "dropped": self._dropped,
            }

    # -- lifecycle --

    def attach_webview(self, adapter: WebViewAdapter) -> None:
        with self._lock:
            if self._adapter is not None:
                raise RuntimeError(f"{_OVERLAY} webview já anexado")
            self._adapter = adapter
            self._go(Lifecycle.WEBVIEW_CREATED)

    def on_ui_ready(self) -> None:
        """Chamado pela janela quando a bridge pywebview fica pronta."""
        with self._lock:
            if self._lifecycle in (
                Lifecycle.WEBVIEW_READY,
                Lifecycle.RUNNING,
                Lifecycle.CLOSING,
                Lifecycle.CLOSED,
            ):
                return  # bridge já ativa (ex.: recarga) ou janela encerrada
            self._go(Lifecycle.WEBVIEW_READY)
        self._ensure_pump()
        with self._lock:
            self._go(Lifecycle.RUNNING)
        self.push("overlay_ready", {"lifecycle": "running"})

    def begin_close(self) -> None:
        with self._lock:
            if self._lifecycle in (Lifecycle.CLOSING, Lifecycle.CLOSED):
                return
            self._jump(Lifecycle.CLOSING)

    def mark_closed(self) -> None:
        with self._lock:
            if self._lifecycle is Lifecycle.CLOSED:
                return
            if self._lifecycle is not Lifecycle.CLOSING:
                self._jump(Lifecycle.CLOSING)
            self._jump(Lifecycle.CLOSED)
        self._stop.set()
        self._queue.put_nowait(_SENTINEL)

    def force_close(self) -> None:
        if self.lifecycle in (Lifecycle.CLOSING, Lifecycle.CLOSED):
            return
        self.begin_close()
        self.mark_closed()

    # -- commands --

    def request_minimize(self) -> None:
        self._enqueue(Command(kind="minimize"))

    def request_close(self) -> None:
        self._enqueue(Command(kind="close"))

    def push(self, kind: str, payload: dict[str, Any]) -> None:
        if self.lifecycle in (Lifecycle.CLOSING, Lifecycle.CLOSED):
            self._dropped += 1
            logger.debug("%s push %s descartado (lifecycle=%s)", _OVERLAY, kind, self._lifecycle)
            return
        json.dumps(payload)
        self._enqueue(
            Command(kind="push", payload={"name": kind, "data": payload})
        )

    # -- pump --

    def _ensure_pump(self) -> None:
        with self._lock:
            if self._pump is not None:
                return
            self._pump = threading.Thread(
                target=self._run_pump,
                name="overlay-ui-pump",
                daemon=True,
            )
            self._pump.start()
        logger.debug("%s pump started", _OVERLAY)

    def _run_pump(self) -> None:
        while not self._stop.is_set():
            try:
                cmd = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if cmd is _SENTINEL:
                break
            self._dispatch(cmd)

    def _dispatch(self, cmd: Command) -> None:
        with self._lock:
            adapter = self._adapter
            state = self._lifecycle
        if adapter is None or state in (Lifecycle.CLOSING, Lifecycle.CLOSED):
            logger.debug("%s descartando %s (lifecycle=%s)", _OVERLAY, cmd.kind, state)
            return
        try:
            if cmd.kind == "minimize":
                adapter.minimize()
            elif cmd.kind == "close":
                adapter.close()
            elif cmd.kind == "push":
                detail = json.dumps(cmd.payload, ensure_ascii=False)
                adapter.evaluate_js(
                    f"window.dispatchEvent(new CustomEvent('alpha:overlay',{detail}))"
                )
            else:
                logger.error("%s comando desconhecido %s", _OVERLAY, cmd.kind)
        except Exception as exc:  # noqa: BLE001 - não propagar para pump
            logger.error("%s falha ao executar %s: %s", _OVERLAY, cmd.kind, exc)

    # -- internals --

    def _go(self, target: Lifecycle) -> None:
        current = self._lifecycle
        expected = _TRANSITIONS.get(current)
        if target != expected:
            raise RuntimeError(f"{_OVERLAY} transição inválida {current} → {target}")
        self._jump(target)

    def _jump(self, target: Lifecycle) -> None:
        self._lifecycle = target
        self._events[target].set()
        self._log(target)

    def _log(self, state: Lifecycle | str, *, level: int = logging.INFO) -> None:
        logger.log(level, "%s %s thread=%s", _OVERLAY, state, threading.current_thread().name)

    def _enqueue(self, cmd: Command) -> None:
        with self._lock:
            if self._lifecycle in (Lifecycle.CLOSING, Lifecycle.CLOSED):
                self._dropped += 1
                logger.debug("%s enqueue %s descartado", _OVERLAY, cmd.kind)
                return
        self._queue.put_nowait(cmd)

    def wait_until(self, state: Lifecycle, timeout: float = 10.0) -> bool:
        return self._events[state].wait(timeout)
