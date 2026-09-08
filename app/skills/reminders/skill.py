from __future__ import annotations

from app.skills.base import Skill

SKILL = Skill(
    name="Reminders",
    description="Lembretes: criar, listar e deletar.",
    tools=[
        "reminder_create",
        "reminder_list",
        "reminder_delete",
    ],
)

__all__ = ["SKILL"]
