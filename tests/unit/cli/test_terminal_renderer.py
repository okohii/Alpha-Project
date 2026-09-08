from __future__ import annotations

from rich.console import Console

from app.cli.renderer import TerminalRenderer
from app.cli.themes import Verbosity


def _renderer(capsys=None, verbosity=Verbosity.normal) -> TerminalRenderer:
    return TerminalRenderer(console=Console(), verbosity=verbosity)


def test_renderer_prints_user(capsys):
    renderer = _renderer()
    renderer.print_user("olá")
    assert "olá" in capsys.readouterr().out


def test_renderer_finalize_alpha(capsys):
    renderer = _renderer()
    renderer.finalize_alpha("resposta")
    out = capsys.readouterr().out
    assert "ALPHA:" in out
    assert "resposta" in out
