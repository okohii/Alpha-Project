"""Regressão da bridge do overlay: API fina, só tipos JSON-safe.

O pywebview (6.2.1) ``inject_pywebview``/``get_functions`` caminha por
``dir(js_api)`` recursivamente: qualquer atributo não-callable com
``__module__`` é expandido. Na versão anterior, ``api.window`` (a janela
pywebview) era expandido e varria ``window.native`` → WebView2 →
``AccessibilityObject``, causando recursão, erro de UI thread e
E_NOINTERFACE. Estes testes garantem que a ``OverlayApi`` nunca exponha
tais objetos e que a inspeção termina sem recursão.
"""

from __future__ import annotations

import inspect
import json

import pytest

from app.overlay.bridge import OverlayApi
from app.overlay.controller import OverlayController


def _pywebview_get_functions(obj: object, base: str = "") -> dict[str, list[str]]:
    """Espelho do algoritmo de pywebview.util._build_func_list / get_functions.

    Replica a travessia recursiva de ``dir()`` para detectar recursão e
    acesso a objetos como ``window``/``native``.
    """

    def get_args(func: object) -> list[str]:
        return list(inspect.getfullargspec(func).args)[1:]

    exposed: list[int] = []
    functions: dict[str, list[str]] = {}

    def walk(current: object, base_name: str) -> None:
        obj_id = id(current)
        if obj_id in exposed:
            return
        exposed.append(obj_id)

        for name in dir(current):
            try:
                full = f"{base_name}.{name}" if base_name else name
                if name.startswith("_"):
                    continue
                attr = getattr(current, name)
                if not getattr(attr, "_serializable", True):
                    continue
                if inspect.ismethod(attr) or inspect.isfunction(attr):
                    functions[full] = get_args(attr)
                elif inspect.isclass(attr) or (
                    isinstance(attr, object)
                    and not callable(attr)
                    and hasattr(attr, "__module__")
                ):
                    walk(attr, full)
            except Exception:  # noqa: BLE001 - pywebview silencia durante a inspeção
                continue

    walk(obj, base)
    return functions


def _build_api() -> tuple[OverlayApi, OverlayController]:
    ctrl = OverlayController()
    return OverlayApi(ctrl), ctrl


def test_introspection_finds_only_public_methods():
    api, _ = _build_api()
    funcs = _pywebview_get_functions(api, "api")
    assert set(funcs) == {"api.get_status", "api.minimize", "api.close"}
    assert all(params == [] for params in funcs.values())


def test_introspection_never_finds_window_or_native():
    api, _ = _build_api()
    funcs = _pywebview_get_functions(api, "api")
    merged = "|".join(funcs)
    for forbidden in ("native", "window", "AccessibilityObject", "CoreWebView2"):
        assert forbidden not in merged


def test_api_has_no_public_non_callable_attributes():
    api, _ = _build_api()
    for name in dir(api):
        if name.startswith("_"):
            continue
        attr = getattr(api, name)
        assert callable(attr), f"atributo público não-callable: {name}=>{type(attr)}"


def test_get_status_returns_json_safe_primitives():
    api, ctrl = _build_api()
    ctrl.attach_webview(_Fake())
    status = api.get_status()
    json.dumps(status)
    assert status["lifecycle"] == "webview_created"
    assert isinstance(status["uptime_s"], (int, float))
    assert isinstance(status["queued"], int)


def test_minimize_and_close_delegate_to_controller():
    api, ctrl = _build_api()
    ctrl.attach_webview(_Fake())
    ctrl.on_ui_ready()

    api.minimize()
    api.close()
    ctrl.mark_closed()
    # nenhum dos dois lança e ambos passam pela fila thread-safe
    assert ctrl.status()["dropped"] == 0


class _Fake:
    def minimize(self) -> None:
        pass

    def close(self) -> None:
        pass

    def evaluate_js(self, script: str) -> None:
        pass


def test_refuses_arbitrary_objects_in_status_path():
    """A bridge nunca retorna objetos; payloads complexos são barrados."""
    api, ctrl = _build_api()
    assert json.dumps(api.get_status())

    with pytest.raises(TypeError):
        ctrl.push("payload", {"obj": object()})