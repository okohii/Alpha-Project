"""Lançador do Avatar Overlay do ALPHA.

No Windows, o pywebview não oferece transparência nativa de janela. O avatar
usa por isso uma janela frameless + Win32 color-key: a cor de fundo técnica é
removida pela própria janela, deixando apenas o WebGL do Astral Core visível.
Em plataformas que suportam transparência nativa, o parâmetro ``transparent``
é usado normalmente.

Uso:
    alpha avatar [--host 127.0.0.1] [--port 18081]
"""

from __future__ import annotations

import argparse
import ctypes
import logging
import os
import threading
from typing import Any

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18081
DEFAULT_WIDTH = 220
DEFAULT_HEIGHT = 300

# Cor técnica removida pela janela Windows. Deve ser exatamente a mesma
# usada no canvas/HTML quando não há conteúdo desenhado.
WINDOW_KEY_COLOR = (5, 6, 12)

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
    """Transparência por composição depende do DWM estar ativo."""
    if os.name != "nt":
        return True
    try:
        enabled = ctypes.c_int()
        hr = ctypes.windll.dwmapi.DwmIsCompositionEnabled(ctypes.byref(enabled))
        return hr == 0 and enabled.value != 0
    except Exception:  # noqa: BLE001
        return True


def _apply_windows_color_key(window: Any) -> bool:
    """Remove a cor de fundo da janela usando Win32 layered + color key.

    ``pywebview.transparent`` é documentado como não suportado no Windows.
    Portanto não dependemos dele para o avatar: o form inteiro recebe
    ``WS_EX_LAYERED`` e ``LWA_COLORKEY``. O canvas usa ``WINDOW_KEY_COLOR``
    como clear color e essa cor passa a representar alpha=0 no desktop.
    """
    if os.name != "nt":
        return False

    try:
        form = window.native
        if form is None:
            return False

        hwnd = form.Handle.ToInt32()
        user32 = ctypes.windll.user32
        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000
        LWA_COLORKEY = 0x00000001
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_FRAMECHANGED = 0x0020
        HWND_TOP = 0

        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED)
        user32.SetWindowPos(
            hwnd,
            HWND_TOP,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_FRAMECHANGED,
        )

        r, g, b = WINDOW_KEY_COLOR
        colorref = r | (g << 8) | (b << 16)
        if not user32.SetLayeredWindowAttributes(hwnd, colorref, 0, LWA_COLORKEY):
            return False

        # O form precisa nascer com a mesma cor que será removida pelo key.
        try:
            import clr
            clr.AddReference("System.Drawing")
            from System.Drawing import Color
            form.BackColor = Color.FromArgb(r, g, b)
        except Exception:  # noqa: BLE001
            pass

        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("[AVATAR] color-key Windows indisponível: %s", exc)
        return False


def _prepare_native_window(window: Any) -> None:
    """Aplica o modo de transparência antes de exibir a janela."""
    if os.name == "nt":
        if not _apply_windows_color_key(window):
            logger.warning("[AVATAR] fallback para janela opaca no Windows")
        return

    # macOS/Linux: pywebview pode suportar transparência nativa conforme o
    # backend escolhido. Não fazemos hacks Win32 fora do Windows.
    try:
        form = window.native
        if form is not None:
            import clr
            clr.AddReference("System.Drawing")
            from System.Drawing import Color
            form.BackColor = Color.Transparent
    except Exception:  # noqa: BLE001
        pass


def open_avatar(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    transparent: bool = True,
) -> int:
    """Sobe o servidor e abre a janela do avatar. Bloqueia até fechar."""
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

    if transparent and os.name == "nt" and not _dwm_composition_enabled():
        logger.warning("[AVATAR] composição DWM desativada; usando janela opaca")
        transparent = False

    api = AvatarApi()
    kwargs: dict[str, Any] = {
        "title": "ALPHA",
        "url": url,
        "width": width,
        "height": height,
        "frameless": True,
        "shadow": False,
        "on_top": True,
        "js_api": api,
        "hidden": True,
        "background_color": "#05060c",
    }

    # No Windows, não passamos transparent=True porque o próprio pywebview
    # documenta essa opção como unsupported. Usamos color-key após criar a
    # janela. Em outros sistemas, a transparência nativa pode ser usada.
    if transparent and os.name != "nt":
        kwargs["transparent"] = True

    try:
        window = webview.create_window(**kwargs)
    except TypeError:
        logger.warning("[AVATAR] transparência nativa indisponível; abrindo opaco")
        kwargs.pop("transparent", None)
        window = webview.create_window(**kwargs)

    api.bind_close(window.destroy)

    def _on_loaded() -> None:
        if transparent:
            _prepare_native_window(window)
        try:
            window.show()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[AVATAR] não foi possível exibir a janela: %s", exc)

    window.events.loaded += _on_loaded
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
