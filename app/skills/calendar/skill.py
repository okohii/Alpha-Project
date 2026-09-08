from __future__ import annotations

from app.skills.base import Skill

SKILL = Skill(
    name="Calendar",
    description="Agenda: criar, listar e deletar eventos.",
    tools=[
        "calendar_create",
        "calendar_list",
        "calendar_delete",
    ],
)

__all__ = ["SKILL"]
