from __future__ import annotations

from app.skills.base import Skill

SKILL = Skill(
    name="Web",
    description="Pesquisa na web controlada, incluindo clima e previsão do tempo.",
    keywords=[
        "pesquisar", "pesquisa", "buscar na internet", "procurar", "procura",
        "procure", "busque", "notícia", "noticia", "google", "web",
        "vídeo", "videos", "assistir",
        "clima", "previsão do tempo", "previsao do tempo", "previsão", "previsao",
        "temperatura", "chuva", "tempo hoje", "tempo amanhã", "tempo amanha",
    ],
    tools=["web_search"],
)

__all__ = ["SKILL"]
