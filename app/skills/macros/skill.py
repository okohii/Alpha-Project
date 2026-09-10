from __future__ import annotations

from app.skills.base import Skill

SKILL = Skill(
    name="macros",
    description="Gravação, execução e agendamento de macros (sequências de ações automatizadas).",
    tools=[
        "macro_list",
        "macro_run",
        "macro_create",
        "macro_delete",
        "macro_schedule",
        "macro_schedules",
    ],
)

__all__ = ["SKILL"]