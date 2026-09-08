from __future__ import annotations

import asyncio
import json

import pytest

from app.tools.browser import BrowserDriver
from app.tools.browser_tools import (
    BrowserClickTool,
    BrowserHtmlTool,
    BrowserJsTool,
    BrowserOpenTool,
    BrowserScreenshotTool,
    BrowserTextTool,
    BrowserWaitTool,
)


class FakeDriverFactory:
    def __init__(self, driver: BrowserDriver) -> None:
        self.driver = driver
        self.calls = 0

    def __call__(self) -> BrowserDriver:
        self.calls += 1
        return self.driver


def eval_value(value) -> dict:
    return {"Runtime.evaluate": {"result": {"result": {"value": value}}}}


class FakeWebSocket:
    """Responde a cada comando CDP com um payload por método que recebe o id enviado."""

    def __init__(self, result_by_method: dict[str, dict] | None = None) -> None:
        from websockets.protocol import State

        self.state = State.OPEN
        self.result_by_method = result_by_method or {}
        self.sent: list[dict] = []
        self.responses: list[dict] = []
        self.closed = False

    async def send(self, raw: str) -> None:
        msg = json.loads(raw)
        self.sent.append(msg)
        payload = self.result_by_method.get(msg["method"], {"result": {}})
        self.responses.append({"id": msg["id"], **payload})

    async def __aiter__(self):
        while True:
            if self.responses:
                yield json.dumps(self.responses.pop(0))
            else:
                await asyncio.sleep(0.02)

    async def close(self) -> None:
        self.closed = True


def _build_driver(monkeypatch, result_by_method: dict[str, dict] | None = None) -> BrowserDriver:
    import app.tools.browser as browser_mod

    driver = BrowserDriver()
    ws = FakeWebSocket(result_by_method)

    async def _fake_connect(url, **kwargs):
        return ws

    monkeypatch.setattr(browser_mod.websockets, "connect", _fake_connect)

    async def _fake_ws_url():
        return "ws://fake"

    driver._ws_url = _fake_ws_url  # type: ignore[method-assign]
    return driver


def _skip_start(driver: BrowserDriver) -> BrowserDriver:
    driver.start_browser = lambda url=None: {"started": True}  # type: ignore[method-assign]
    return driver


@pytest.mark.anyio
async def test_browser_open_tool_normalizes_url(monkeypatch):
    driver = _skip_start(_build_driver(monkeypatch, eval_value("GitHub")))
    sent_messages: list[dict] = []
    orig_close = driver.close

    async def _close_snap():
        sent_messages.extend(driver._ws.sent if driver._ws else [])
        await orig_close()

    driver.close = _close_snap  # type: ignore[method-assign]
    tool = BrowserOpenTool(FakeDriverFactory(driver))

    result = await tool.execute(url="github.com")

    assert result.success is True
    assert result.data["title"] == "GitHub"
    navigate = next(m for m in sent_messages if m["method"] == "Page.navigate")
    assert navigate["params"]["url"] == "https://github.com"


@pytest.mark.anyio
async def test_browser_open_tool_requires_url(monkeypatch):
    driver = _skip_start(_build_driver(monkeypatch))
    tool = BrowserOpenTool(FakeDriverFactory(driver))
    result = await tool.execute(url="")
    assert result.success is False
    assert "Informe a URL" in result.error


@pytest.mark.anyio
async def test_browser_open_tool_surfaces_error(monkeypatch):
    class Boom(BrowserDriver):
        def start_browser(self, url=None):
            raise RuntimeError("boom")

    driver = Boom()
    driver._ws = None
    tool = BrowserOpenTool(FakeDriverFactory(driver))

    result = await tool.execute(url="x.com")

    assert result.success is False
    assert "boom" in result.error


@pytest.mark.anyio
async def test_browser_text_tool_returns_body(monkeypatch):
    driver = _skip_start(_build_driver(monkeypatch, eval_value("Olá mundo")))
    tool = BrowserTextTool(FakeDriverFactory(driver))

    result = await tool.execute()

    assert result.success is True
    assert result.data["text"] == "Olá mundo"


