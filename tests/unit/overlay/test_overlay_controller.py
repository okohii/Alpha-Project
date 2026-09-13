"""Testes do OverlayController: lifecycle + fila thread-safe de UI.

Não importa pywebview: usamos um adapter fake — o controller não deve
conhecer a janela nativa (apenas o protocolo WebViewAdapter).
"""

from __future__ import annotations

import json
import threading
import time

import pytest

from app.overlay.controller import Lifecycle, OverlayController


class FakeAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.scripts: list[str] = []

    def minimize(self) -> None:
        self.calls.append(("minimize", None))

    def close(self) -> None:
        self.calls.append(("close", None))

    def evaluate_js(self, script: str) -> None:
        self.calls.append(("evaluate_js", script))
        self.scripts.append(script)


def _wait_for_calls(adapter: FakeAdapter, n: int, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if len(adapter.calls) >= n:
            return True
        time.sleep(0.01)
    return False


def test_lifecycle_valid_path_creates_and_ready():
    ctrl = OverlayController()
    adapter = FakeAdapter()
    assert ctrl.lifecycle is Lifecycle.STARTING

    ctrl.attach_webview(adapter)
    assert ctrl.lifecycle is Lifecycle.WEBVIEW_CREATED

    ctrl.on_ui_ready()
    assert ctrl.lifecycle is Lifecycle.RUNNING
    assert ctrl.wait_until(Lifecycle.RUNNING)

    # push inicial de overlay_ready é o primeiro comando do pump
    assert _wait_for_calls(adapter, 1)
    script = adapter.scripts[0]
    assert "overlay_ready" in script


def test_lifecycle_closing_to_closed():
    ctrl = OverlayController()
    ctrl.attach_webview(FakeAdapter())
    ctrl.on_ui_ready()
    ctrl.begin_close()
    assert ctrl.lifecycle is Lifecycle.CLOSING
    ctrl.mark_closed()
    assert ctrl.lifecycle is Lifecycle.CLOSED


def test_on_ui_ready_is_idempotent_on_reload():
    ctrl = OverlayController()
    adapter = FakeAdapter()
    ctrl.attach_webview(adapter)
    ctrl.on_ui_ready()
    ctrl.on_ui_ready()  # recarga dispara loaded de novo; não pode quebrar
    assert ctrl.lifecycle is Lifecycle.RUNNING
    assert _wait_for_calls(adapter, 1)  # só um overlay_ready


def test_invalid_transition_raises():
    ctrl = OverlayController()
    with pytest.raises(RuntimeError):
        ctrl._go(Lifecycle.RUNNING)  # noqa: SLF001 - guarda interna


def test_attach_twice_raises():
    ctrl = OverlayController()
    ctrl.attach_webview(FakeAdapter())
    with pytest.raises(RuntimeError):
        ctrl.attach_webview(FakeAdapter())


def test_commands_before_ready_are_dispatched_after_ready():
    ctrl = OverlayController()
    adapter = FakeAdapter()
    ctrl.request_minimize()  # enfileirado antes de qualquer janela
    assert ctrl.status()["queued"] == 1

    ctrl.attach_webview(adapter)
    ctrl.on_ui_ready()

    assert _wait_for_calls(adapter, 2)
    kinds = [c[0] for c in adapter.calls]
    assert "minimize" in kinds
    assert "evaluate_js" in kinds  # overlay_ready


def test_request_close_executes_on_adapter():
    ctrl = OverlayController()
    adapter = FakeAdapter()
    ctrl.attach_webview(adapter)
    ctrl.on_ui_ready()
    ctrl.request_close()
    assert _wait_for_calls(adapter, 2)
    assert ("close", None) in adapter.calls


def test_commands_after_closed_are_dropped():
    ctrl = OverlayController()
    adapter = FakeAdapter()
    ctrl.attach_webview(adapter)
    ctrl.on_ui_ready()
    ctrl.mark_closed()

    calls_before = len(adapter.calls)
    ctrl.request_minimize()
    ctrl.push("late", {"k": 1})
    time.sleep(0.1)

    assert len(adapter.calls) == calls_before
    status = ctrl.status()
    assert status["dropped"] == 2
    assert status["lifecycle"] == "closed"


def test_push_validates_json_serializable_payload():
    ctrl = OverlayController()
    ctrl.attach_webview(FakeAdapter())
    ctrl.on_ui_ready()
    with pytest.raises(TypeError):
        ctrl.push("bad", {"obj": object()})


def test_push_payload_is_forwarded_in_script():
    ctrl = OverlayController()
    adapter = FakeAdapter()
    ctrl.attach_webview(adapter)
    ctrl.on_ui_ready()

    trgt = _wait_for_calls(adapter, 1)
    assert trgt
    ctrl.push("status_changed", {"state": "thinking", "n": 3})

    assert _wait_for_calls(adapter, 2)
    script = adapter.scripts[-1]
    assert "status_changed" in script
    assert '"state": "thinking"' in script
    # nunca referencia a janela nativa
    assert "native" not in script
    assert "AccessibilityObject" not in script
    # payload válido JSON embutido
    payload = json.loads(script[script.index("{") : script.rindex("}") + 1])
    assert payload["name"] == "status_changed"


def test_concurrent_enqueue_is_thread_safe():
    ctrl = OverlayController()
    adapter = FakeAdapter()
    ctrl.attach_webview(adapter)
    ctrl.on_ui_ready()
    _wait_for_calls(adapter, 1)

    n_workers = 20
    n_calls = 50
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            for _ in range(n_calls):
                ctrl.request_minimize()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(n_workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert not errors
    target = 1 + n_workers * n_calls  # 1 = overlay_ready
    assert _wait_for_calls(adapter, target, timeout=5)
    assert len(adapter.calls) == target
    status = ctrl.status()
    assert status["queued"] == 0
    assert status["dropped"] == 0


def test_status_is_json_safe():
    ctrl = OverlayController()
    ctrl.attach_webview(FakeAdapter())
    status = ctrl.status()
    json.dumps(status)  # só tipos JSON-safe
    assert set(status) == {"lifecycle", "uptime_s", "queued", "dropped"}


def test_force_close_idempotent():
    ctrl = OverlayController()
    ctrl.attach_webview(FakeAdapter())
    ctrl.force_close()
    ctrl.force_close()
    assert ctrl.lifecycle is Lifecycle.CLOSED