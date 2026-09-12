from __future__ import annotations

import asyncio
import os

import app.skills.computer.tools.search as search


def run(coro):
    return asyncio.run(coro)


def test_windows_search_rejects_empty_query():
    result = run(search.WindowsSearchTool().execute(query=""))
    assert not result.success
    assert "pesquisado" in str(result.error)


def test_windows_search_rejects_non_windows(monkeypatch):
    monkeypatch.setattr(os, "name", "posix")
    result = run(search.WindowsSearchTool().execute(query="Calculadora"))
    assert not result.success
    assert "Windows" in str(result.error)


def test_windows_search_opens_first_result(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(search, "press_sequence", lambda key: calls.append(f"key:{key}") or 1)
    monkeypatch.setattr(search, "type_text", lambda text: calls.append(f"text:{text}") or len(text))
    monkeypatch.setattr(search, "_get_foreground_window_title", lambda: "Calculadora")

    result = run(search.WindowsSearchTool().execute(query="Calculadora", open_first=True, wait_seconds=0))
    assert result.success
    assert calls == ["key:win+s", "text:Calculadora", "key:enter"]
    assert result.data["foreground"] == "Calculadora"


def test_windows_search_can_leave_results_open(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(search, "press_sequence", lambda key: calls.append(key) or 1)
    monkeypatch.setattr(search, "type_text", lambda text: len(text))
    monkeypatch.setattr(search, "_get_foreground_window_title", lambda: "Windows Search")

    result = run(search.WindowsSearchTool().execute(query="Notepad", open_first=False, wait_seconds=0))
    assert result.success
    assert calls == ["win+s"]
    assert result.data["opened_first_result"] is False
