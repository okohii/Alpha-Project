"""Janela nativa do Avatar ALPHA com o Astral Core 3D."""

from __future__ import annotations

import argparse

from app.core.config import get_settings
from app.desktop.native import run_native, start_backend

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18081
DEFAULT_WIDTH = 240
DEFAULT_HEIGHT = 240


def open_avatar(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, width: int = DEFAULT_WIDTH, height: int = DEFAULT_HEIGHT, transparent: bool = True) -> int:
    _ = transparent
    return run_native(mode="avatar", host=host, port=port, width=width, height=height)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="alpha", description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=get_settings().overlay_port + 1)
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument("--no-transparent", dest="transparent", action="store_false", default=True)
    args = parser.parse_args(argv)
    return open_avatar(args.host, args.port, args.width, args.height, args.transparent)


__all__ = ["main", "open_avatar", "start_backend"]
