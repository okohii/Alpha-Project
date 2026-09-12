"""Lançador do Overlay Desktop do ALPHA.

Abre uma janela nativa (pywebview) apontando para o backend FastAPI,
que expõe a UI e o WebSocket de eventos. O overlay é apenas a
apresentação: toda a lógica/segurança continua no AgentCore.

Arquitetura: a janela pywebview NUNCA é exposta à bridge JS. A
``OverlayApi`` (bridge) só conhece o ``OverlayController``, que enfileira
comandos de UI (minimize/close/push) numa fila thread-safe tocada por um
pump dedicado — o acesso final ao WebView2 acontece sempre na UI thread,
via marshaling interno do pywebview.

Uso:
    alpha overlay [--port 18080] [--host 127.0.0.1]
"""

from __future__ import annotations

import argparse
import logging
import threading
from typing import Any

from app.core.config import get_settings
from app.overlay.bridge import OverlayApi
from app.overlay.controller import OverlayController

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18080

logger = logging.getLogger(__name__)


def start_server(host: str, port: int) -> tuple[Any, threading.Thread]:
    """Inicia o uvicorn em thread daemon e devolve (server, thread)."""
    import uvicorn

    config = uvicorn.Config(
        "app.main:app",
        host=host,
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(
        target=server.run, name="alpha-overlay-server", daemon=True
    )
    thread.start()
    return server, thread


class _PyWebViewWindow:
    """Adapter que isola a janela pywebview atrás da UI queue."""

    def __init__(self, window: Any) -> None:
        self._window = window

    def minimize(self) -> None:
        self._window.minimize()

    def close(self) -> None:
        self._window.destroy()

    def evaluate_js(self, script: str) -> None:
        self._window.evaluate_js(script)


def _webview2_runtime_version() -> str | None:
    """Versão do WebView2 Runtime instalado, para diagnóstico (0x80004002)."""
    try:
        import winreg

        subkeys = (
            r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients"
            r"\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
            r"SOFTWARE\Microsoft\EdgeUpdate\Clients"
            r"\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
        )
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for key_path in subkeys:
                try:
                    with winreg.OpenKey(hive, key_path) as key:
                        value, _ = winreg.QueryValueEx(key, "pv")
                    if value:
                        return str(value)
                except OSError:
                    continue
    except Exception:  # noqa: BLE001 - diagnóstico nunca bloqueia a inicialização
        pass
    return None


def open_overlay(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> int:
    """Sobe o servidor e abre a janela do overlay. Bloqueia até fechar."""
    try:
        import webview
    except ModuleNotFoundError:
        print(
            "pywebview não instalado. Instale com: "
            ".venv\\Scripts\\python -m pip install -e \".[desktop]\"\n"
            "ou use 'alpha overlay --browser' / "
            f"abrir http://{host}:{port}/overlay/"
        )
        return 1

    logger.info("[OVERLAY] starting host=%s port=%s", host, port)
    runtime = _webview2_runtime_version()
    logger.debug(
        "[OVERLAY] WebView2 Runtime %s", runtime if runtime else "não detectado (fallback MSHTML?)"
    )
    server, _thread = start_server(host, port)
    url = f"http://{host}:{port}/overlay/"

    controller = OverlayController()
    window = webview.create_window(
        "ALPHA",
        url,
        width=400,
        height=640,
        frameless=True,
        easy_drag=True,
        on_top=True,
        background_color="#0d0e1a",
        js_api=OverlayApi(controller),
    )
    controller.attach_webview(_PyWebViewWindow(window))
    logger.info("[OVERLAY] WebView created url=%s", url)

    window.events.loaded += lambda: controller.on_ui_ready()
    window.events.closed += lambda: controller.mark_closed()

    logger.info("[OVERLAY] UI thread ready (webview.start na thread principal)")
    try:
        webview.start(debug=False)
    except Exception as exc:  # noqa: BLE001 - fechar servidor mesmo com erro de GUI
        logger.error("[OVERLAY] erro da GUI: %s", exc)
    finally:
        controller.force_close()
        server.should_exit = True
        logger.info("[OVERLAY] closed")
    return 0


def open_browser(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> int:
    """Sobe o servidor e abre no navegador padrão (sem pywebview)."""
    import webbrowser

    server, _thread = start_server(host, port)
    url = f"http://{host}:{port}/overlay/"
    webbrowser.open(url, new=2)
    print(f"Overlay disponível em {url}  (Ctrl+C para sair)")
    try:
        while True:
            pass
    except KeyboardInterrupt:
        pass
    finally:
        server.should_exit = True
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="alpha overlay", description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=get_settings().overlay_port)
    parser.add_argument(
        "--browser",
        action="store_true",
        help="abre no navegador em vez de janela nativa",
    )
    args = parser.parse_args(argv)
    if args.browser:
        return open_browser(args.host, args.port)
    return open_overlay(args.host, args.port)


__all__ = ["main", "start_server"]