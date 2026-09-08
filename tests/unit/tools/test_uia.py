from __future__ import annotations

import asyncio

import pytest

import app.skills.computer.tools.uia as u
from app.skills.computer.tools.uia import (
    ClickTextTool,
    ElementNotFoundError,
    ReadUiTool,
    _prefer,
    click_text,
    find_element,
)


def run(coro):
    return asyncio.run(coro)


def test_available_false_when_off_windows(monkeypatch):
    import os

    monkeypatch.setattr(os, "name", "posix")
    u._PYAUTO_LOADED = False
    u._PYAUTO = None
    assert u.available() is False


def test_prefer_interactive_controls():
    button = {"control_type": "Button"}
    text = {"control_type": "Text"}
    assert _prefer(text, button) is True
    assert _prefer(button, text) is False
    assert _prefer(button, button) is False


def test_find_element_returns_search_record(monkeypatch):
    record = {"name": "Salvar", "control_type": "Button", "window": "App", "x": 10, "y": 20}
    monkeypatch.setattr(
        u,
        "_search",
        lambda text, window_hint=None, max_windows=20: (object(), record),
    )
    assert find_element("Salvar") == record


def test_click_text_uses_search_and_clicks(monkeypatch):
    record = {"name": "Enviar", "control_type": "Button", "window": "Discord", "x": 560, "y": 340}
    clicked = {}

    class FakeWrapper:
        def click_input(self):
            clicked["called"] = True

    monkeypatch.setattr(u, "_search", lambda text, window_hint=None: (FakeWrapper(), record))
    result = click_text("Enviar")
    assert clicked["called"] is True
    assert result["window"] == "Discord"
    assert result["x"] == 560


def test_click_text_raises_when_not_found(monkeypatch):
    monkeypatch.setattr(u, "_search", lambda text, window_hint=None: None)
    with pytest.raises(ElementNotFoundError):
        click_text("nada aqui")


def test_click_text_tool_success(monkeypatch):
    monkeypatch.setattr(u, "available", lambda: True)
    monkeypatch.setattr(
        u,
        "click_text",
        lambda text, window_hint=None: {"clicked": text, "window": "Discord", "x": 5, "y": 5},
    )
    tool = ClickTextTool()
    result = run(tool.execute(text="Enviar", hint="discord"))
    assert result.success
    assert result.data["clicked"] == "Enviar"


def test_click_text_tool_unavailable(monkeypatch):
    monkeypatch.setattr(u, "available", lambda: False)
    tool = ClickTextTool()
    result = run(tool.execute(text="Enviar"))
    assert not result.success
    assert "indisponível" in result.error


def test_read_ui_tool_success(monkeypatch):
    monkeypatch.setattr(u, "available", lambda: True)
    monkeypatch.setattr(
        u,
        "read_ui_text",
        lambda window_hint=None, limit=200: [
            {"control_type": "Button", "name": "Salvar", "window": "App", "x": 1, "y": 2}
        ],
    )
    tool = ReadUiTool()
    result = run(tool.execute(hint="app"))
    assert result.success
    assert result.data["count"] == 1
    assert result.data["elements"][0]["name"] == "Salvar"


def test_read_ui_tool_unavailable(monkeypatch):
    monkeypatch.setattr(u, "available", lambda: False)
    tool = ReadUiTool()
    result = run(tool.execute())
    assert not result.success