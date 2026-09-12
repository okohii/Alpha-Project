from __future__ import annotations

import pytest

from app.cli.renderer import TerminalRenderer


@pytest.mark.parametrize(
    "answer",
    ["s", "sim", "sim, permitir", "pode", "permitir", "yes", "autorizo", "pode salvar"],
)
def test_confirmation_accepts_natural_positive_answers(monkeypatch, answer):
    monkeypatch.setattr("app.cli.renderer.Prompt.ask", lambda *args, **kwargs: answer)
    renderer = TerminalRenderer()
    assert renderer.confirm("memory_save") is True


@pytest.mark.parametrize(
    "answer",
    ["n", "não", "nao", "não permitir", "nao pode", "cancela", "não, pode"],
)
def test_confirmation_rejects_negative_or_ambiguous_answers(monkeypatch, answer):
    monkeypatch.setattr("app.cli.renderer.Prompt.ask", lambda *args, **kwargs: answer)
    renderer = TerminalRenderer()
    assert renderer.confirm("memory_save") is False
