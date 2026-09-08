from __future__ import annotations

import asyncio

from app.tools import pc as pc_module
from app.tools.apps import AppCatalogEntry, ApplicationLauncher, InstalledAppsProvider
from app.tools.pc import (
    CloseAppTool,
    TypeTextTool,
    _match_running,
    candidate_process_names,
    close_processes,
    running_process_names,
)


def run(coro):
    return asyncio.run(coro)


def test_candidate_process_names_from_path_and_name():
    names = candidate_process_names("Bloco de Notas", r"C:\Windows\System32\notepad.exe")
    assert names == ["notepad", "notepad.exe", "bloco de notas"]


def test_match_running_by_name_and_substring():
    running = ["chrome.exe", "steam.exe", "explorer.exe"]
    assert _match_running(["chrome"], running) == ["chrome.exe"]
    assert _match_running(["steam"], running) == ["steam.exe"]
    assert _match_running(["naoaberto"], running) == []


def test_running_process_names_never_raises():
    names = running_process_names()
    assert isinstance(names, list)


def test_close_processes_error_for_unknown():
    result = close_processes(["naoexiste123abc.exe"])
    assert result["killed"] == []
    assert result["errors"]


def test_close_app_tool_reports_when_app_not_running(tmp_path, monkeypatch):
    executable = tmp_path / "fakeeditor.exe"
    executable.write_text("", encoding="utf-8")

    launcher = ApplicationLauncher(
        catalog=[AppCatalogEntry("fakeeditor", ["meu editor"], hints=[str(executable)])],
        installed=InstalledAppsProvider(),
    )
    monkeypatch.setattr(pc_module, "running_process_names", lambda: [])
    monkeypatch.setattr(pc_module, "close_processes", lambda names: {"killed": [], "errors": []})

    result = run(CloseAppTool(launcher).execute(app="meu editor"))
    assert result.success
    assert result.data["running"] is False


def test_close_app_tool_kills_matching_process(tmp_path, monkeypatch):
    executable = tmp_path / "fakeeditor.exe"
    executable.write_text("", encoding="utf-8")

    launcher = ApplicationLauncher(
        catalog=[AppCatalogEntry("fakeeditor", ["meu editor"], hints=[str(executable)])],
        installed=InstalledAppsProvider(),
    )
    monkeypatch.setattr(
        pc_module, "running_process_names", lambda: ["fakeeditor.exe", "chrome.exe"]
    )
    monkeypatch.setattr(
        pc_module, "close_processes", lambda names: {"killed": list(names), "errors": []}
    )

    result = run(CloseAppTool(launcher).execute(app="meu editor"))
    assert result.success
    assert result.data["killed"] == ["fakeeditor.exe"]


def test_type_text_tool_requires_text():
    tool = TypeTextTool(ApplicationLauncher())
    result = run(tool.execute(text=""))
    assert not result.success


def test_type_text_tool_types_into_focused_window(monkeypatch):
    captured = {}

    def fake_type(text):
        captured["text"] = text
        return len(text)

    monkeypatch.setattr(pc_module, "type_text", fake_type)
    tool = TypeTextTool(ApplicationLauncher())
    result = run(tool.execute(text="olá mundo"))
    assert result.success
    assert captured["text"] == "olá mundo"
    assert result.data["typed_chars"] == len("olá mundo")


def test_type_text_tool_activates_app_window(monkeypatch):
    monkeypatch.setattr(pc_module, "type_text", lambda text: len(text))
    monkeypatch.setattr(pc_module, "activate_window", lambda name: True)
    tool = TypeTextTool(ApplicationLauncher())
    result = run(tool.execute(text="oi", app="bloco de notas"))
    assert result.success
    assert result.data["window"] == "bloco de notas"
    assert result.data["focused"] is True