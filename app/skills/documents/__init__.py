from __future__ import annotations

from app.skills.base import Skill

SKILL = Skill(
    name="Documents",
    description="Indexação e busca semântica em documentos do projeto/computador.",
    tools=[
        "document_search",
    ],
)

__all__ = ["SKILL"]