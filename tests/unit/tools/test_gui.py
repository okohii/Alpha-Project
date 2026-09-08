from __future__ import annotations

import asyncio
from pathlib import Path

from app.tools.computer import (
    MouseClickTool,
    MouseScrollTool,
    PressKeyTool,
    ScreenshotTool,
    VerifyScreenTool,
    _key_vk,
    keyboard,
    mouse,
    mouse_click,
    press_sequence,
    screenshot,
)
from app.tools.files import FileManager


def run(coro):
    return asyncio.run(coro)


def test_key_vk_mapping():
    assert _key_vk("enter") == 0x0D
    assert _key_vk("f5") == 0x74
    assert _key_vk("k") == ord("K")
    assert _key_vk(",,,") is None


def test_press_sequence_sends_modifiers_in_order(monkeypatch):
    sent = []
    monkeypatch.setattr(
        keyboard,
        "_send_key",
        lambda vk, scan, flags: sent.append((vk, scan, flags)),
    )
    pressed = press_sequence("ctrl+shift+k")
    assert pressed == 1
    assert sent == [
        (0x11, 0, 0),  # ctrl down
        (0x10, 0, 0),  # shift down
        (ord("K"), 0, 0),  # k down
        (ord("K"), 0, 2),  # k up
        (0x10, 0, 2),  # shift up
        (0x11, 0, 2),  # ctrl up
    ]


def test_press_sequence_rejects_unknown_key():
    try:
        press_sequence("notakey")
        raise AssertionError("deveria ter falhado")
    except ValueError:
        pass


def test_mouse_click_moves_then_clicks(monkeypatch):
    events = []
    monkeypatch.setattr(mouse, "mouse_move", lambda x, y: events.append(("move", x, y)))
    monkeypatch.setattr(
        mouse,
        "_native_mouse_event",
        lambda flags, data=0: events.append(("event", flags)),
    )

    mouse_click(100, 200, button="right", clicks=2)
    assert events[0] == ("move", 100, 200)
    assert events[1:] == [
        ("event", 0x0008),
        ("event", 0x0010),
        ("event", 0x0008),
        ("event", 0x0010),
    ]


def test_press_key_tool_result(monkeypatch):
    monkeypatch.setattr(keyboard, "press_sequence", lambda key: 1)
    tool = PressKeyTool()
    result = run(tool.execute(key="ctrl+k"))
    assert result.success
    assert result.data["pressed"] == 1


def test_mouse_click_tool_accepts_coordinates(monkeypatch):
    called = {}
    monkeypatch.setattr(
        mouse,
        "mouse_click",
        lambda x, y, button="left", clicks=1: called.update(x=x, y=y, button=button, clicks=clicks),
    )
    tool = MouseClickTool()
    result = run(tool.execute(x=560, y=340, button="left"))
    assert result.success
    assert called == {"x": 560, "y": 340, "button": "left", "clicks": 1}


def test_mouse_scroll_tool(monkeypatch):
    called = {}
    monkeypatch.setattr(mouse, "mouse_scroll", lambda delta: called.update(delta=delta))
    tool = MouseScrollTool()
    result = run(tool.execute(delta=3))
    assert result.success
    assert called["delta"] == 3


def test_screenshot_tool_writes_inside_allowed_dir(tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    manager = FileManager([allowed])
    monkeypatch.setattr(screenshot, "capture_screen", lambda path: path)

    tool = ScreenshotTool(manager)
    result = run(tool.execute(path="foto.png"))
    assert result.success
    saved = Path(result.data["path"])
    assert saved == allowed / "foto.png"


def test_screenshot_tool_default_path(tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    manager = FileManager([allowed])
    monkeypatch.setattr(screenshot, "capture_screen", lambda path: path)

    tool = ScreenshotTool(manager)
    result = run(tool.execute())
    assert result.success
    saved = Path(result.data["path"])
    assert allowed in saved.parents
    assert saved.name.startswith("screen_")
    assert saved.suffix == ".png"


class FakeVision:
    def __init__(self, text="Botão Enviar: (560, 340)"):
        self.text = text
        self.last_path = None

    def available(self):
        return True

    async def describe(self, image_path):
        self.last_path = image_path
        return self.text


def test_screenshot_tool_includes_vision_description(tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    manager = FileManager([allowed])
    monkeypatch.setattr(screenshot, "capture_screen", lambda path: path)
    vision = FakeVision()

    tool = ScreenshotTool(manager, vision=vision)
    result = run(tool.execute(path="foto.png"))
    assert result.success
    assert result.data["screen"] == "Botão Enviar: (560, 340)"
    assert result.data["vision"] is True
    assert vision.last_path == str(allowed / "foto.png")


def test_screenshot_tool_tolerates_vision_failure(tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    manager = FileManager([allowed])
    monkeypatch.setattr(screenshot, "capture_screen", lambda path: path)

    class BrokenVision:
        def available(self):
            return True

        async def describe(self, image_path):
            raise RuntimeError("ollama fora do ar")

    tool = ScreenshotTool(manager, vision=BrokenVision())
    result = run(tool.execute(path="foto.png"))
    assert result.success
    assert result.data["vision"] is False
    assert "ollama fora do ar" in result.data["vision_error"]
    assert "path" in result.data


def test_screenshot_tool_skips_vision_when_unavailable(tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    manager = FileManager([allowed])
    monkeypatch.setattr(screenshot, "capture_screen", lambda path: path)

    class NoVision:
        def available(self):
            return False

        async def describe(self, image_path):
            raise AssertionError("não deveria ser chamado")

    tool = ScreenshotTool(manager, vision=NoVision())
    result = run(tool.execute(path="foto.png"))
    assert result.success
    assert "screen" not in result.data
    assert "path" in result.data


class FakeVerifier:
    def __init__(self, available=True, achieved=True):
        self._available = available
        self.achieved = achieved
        self.last_goal = None

    def available(self):
        return self._available

    async def verify(self, image_path, goal, max_retries=0):
        self.last_goal = goal
        return {
            "achieved": self.achieved,
            "attempts": 1,
            "last": {"achieved": self.achieved, "confidence": 0.9, "feedback": "ok"},
            "details": [],
        }


def test_verify_screen_tool_success(tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    manager = FileManager([allowed])
    monkeypatch.setattr(screenshot, "capture_screen", lambda path: path)
    verifier = FakeVerifier(available=True, achieved=True)

    tool = VerifyScreenTool(manager, verifier=verifier)
    result = run(tool.execute(goal="github aberto"))
    assert result.success
    assert result.data["achieved"] is True
    assert verifier.last_goal == "github aberto"


def test_verify_screen_tool_unavailable(tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    manager = FileManager([allowed])
    monkeypatch.setattr(screenshot, "capture_screen", lambda path: path)

    tool = VerifyScreenTool(manager, verifier=FakeVerifier(available=False))
    result = run(tool.execute(goal="github aberto"))
    assert not result.success
    assert "indisponível" in result.error


def test_verify_screen_tool_requires_goal(tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    manager = FileManager([allowed])
    monkeypatch.setattr(screenshot, "capture_screen", lambda path: path)

    tool = VerifyScreenTool(manager, verifier=FakeVerifier())
    result = run(tool.execute())
    assert not result.success
    assert "meta" in result.error