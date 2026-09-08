from __future__ import annotations

import asyncio
import os

import pytest

import app.skills.computer.tools.window as w
from app.skills.computer.tools.window import ListMonitorsTool, MoveAppTool


def run(coro):
    return asyncio.run(coro)


MONITOR1 = {
    "monitor": 1,
    "name": "PRINCIPAL",
    "left": 0,
    "top": 0,
    "width": 1920,
    "height": 1080,
    "primary": True,
}
MONITOR2 = {
    "monitor": 2,
    "name": "SECUNDARIO",
    "left": -1080,
    "top": -847,
    "width": 1080,
    "height": 1920,
    "primary": False,
}


def test_list_monitors_empty_off_windows(monkeypatch):
    monkeypatch.setattr(os, "name", "posix")
    assert w.list_monitors() == []


def test_move_app_success(monkeypatch):
    calls = {}
    monkeypatch.setattr(w, "list_monitors", lambda: [MONITOR1, MONITOR2])
    monkeypatch.setattr(
        w,
        "find_app_window",
        lambda name, resolved_path=None: (123, "discord.exe"),
    )
    monkeypatch.setattr(
        w,
        "move_window",
        lambda hwnd, monitor, maximize=False: calls.update(hwnd=hwnd, monitor=monitor),
    )
    monkeypatch.setattr(w, "bring_to_front", lambda hwnd: calls.update(front=hwnd))
    result = w.move_app("discord", 2)
    assert result["moved"] is True
    assert result["monitor"] == 2
    assert calls["hwnd"] == 123
    assert calls["monitor"] == MONITOR2
    assert calls["front"] == 123


def test_move_app_window_not_found(monkeypatch):
    monkeypatch.setattr(w, "list_monitors", lambda: [MONITOR1, MONITOR2])
    monkeypatch.setattr(w, "find_app_window", lambda name, resolved_path=None: (0, None))
    with pytest.raises(FileNotFoundError):
        w.move_app("discord", 2)


def test_move_app_bad_monitor(monkeypatch):
    monkeypatch.setattr(w, "list_monitors", lambda: [MONITOR1])
    monkeypatch.setattr(w, "find_app_window", lambda name, resolved_path=None: (123, "app.exe"))
    with pytest.raises(ValueError):
        w.move_app("app", 5)


def test_move_app_tool_success(monkeypatch):
    called = {}

    def fake_move(app, monitor, resolved_path=None):
        called["app"] = app
        called["monitor"] = monitor
        return {"app": app, "moved": True, "monitor": monitor, "monitor_name": "SECUNDARIO"}

    monkeypatch.setattr(w, "move_app", fake_move)
    tool = MoveAppTool(launcher=None)
    result = run(tool.execute(app="discord", monitor=2))
    assert result.success
    assert result.data["moved"] is True
    assert called == {"app": "discord", "monitor": 2}


def test_move_app_tool_requires_args():
    tool = MoveAppTool(launcher=None)
    result = run(tool.execute())
    assert not result.success
    assert "aplicativo" in result.error


def test_move_app_tool_ignores_resolve_failure(monkeypatch):
    class BrokenLauncher:
        def resolve(self, name):
            raise ValueError("não achou")

    called = {}
    monkeypatch.setattr(
        w,
        "move_app",
        lambda app, monitor, resolved_path=None: called.update(app=app, monitor=monitor)
        or {},
    )
    tool = MoveAppTool(launcher=BrokenLauncher())
    result = run(tool.execute(app="discord", monitor=1))
    assert result.success
    assert called["app"] == "discord"


def test_list_monitors_tool(monkeypatch):
    monkeypatch.setattr(w, "list_monitors", lambda: [MONITOR1, MONITOR2])
    tool = ListMonitorsTool()
    result = run(tool.execute())
    assert result.success
    assert result.data["total"] == 2
    assert result.data["monitors"][0]["monitor"] == 1


@pytest.mark.skipif(os.name != "nt", reason="Windows only")
def test_launch_on_monitor_moves_new_window(monkeypatch, tmp_path):
    app = tmp_path / "app.exe"
    app.write_bytes(b"MZ")
    monkeypatch.setattr(w, "list_monitors", lambda: [MONITOR1, MONITOR2])
    calls = []
    monkeypatch.setattr(
        w,
        "_windows_matching_stem",
        lambda stem: calls.append(stem) or ({55} if len(calls) > 1 else set()),
    )

    class Proc:
        def poll(self):
            return None

    monkeypatch.setattr(w.subprocess, "Popen", lambda *args, **kw: Proc())
    moved = {}
    monkeypatch.setattr(
        w,
        "move_window",
        lambda hwnd, monitor, maximize=False: moved.update(hwnd=hwnd, monitor=monitor),
    )
    monkeypatch.setattr(w, "bring_to_front", lambda hwnd: moved.update(front=hwnd))

    result = w.launch_on_monitor(str(app), 2)
    assert result["moved"] is True
    assert moved["hwnd"] == 55
    assert moved["monitor"] == MONITOR2


@pytest.mark.skipif(os.name != "nt", reason="Windows only")
def test_launch_on_monitor_reuses_existing_window(monkeypatch, tmp_path):
    app = tmp_path / "app.exe"
    app.write_bytes(b"MZ")
    monkeypatch.setattr(w, "list_monitors", lambda: [MONITOR1, MONITOR2])
    monkeypatch.setattr(w, "_windows_matching_stem", lambda stem: {10})

    class Proc:
        def poll(self):
            return 0

    monkeypatch.setattr(w.subprocess, "Popen", lambda *args, **kw: Proc())
    moved = {}
    monkeypatch.setattr(
        w,
        "move_window",
        lambda hwnd, monitor, maximize=False: moved.update(hwnd=hwnd),
    )
    monkeypatch.setattr(w, "bring_to_front", lambda hwnd: moved.update(front=hwnd))

    result = w.launch_on_monitor(str(app), 2)
    assert result["moved"] is True
    assert moved["hwnd"] == 10


@pytest.mark.skipif(os.name != "nt", reason="Windows only")
def test_launch_on_monitor_fails_without_window(monkeypatch, tmp_path):
    app = tmp_path / "app.exe"
    app.write_bytes(b"MZ")
    monkeypatch.setattr(w, "list_monitors", lambda: [MONITOR1, MONITOR2])
    monkeypatch.setattr(w, "_windows_matching_stem", lambda stem: set())

    class Proc:
        def poll(self):
            return 1

        def terminate(self):
            pass

    monkeypatch.setattr(w.subprocess, "Popen", lambda *args, **kw: Proc())

    result = w.launch_on_monitor(str(app), 2)
    assert result["moved"] is False