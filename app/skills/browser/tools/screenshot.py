from __future__ import annotations

from typing import Any

from app.skills.browser.service import BrowserDriver
from app.tools.base import Tool, ToolPermission, ToolResult


class BrowserScreenshotTool(Tool):
    name = "browser_screenshot"
    description = (
        "Captura um screenshot da aba atual e salva em PNG. Use para 'ver' a página "
        "quando textos puros não bastarem. Retorna o caminho do arquivo."
    )
    permission = ToolPermission.read

    def __init__(self, driver_factory=None, output_dir: str | None = None) -> None:
        self._driver_factory = driver_factory
        self._output_dir = output_dir

    def _driver(self) -> BrowserDriver:
        return self._driver_factory() if self._driver_factory else BrowserDriver()

    async def execute(self, **kwargs: Any) -> ToolResult:
        import os
        import tempfile
        import uuid

        driver = self._driver()
        try:
            driver.start_browser()
            out_dir = self._output_dir or os.path.join(tempfile.gettempdir(), "alpha_shots")
            os.makedirs(out_dir, exist_ok=True)
            path = os.path.join(out_dir, f"browser_{uuid.uuid4().hex[:8]}.png")
            await driver.screenshot(path)
            size = os.path.getsize(path)
            return ToolResult(name=self.name, success=True, data={"path": path, "size_bytes": size})
        except Exception as exc:
            return ToolResult(name=self.name, success=False, data={}, error=str(exc))
        finally:
            await driver.close()