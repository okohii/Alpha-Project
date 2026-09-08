from __future__ import annotations

from typing import Any

import httpx

from app.core.config import get_settings
from app.tools.base import Tool, ToolPermission, ToolResult


class WebUnavailableError(RuntimeError):
    pass


class WebSearchProvider:
    async def search(self, query: str) -> dict[str, Any]:
        raise NotImplementedError


class DuckDuckGoHtmlSearchProvider(WebSearchProvider):
    async def search(self, query: str) -> dict[str, Any]:
        settings = get_settings()
        if not settings.allow_web:
            raise WebUnavailableError("Pesquisa web desativada")
        url = "https://html.duckduckgo.com/html/"
        async with httpx.AsyncClient(timeout=settings.web_timeout_seconds, follow_redirects=True) as client:
            response = await client.post(url, data={"q": query}, headers={"User-Agent": "ALPHA/0.1"})
            response.raise_for_status()
            html = response.text

        # Attempt to extract result links and titles from DuckDuckGo HTML
        import re

        results: list[dict[str, str]] = []

        # DuckDuckGo html results often contain <a class="result__a" href="...">Title</a>
        pattern = re.compile(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
        matches = pattern.findall(html)
        for href, title_html in matches[:10]:
            # strip HTML tags from title
            title = re.sub(r"<[^>]+>", "", title_html).strip()
            # create a short snippet around the link occurrence
            snippet = ""
            try:
                idx = html.index(href)
                start = max(0, idx - 120)
                snippet = re.sub(r"<[^>]+>", "", html[start:start+240]).strip()
            except Exception:
                snippet = title
            results.append({"title": title or "(sem título)", "url": href, "snippet": snippet})

        if not results:
            # fallback: return a simple DuckDuckGo link
            results = [{"title": "DuckDuckGo", "url": f"https://duckduckgo.com/?q={query}", "snippet": html[:200]}]

        return {"query": query, "results": results}


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
