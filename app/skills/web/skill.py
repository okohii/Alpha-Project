from __future__ import annotations

from app.skills.base import Skill

SKILL = Skill(
    name="Web",
    description="Pesquisa na web controlada.",
    keywords=[
        "pesquisar", "pesquisa", "buscar na internet", "procurar", "procura",
        "procure", "busque", "notícia", "noticia", "google", "web",
        "vídeo", "videos", "assistir",
    ],
    tools=[
        "web_search",
    ],
)

__all__ = ["SKILL"]
