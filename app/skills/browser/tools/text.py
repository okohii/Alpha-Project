from __future__ import annotations

from typing import Any

from app.skills.browser.service import BrowserDriver
from app.tools.base import Tool, ToolPermission, ToolResult


class BrowserTextTool(Tool):
    name = "browser_text"
    description = (
        "Retorna o texto visível da aba atual. Passe 'query' para buscar apenas trechos que "
        "contêm o termo. Use para entender o conteúdo da página após uma navegação."
    )
    permission = ToolPermission.read

    def __init__(self, driver_factory=None) -> None:
        self._driver_factory = driver_factory

    def _driver(self) -> BrowserDriver:
        return self._driver_factory() if self._driver_factory else BrowserDriver()

    async def execute(self, **kwargs: Any) -> ToolResult:
        driver = self._driver()
        try:
            driver.start_browser()
            query = kwargs.get("query")
            if query:
                text = await driver.get_text(partial=str(query))
            else:
                text = await driver.get_text()
            if not text:
                text = await driver.get_text(sel="body")
            data = {"length": len(text), "text": text}
            return ToolResult(name=self.name, success=True, data=data)
        except Exception as exc:
            return ToolResult(name=self.name, success=False, data={}, error=str(exc))
        finally:
            await driver.close()

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Termo para filtrar o texto (opcional)"}
            },
        }