"""Lançador do Avatar Overlay do ALPHA.

Abre uma janela pywebview transparente e sem moldura (um "PNG flutuante")
apontando para o backend FastAPI. O backend roda a sessão de voz contínua
(``app/avatar/server.py``) e o avatar reflete os estados pelo EventBus.

Toda a janela é apenas apresentação: nada de lógica/segurança aqui. A UI é
um elemento flutuante sobre o desktop; o conteúdo fica restrito ao orbe do
avatar e legendas mínimas.

Uso:
    alpha avatar [--host 127.0.0.1] [--port 18081]
"""

from __future__ import annotations

import argparse
import ctypes
import logging
import threading
from typing import Any

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18081
DEFAULT_WIDTH = 220
DEFAULT_HEIGHT = 300

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
    thread = threading.Thread(target=server.run, name="alpha-avatar-server", daemon=True)
    thread.start()
    return server, thread


class AvatarApi:
    """API exposta ao JS. Devolve apenas tipos JSON-safe."""

    def __init__(self) -> None:
        self._closers: list[Any] = []

    def bind_close(self, closer: Any) -> None:
        self._closers.append(closer)

    def close(self) -> None:
        for closer in self._closers[:]:
            try:
                closer()
            except Exception:  # noqa: BLE001 - fechamento nunca deve quebrar
                pass


def _dwm_composition_enabled() -> bool:
    """Transparência per-pixel depende de composição do DWM estar ativa."""
    try:
        import ctypes

        enabled = ctypes.c_int()
        hr = ctypes.windll.dwmapi.DwmIsCompositionEnabled(ctypes.byref(enabled))
        return hr == 0 and enabled.value != 0
    except Exception:  # noqa: BLE001
        return True


def _enable_layered(window: Any) -> None:
    """Aplica ``WS_EX_LAYERED`` no form WinForms e fundo transparente.

    O pywebview não aplica explicitamente esse estilo; sem ele, o WebView2
    não compõe per-pixel e a área transparente do HTML aparece como o
    ``BackColor`` do form (branco/padrão). Forçar ``WS_EX_LAYERED`` + 
    ``BackColor = Transparent`` é o requisito para transparência real com
    WebView2 em WinForms.
    """

    def _apply() -> None:
        try:
            form = window.native
            if form is None:
                return
            hwnd = form.Handle.ToInt32()
            user32 = ctypes.windll.user32
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            if not (style & WS_EX_LAYERED):
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED)
                user32.SetWindowPos(
                    hwnd, 0, 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0020
                )  # SWP_NOMOVE | SWP_NOSIZE | SWP_FRAMECHANGED
        except Exception:  # noqa: BLE001 - nunca quebrar a janela
            pass

        # BackColor transparente: o cinza/branco que vaza atrás do WebView2
        # some — o desktop aparece através das áreas alpha=0.
        try:
            form = window.native
            if form is not None:
                import clr

                clr.AddReference("System.Drawing")
                from System import Action
                from System.Drawing import Color

                def _transparent() -> None:
                    form.BackColor = Color.Transparent

                try:
                    form.Invoke(Action(_transparent))
                except Exception:  # noqa: BLE001
                    form.BackColor = Color.Transparent
        except Exception:  # noqa: BLE001
            pass

    window.events.before_show += _apply
    window.events.loaded += _apply


def open_avatar(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    transparent: bool = True,
) -> int:
    """Sobe o servidor e abre a janela transparente do avatar. Bloqueia até fechar."""
    try:
        import webview
    except ModuleNotFoundError:
        print(
            "pywebview não instalado. Instale com: "
            '.venv\\Scripts\\python -m pip install -e ".[desktop]"\n'
            f"ou abra http://{host}:{port}/avatar/ no navegador."
        )
        return 1

    logger.info("[AVATAR] starting host=%s port=%s transparent=%s", host, port, transparent)
    server, _thread = start_server(host, port)
    url = f"http://{host}:{port}/avatar/"

    if transparent and not _dwm_composition_enabled():
        logger.warning("[AVATAR] composição DWM desativada; usando janela opaca")
        transparent = False

    api = AvatarApi()
    kwargs: dict[str, Any] = {
        "title": "ALPHA",
        "url": url,
        "width": width,
        "height": height,
        "frameless": True,
        "on_top": True,
        "js_api": api,
        # Cor de pré-carregamento. Com transparência real o WebView2 usa
        # DefaultBackgroundColor=Transparent; sem ela, evita branco.
        "background_color": "#05060c",
    }
    if transparent:
        kwargs["transparent"] = True

    try:
        window = webview.create_window(**kwargs)
    except TypeError:
        logger.warning("[AVATAR] transparência indisponível; abrindo opaco")
        kwargs.pop("transparent", None)
        kwargs["background_color"] = "#05060c"
        window = webview.create_window(**kwargs)

    api.bind_close(window.destroy)
    if transparent:
        _enable_layered(window)
    window.events.closed += lambda: setattr(server, "should_exit", True)

    logger.info("[AVATAR] WebView created url=%s", url)
    try:
        webview.start(debug=False)
    except Exception as exc:  # noqa: BLE001 - fechar servidor mesmo com erro de GUI
        logger.error("[AVATAR] erro da GUI: %s", exc)
    finally:
        server.should_exit = True
        logger.info("[AVATAR] closed")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="alpha avatar", description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument(
        "--no-transparent",
        dest="transparent",
        action="store_false",
        default=True,
        help="abre janela opaca (fallback de compatibilidade)",
    )
    args = parser.parse_args(argv)
    return open_avatar(args.host, args.port, args.width, args.height, args.transparent)


__all__ = ["main", "start_server"]
