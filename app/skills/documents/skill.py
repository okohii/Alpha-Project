from __future__ import annotations

from app.skills.base import Skill

SKILL = Skill(
    name="Documents",
    description="Indexação e busca semântica em documentos do projeto/computador.",
    keywords=["indexar", "documento", "pesquisar documento", "buscar documento"],
    tools=[
        "document_search",
    ],
)

__all__ = ["SKILL"]
