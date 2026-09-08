from __future__ import annotations

from app.skills.base import Skill

SKILL = Skill(
    name="System",
    description="Informações do sistema, configuração ativa e hora.",
    tools=[
        "system_info",
        "system_config",
        "time",
    ],
)

__all__ = ["SKILL"]
