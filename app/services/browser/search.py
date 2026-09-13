from __future__ import annotations

from typing import Any

import httpx

from app.core.config import get_settings


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
        async with (
            httpx.AsyncClient(timeout=settings.web_timeout_seconds, follow_redirects=True) as client
        ):
            response = await client.post(
                url,
                data={"q": query},
                headers={"User-Agent": "ALPHA/0.1"},
            )
            response.raise_for_status()
            html = response.text

        import re

        results: list[dict[str, str]] = []

        pattern = re.compile(
            r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            re.IGNORECASE | re.DOTALL,
        )
        matches = pattern.findall(html)
        for href, title_html in matches[:10]:
            title = re.sub(r"<[^>]+>", "", title_html).strip()
            snippet = ""
            try:
                idx = html.index(href)
                start = max(0, idx - 120)
                snippet = re.sub(r"<[^>]+>", "", html[start : start + 240]).strip()
            except Exception:
                snippet = title
            results.append(
                {"title": title or "(sem título)", "url": href, "snippet": snippet}
            )

        if not results:
            results = [
                {
                    "title": "DuckDuckGo",
                    "url": f"https://duckduckgo.com/?q={query}",
                    "snippet": html[:200],
                }
            ]

        return {"query": query, "results": results}