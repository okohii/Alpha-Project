from __future__ import annotations

from typing import Any

from app.services.browser import (
    DuckDuckGoHtmlSearchProvider,
    WebSearchProvider,
    WebUnavailableError,
)
from app.tools.base import Tool, ToolPermission, ToolResult

__all__ = [
    "DuckDuckGoHtmlSearchProvider",
    "WebSearchProvider",
    "WebSearchTool",
    "WebUnavailableError",
]


class WebSearchTool(Tool):
    name = "web_search"
    description = "Pesquisa a web de forma controlada"
    permission = ToolPermission.read

    def __init__(self, provider: WebSearchProvider) -> None:
        self.provider = provider

    async def execute(self, **kwargs: Any) -> ToolResult:
        query = str(kwargs.get("query", ""))
        result = await self.provider.search(query)
        return ToolResult(name=self.name, success=True, data=result)

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Termo a pesquisar na web"},
            },
            "required": ["query"],
        }