@pytest.mark.anyio
async def test_browser_js_tool(monkeypatch):
    driver = _skip_start(_build_driver(monkeypatch, eval_value(42)))
    tool = BrowserJsTool(FakeDriverFactory(driver))

    result = await tool.execute(expression="2 + 40")

    assert result.success is True
    assert result.data["result"] == 42


@pytest.mark.anyio
async def test_browser_js_tool_requires_expression(monkeypatch):
    driver = _build_driver(monkeypatch)
    tool = BrowserJsTool(FakeDriverFactory(driver))
    result = await tool.execute(expression="")
    assert result.success is False
    assert "Informe a expressão JS" in result.error


@pytest.mark.anyio
async def test_browser_click_tool_by_text(monkeypatch):
    driver = _skip_start(_build_driver(monkeypatch, eval_value(True)))
    tool = BrowserClickTool(FakeDriverFactory(driver))

    result = await tool.execute(text="Entrar")

    assert result.success is True
    assert result.data["clicked"] is True


@pytest.mark.anyio
async def test_browser_click_tool_requires_input(monkeypatch):
    driver = _skip_start(_build_driver(monkeypatch))
    tool = BrowserClickTool(FakeDriverFactory(driver))
    result = await tool.execute()
    assert result.success is False
    assert "Informe" in result.error


@pytest.mark.anyio
async def test_browser_html_tool(monkeypatch):
    driver = _skip_start(_build_driver(monkeypatch, eval_value("<html></html>")))
    tool = BrowserHtmlTool(FakeDriverFactory(driver))

    result = await tool.execute()

    assert result.success is True
    assert result.data["html"] == "<html></html>"


@pytest.mark.anyio
async def test_browser_wait_tool(monkeypatch):
    driver = _skip_start(_build_driver(monkeypatch, eval_value(True)))
    tool = BrowserWaitTool(FakeDriverFactory(driver))

    result = await tool.execute(text="carregado")

    assert result.success is True
    assert result.data["found"] is True


@pytest.mark.anyio
async def test_browser_wait_tool_requires_text(monkeypatch):
    driver = _build_driver(monkeypatch)
    tool = BrowserWaitTool(FakeDriverFactory(driver))
    result = await tool.execute()
    assert result.success is False
    assert "Informe 'text'" in result.error


@pytest.mark.anyio
async def test_driver_navigates_and_gets_title(monkeypatch):
    driver = _build_driver(
        monkeypatch,
        {
            "Page.navigate": {"result": {}},
            "Runtime.evaluate": {"result": {"result": {"value": "Exemplo"}}},
        },
    )

    await driver.connect()
    result = await driver.navigate("https://example.com")

    assert result["title"] == "Exemplo"
    sent = [m["method"] for m in driver._ws.sent]
    assert "Page.navigate" in sent
    assert "Runtime.evaluate" in sent
    await driver.close()


@pytest.mark.anyio
async def test_driver_catches_cdp_error(monkeypatch):
    driver = _build_driver(
        monkeypatch,
        {"Runtime.evaluate": {"error": {"code": -32000, "message": "No target"}}},
    )

    await driver.connect()
    with pytest.raises(Exception) as excinfo:
        await driver.evaluate("1+1")
    assert "No target" in str(excinfo.value)
    await driver.close()


@pytest.mark.anyio
async def test_browser_screenshot_tool(monkeypatch, tmp_path):
    import base64

    png_b64 = base64.b64encode(b"fake-png-bytes").decode()
    driver = _skip_start(
        _build_driver(
            monkeypatch,
            {"Page.captureScreenshot": {"result": {"data": png_b64}}},
        )
    )
    tool = BrowserScreenshotTool(FakeDriverFactory(driver), output_dir=str(tmp_path))
    result = await tool.execute()
    assert result.success is True
    shot = tmp_path / result.data["path"].rsplit("\\", 1)[-1]
    assert shot.read_bytes() == b"fake-png-bytes"
