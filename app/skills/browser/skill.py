from __future__ import annotations

from app.skills.base import Skill

SKILL = Skill(
    name="Browser",
    description="Navegação web: página atual, clique, texto, js e abertura de sites.",
    keywords=[
        "navegador", "site", "url", "chrome", "edge", "firefox", "brave",
        "github", "youtube", "youtu.be", "web", "página", "pagina",
        "teams", "teams.microsoft", "teams.live",
        "slack", "discord", "telegram", "instagram", "facebook", "twitter",
        "x.com", "linkedin", "gmail", "outlook", "drive.google", "google drive",
        "netflix", "prime video", "primevideo", "spotify", "twitch",
        "vídeo", "videos", "assistir", "pesquisar no site", "pesquisar no google",
    ],
    tools=[
        "browser_open",
        "browser_text",
        "browser_html",
        "browser_js",
        "browser_click",
        "browser_wait",
        "browser_screenshot",
    ],
)

__all__ = ["SKILL"]
