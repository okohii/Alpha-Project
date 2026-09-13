from __future__ import annotations

from typing import Any

from app.skills.browser.service import BrowserDriver
from app.tools.base import Tool, ToolPermission, ToolResult


class BrowserHtmlTool(Tool):
    name = "browser_html"
    description = "Retorna o HTML atual da aba (ou de um seletor CSS) para inspeção técnica."
    permission = ToolPermission.read

    def __init__(self, driver_factory=None) -> None:
        self._driver_factory = driver_factory

    def _driver(self) -> BrowserDriver:
        return self._driver_factory() if self._driver_factory else BrowserDriver()

    async def execute(self, **kwargs: Any) -> ToolResult:
        driver = self._driver()
        try:
            await driver.start_browser()
            sel = kwargs.get("sel")
            html = await driver.get_html(sel=str(sel) if sel else None)
            data = {"length": len(html), "html": html}
            return ToolResult(name=self.name, success=True, data=data)
        except Exception as exc:
            return ToolResult(name=self.name, success=False, data={}, error=str(exc))
        finally:
            await driver.close()

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "sel": {"type": "string", "description": "Seletor CSS opcional (ex.: 'form', 'h1')"}
            },
        }