from __future__ import annotations

from typing import Any

from app.skills.browser.service import BrowserDriver
from app.tools.base import Tool, ToolPermission, ToolResult


class BrowserJsTool(Tool):
    name = "browser_js"
    description = "Executa JavaScript na página atual e devolve o resultado."
    permission = ToolPermission.sensitive

    def __init__(self, driver_factory=None) -> None:
        self._driver_factory = driver_factory

    def _driver(self) -> BrowserDriver:
        return self._driver_factory() if self._driver_factory else BrowserDriver()

    async def execute(self, **kwargs: Any) -> ToolResult:
        expression = str(kwargs.get("expression", "")).strip()
        if not expression:
            return ToolResult(
                name=self.name, success=False, data={}, error="Informe a expressão JS."
            )
        driver = self._driver()
        try:
            await driver.start_browser()
            value = await driver.evaluate(expression)
            return ToolResult(name=self.name, success=True, data={"result": value})
        except Exception as exc:
            return ToolResult(name=self.name, success=False, data={}, error=str(exc))
        finally:
            await driver.close()

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"expression": {"type": "string", "description": "JavaScript a avaliar"}},
            "required": ["expression"],
        }