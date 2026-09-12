"""Janela nativa do Chat Overlay do ALPHA.

A UI não contém lógica de agente: conecta no WebSocket local do backend e
apenas apresenta estado, execução, confirmações e conversa. O mesmo
Astral Core 3D usado pelo avatar é renderizado aqui.
"""

from __future__ import annotations

import argparse

from app.core.config import get_settings
from app.desktop.native import run_native, start_backend

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18080


def open_overlay(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> int:
    return run_native(mode="chat", host=host, port=port, width=430, height=700)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="alpha chat", description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=get_settings().overlay_port)
    args = parser.parse_args(argv)
    return open_overlay(args.host, args.port)


__all__ = ["main", "open_overlay", "start_backend"]
