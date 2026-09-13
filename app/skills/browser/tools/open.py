from __future__ import annotations

from typing import Any

from app.security.urlpolicy import normalize_url
from app.skills.browser.service import BrowserDriver
from app.tools.base import Tool, ToolPermission, ToolResult


def _coerce_url(url: str) -> str:
    """Coerção de URL — fonte única em ``app.security.urlpolicy``."""
    return normalize_url(url)


class BrowserOpenTool(Tool):
    name = "browser_open"
    description = (
        "Abre uma página no navegador controlado (Chrome/Edge via CDP) e devolve o título. "
        "Ex.: browser_open url='github.com'. Para leitura da página, use browser_text/browser_html."
    )
    permission = ToolPermission.write

    def __init__(self, driver_factory=None) -> None:
        self._driver_factory = driver_factory

    def _driver(self) -> BrowserDriver:
        return self._driver_factory() if self._driver_factory else BrowserDriver()

    async def execute(self, **kwargs: Any) -> ToolResult:
        url = _coerce_url(str(kwargs.get("url", "")))
        if not url:
            return ToolResult(name=self.name, success=False, data={}, error="Informe a URL.")
        # SSRF hardening (Parte 7/39): destinos proibidos nunca são navegados.
        from app.security.urlpolicy import UnsafeUrlError, coerce_safe_url

        try:
            url = coerce_safe_url(url)
        except UnsafeUrlError as exc:
            return ToolResult(
                name=self.name, success=False, data={}, error=f"destino bloqueado: {exc}"
            )
        driver = self._driver()
        try:
            await driver.start_browser(url)
            result = await driver.navigate(url)
            return ToolResult(name=self.name, success=True, data=result)
        except Exception as exc:
            return ToolResult(name=self.name, success=False, data={}, error=str(exc))
        finally:
            await driver.close()

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "Endereço/site a abrir"}},
            "required": ["url"],
        }