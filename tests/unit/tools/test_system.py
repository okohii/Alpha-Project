from __future__ import annotations

import asyncio

from app.skills.system.tools.info import (
    _PROGID_TO_BROWSER,
    SystemInfoTool,
    detect_default_browser,
)


def test_progid_mapping_known_browsers():
    assert _PROGID_TO_BROWSER["chromehtml"] == "chrome"
    assert _PROGID_TO_BROWSER["msedgehtm"] == "edge"
    assert _PROGID_TO_BROWSER["zenbrowserhtm"] == "zen"
    assert _PROGID_TO_BROWSER["firefoxurl-308046b0af4a39cb"] == "firefox"
    assert _PROGID_TO_BROWSER.get("desconhecidohtm", "desconhecidohtm") == "desconhecidohtm"


def test_detect_default_browser_non_windows_returns_none(monkeypatch):
    monkeypatch.setattr("os.name", "posix")
    assert detect_default_browser() is None


def test_system_info_reports_default_browser(monkeypatch):
    monkeypatch.setattr(
        "app.skills.system.tools.info.detect_default_browser", lambda: "zen"
    )
    result = asyncio.run(SystemInfoTool().execute())
    assert result.success
    assert result.data["default_browser"] == "zen"
    assert "platform" in result.data