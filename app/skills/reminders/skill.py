from __future__ import annotations

from app.skills.base import Skill

SKILL = Skill(
    name="Reminders",
    description="Lembretes: criar, listar e deletar.",
    keywords=[
        "lembrete", "lembrar", "lembra", "lembre",
        " às 1", "daqui a", "todo dia", "daqui",
        "agendar", "agenda",
    ],
    tools=[
        "reminder_create",
        "reminder_list",
        "reminder_delete",
    ],
)

__all__ = ["SKILL"]
