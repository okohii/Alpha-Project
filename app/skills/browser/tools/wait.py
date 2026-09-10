from __future__ import annotations

from typing import Any

from app.skills.browser.service import BrowserDriver
from app.tools.base import Tool, ToolPermission, ToolResult


class BrowserWaitTool(Tool):
    name = "browser_wait"
    description = "Aguarda até que um texto apareça na página (ou retorna falso após o timeout)."
    permission = ToolPermission.read

    def __init__(self, driver_factory=None) -> None:
        self._driver_factory = driver_factory

    def _driver(self) -> BrowserDriver:
        return self._driver_factory() if self._driver_factory else BrowserDriver()

    async def execute(self, **kwargs: Any) -> ToolResult:
        text = str(kwargs.get("text", ""))
        if not text:
            return ToolResult(
                name=self.name, success=False, data={}, error="Informe 'text' a aguardar."
            )
        timeout = float(kwargs.get("timeout_s", 15.0))
        driver = self._driver()
        try:
            await driver.start_browser()
            found = await driver.wait_for_text(text, timeout)
            return ToolResult(
                name=self.name,
                success=True,
                data={"found": found, "text": text, "timeout_s": timeout},
            )
        except Exception as exc:
            return ToolResult(name=self.name, success=False, data={}, error=str(exc))
        finally:
            await driver.close()

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Texto a aguardar aparecer"},
                "timeout_s": {"type": "number", "description": "Timeout em segundos (padrão 15)"},
            },
            "required": ["text"],
        }