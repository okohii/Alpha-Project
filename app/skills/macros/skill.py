from __future__ import annotations

from app.skills.base import Skill

SKILL = Skill(
    name="Macros",
    description="Gravação, execução e agendamento de macros (sequências de ações automatizadas).",
    keywords=["macro", "macros", "gravar macro", "automatizar", "agendar macro"],
    tools=[
        "macro_list",
        "macro_run",
        "macro_create",
        "macro_delete",
        "macro_schedule",
        "macro_schedules",
        "macro_schedule_edit",
        "macro_schedule_delete",
    ],
)

__all__ = ["SKILL"]