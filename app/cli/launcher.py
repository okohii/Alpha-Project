from __future__ import annotations

import argparse
import asyncio
import signal
from typing import Sequence


MODES = ("chat", "macros")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="alpha",
        description="ALPHA — agente local-first com duas interfaces: avatar e chat overlay.",
    )
    sub = parser.add_subparsers(dest="mode", metavar="MODO")
    sub.add_parser("chat", help="abre o Chat Overlay do ALPHA")
    sub.add_parser("macros", help="abre a tela de macros e agendamentos")
    return parser


def _run_avatar() -> int:
    from app.avatar.desktop import main as avatar_main

    return avatar_main([])


def _run_chat() -> int:
    from app.overlay.desktop import main as overlay_main

    return overlay_main([])


def _run_macros() -> int:
    from app.db.session import initialize_database
    from app.macros.gui import open_gui

    asyncio.run(initialize_database())
    open_gui()
    return 0


def _quit_qt() -> bool:
    """Encerra a UI Qt sem lançar KeyboardInterrupt dentro de callbacks Qt."""
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return False

        # Fechar a janela primeiro garante que NativeAlphaWindow.closeEvent()
        # pare o WebSocket e solicite o encerramento do backend local.
        for window in list(app.topLevelWidgets()):
            try:
                window.close()
            except Exception:
                pass
        app.quit()
        return True
    except Exception:
        return False


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)

    def _stop(signum: int, frame: object) -> None:
        # SIGINT durante QTimer callbacks não deve virar KeyboardInterrupt dentro
        # do Qt (isso gerava traceback apontando para _drain_events()).
        if args.mode in {"chat", None} and _quit_qt():
            return
        raise KeyboardInterrupt

    try:
        signal.signal(signal.SIGINT, _stop)
    except (ValueError, OSError):
        pass

    try:
        if args.mode == "chat":
            return _run_chat()
        if args.mode == "macros":
            return _run_macros()
        return _run_avatar()
    except KeyboardInterrupt:
        print()
        return 130


__all__ = ["main"]
