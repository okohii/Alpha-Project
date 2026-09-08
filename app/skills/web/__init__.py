from __future__ import annotations

from app.skills.base import Skill

SKILL = Skill(
    name="Web",
    description="Pesquisa na web controlada.",
    tools=["web_search"],
)

__all__ = ["SKILL"]