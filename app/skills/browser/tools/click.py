from __future__ import annotations

from typing import Any

from app.skills.browser.service import BrowserDriver
from app.tools.base import Tool, ToolPermission, ToolResult


class BrowserClickTool(Tool):
    name = "browser_click"
    description = (
        "Clica num elemento da página pelo texto visível (ex.: 'Entrar', 'Enviar'). "
        "Tenta um clique DOM direto; também aceita 'x'/'y' para clique em pixel."
    )
    permission = ToolPermission.write

    def __init__(self, driver_factory=None) -> None:
        self._driver_factory = driver_factory

    def _driver(self) -> BrowserDriver:
        return self._driver_factory() if self._driver_factory else BrowserDriver()

    async def execute(self, **kwargs: Any) -> ToolResult:
        driver = self._driver()
        try:
            await driver.start_browser()
            if kwargs.get("x") is not None and kwargs.get("y") is not None:
                await driver.click_point(int(kwargs["x"]), int(kwargs["y"]))
                return ToolResult(
                    name=self.name, success=True, data={"clicked_point": [kwargs["x"], kwargs["y"]]}
                )
            text = str(kwargs.get("text", ""))
            if not text:
                return ToolResult(
                    name=self.name, success=False, data={}, error="Informe 'text' ou 'x'/'y'."
                )
            result = await driver.click(text)
            clicked = bool(result.get("clicked")) if isinstance(result, dict) else bool(result)
            data: dict[str, Any] = {"clicked": clicked, "text": text}
            if isinstance(result, dict):
                data["matches"] = result.get("match", 1)
                if result.get("selected"):
                    data["selected"] = result["selected"]
            return ToolResult(name=self.name, success=clicked, data=data)
        except Exception as exc:
            return ToolResult(name=self.name, success=False, data={}, error=str(exc))
        finally:
            await driver.close()

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Texto visível do elemento a clicar"},
                "x": {"type": "integer", "description": "Coordenada X (clique em pixel)"},
                "y": {"type": "integer", "description": "Coordenada Y (clique em pixel)"},
            },
        }