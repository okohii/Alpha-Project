from __future__ import annotations

from app.skills.base import Skill

SKILL = Skill(
    name="System",
    description="Aplicativos instalados, sistema, configurações, agenda, lembretes e hora.",
    tools=[
        "system_info",
        "system_config",
        "time",
        "run_code",
        "run_shell",
        "calendar_create",
        "calendar_list",
        "calendar_delete",
        "reminder_create",
        "reminder_list",
        "reminder_delete",
    ],
)

__all__ = ["SKILL"]