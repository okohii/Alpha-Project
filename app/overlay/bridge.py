"""Bridge fina JS<->Python para o overlay.

Requisito arquitetural: o objeto passado como ``js_api`` NÃO pode expor
atributos não-callable, porque o pywebview (util.py::get_functions)
percorre ``dir()`` recursivamente e desce por qualquer objeto com
``__module__``. Guardar ``self.window``/``self.native`` na API causa a
recursão ``window.native.AccessibilityObject...`` e o acesso a
propriedades do WebView2 fora da UI thread. Por isso esta classe expõe
APENAS métodos, e nunca retém referência à janela.

Toda operação de UI é delegada ao controller (fila thread-safe), nunca
toca pywebview diretamente.
"""

from __future__ import annotations

from typing import Any

from app.overlay.controller import OverlayController


class OverlayApi:
    """API exposta ao JS. Devolve apenas tipos JSON-safe."""

    def __init__(self, controller: OverlayController) -> None:
        self._controller = controller

    def get_status(self) -> dict[str, Any]:
        return self._controller.status()

    def minimize(self) -> None:
        self._controller.request_minimize()

    def close(self) -> None:
        self._controller.request_close()