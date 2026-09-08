"""Ferramentas de navegação web via CDP."""

from __future__ import annotations

import re
from typing import Any

from app.tools.base import Tool, ToolPermission, ToolResult
from app.tools.browser import BrowserDriver


def _coerce_url(url: str) -> str:
    url = url.strip()
    if not url:
        return ""
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
        return "https://" + url
    return url


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
        driver = self._driver()
        try:
            driver.start_browser(url)
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
            driver.start_browser()
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


class BrowserJsTool(Tool):
    name = "browser_js"
    description = "Executa JavaScript na página atual e devolve o resultado."
    permission = ToolPermission.write

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
            driver.start_browser()
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
            driver.start_browser()
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
            clicked = await driver.click(text)
            return ToolResult(
                name=self.name, success=clicked, data={"clicked": clicked, "text": text}
            )
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
            driver.start_browser()
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
