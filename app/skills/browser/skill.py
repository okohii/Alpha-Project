from __future__ import annotations

from app.skills.base import Skill

SKILL = Skill(
    name="Browser",
    description="Navegação web: página atual, clique, texto, js e abertura de sites.",
    tools=[
        "browser_open",
        "browser_text",
        "browser_html",
        "browser_js",
        "browser_click",
        "browser_wait",
        "browser_screenshot",
        "open_url",
    ],
)

__all__ = ["SKILL"]
