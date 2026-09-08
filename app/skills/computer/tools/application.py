# ruff: noqa: E501 - descrições de ferramentas de aplicativos
from __future__ import annotations

from typing import Any

from app.security import AccessDeniedError
from app.skills.computer.service import (
    ApplicationLauncher,
    _normalize_url,
    _open_url_default,
)
from app.skills.computer.tools.window import launch_on_monitor
from app.tools.base import Tool, ToolPermission, ToolResult


class OpenFileTool(Tool):
    name = "open_file"
    description = (
        "Abre um arquivo ou pasta com o aplicativo padrão do sistema. "
        "Aceita caminho normal ('C:/Users/Downloads/relatorio.txt'), caminho falado "
        "('c barra users barra downloads barra relatorio ponto txt') ou apenas o nome "
        "('relatorio.txt' — procura nas pastas permitidas)."
    )
    permission = ToolPermission.write

    def __init__(self, file_manager: Any) -> None:
        self.file_manager = file_manager

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            path = str(kwargs.get("path", ""))
            result = self.file_manager.open_with_default_app(path)
            return ToolResult(name=self.name, success=True, data=result)
        except (AccessDeniedError, OSError, ValueError) as exc:
            return ToolResult(name=self.name, success=False, data={}, error=exc)

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Caminho do arquivo ou pasta (normal ou 'c barra users barra downloads')",
                },
            },
            "required": ["path"],
        }


class OpenAppTool(Tool):
    name = "open_app"
    description = (
        "Abre um aplicativo/programa instalado no computador pelo nome falado ou verdadeiro. "
        "Ex.: 'abra o chrome', 'abra o bloco de notas', 'abra o excel'. Aceita 'url' opcional "
        "para abrir o app já com um endereço (ex.: 'abra o chrome no site do github', "
        "url='github.com'). Aceita 'monitor' (1, 2, ...) para abrir em um monitor específico "
        "(veja list_monitors). Localiza o executável automaticamente."
    )
    permission = ToolPermission.write

    def __init__(self, launcher: ApplicationLauncher) -> None:
        self.launcher = launcher

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            app = str(kwargs.get("app", ""))
            url = _normalize_url(str(kwargs.get("url", "") or ""))
            monitor = kwargs.get("monitor")
            if monitor is not None:
                monitor = int(monitor)
                if monitor <= 0:
                    raise ValueError("Monitor deve ser um número a partir de 1 (veja list_monitors).")
                info = self.launcher.resolve(app)
                result = launch_on_monitor(info["path"], monitor, args=[url] if url else None)
                return ToolResult(name=self.name, success=True, data=result)
            args = [url] if url else None
            result = self.launcher.launch(app, args=args)
            return ToolResult(name=self.name, success=True, data=result)
        except (ValueError, FileNotFoundError, OSError, RuntimeError) as exc:
            return ToolResult(name=self.name, success=False, data={}, error=exc)

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "app": {"type": "string", "description": "Nome do aplicativo a abrir"},
                "url": {
                    "type": "string",
                    "description": "Opcional: endereço/site para abrir no app (ex.: 'github.com')",
                },
                "monitor": {
                    "type": "integer",
                    "description": "Opcional: número do monitor para abrir o app (ex.: 2)",
                },
            },
            "required": ["app"],
        }


class OpenUrlTool(Tool):
    name = "open_url"
    description = (
        "Abre um endereço/site no navegador padrão ou num navegador específico. "
        "Ex.: 'entre no site do github', 'abre o github no chrome'."
    )
    permission = ToolPermission.write

    def __init__(self, launcher: ApplicationLauncher) -> None:
        self.launcher = launcher

    async def execute(self, **kwargs: Any) -> ToolResult:
        url = _normalize_url(str(kwargs.get("url", "") or ""))
        if not url:
            return ToolResult(
                name=self.name, success=False, data={}, error="Informe a URL a abrir."
            )
        browser = str(kwargs.get("browser", "") or "").strip()
        try:
            if browser:
                result = self.launcher.launch(browser, args=[url])
                data = {"url": url, "browser": result.get("app", browser), "method": "browser"}
            else:
                _open_url_default(url)
                data = {"url": url, "browser": "default", "method": "default"}
            return ToolResult(name=self.name, success=True, data=data)
        except (ValueError, FileNotFoundError, OSError) as exc:
            return ToolResult(name=self.name, success=False, data={}, error=exc)

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Endereço ou site a abrir (ex.: 'github.com')"},
                "browser": {
                    "type": "string",
                    "description": "Opcional: navegador (chrome, edge, firefox...). Se vazio, usa o padrão.",
                },
            },
            "required": ["url"],
        }


class ListAppsTool(Tool):
    name = "list_apps"
    description = (
        "Lista os aplicativos instalados no computador descobertos automaticamente "
        "(Menu Iniciar e registro do Windows) e os aliases conhecidos pelo agente."
    )
    permission = ToolPermission.read

    def __init__(self, launcher: ApplicationLauncher) -> None:
        self.launcher = launcher

    async def execute(self, **kwargs: Any) -> ToolResult:
        installed = [app.to_dict() for app in self.launcher.installed.discover()]
        limit = int(kwargs.get("limit", 100))
        return ToolResult(
            name=self.name,
            success=True,
            data={
                "total_installed": len(installed),
                "known_catalog": [entry.key for entry in self.launcher.catalog],
                "apps": installed[:limit],
                "truncated": len(installed) > limit,
            },
        )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Quantidade máxima de apps a retornar"},
            },
        }