from __future__ import annotations

from app.skills.base import Skill

SKILL = Skill(
    name="Tasks",
    description="Tarefas persistentes do executor automático.",
    keywords=["tarefa", "executar", "rotina", "agendar tarefa"],
    tools=[
        "task_create",
        "task_execute",
        "task_list",
        "task_register_path",
    ],
)

__all__ = ["SKILL"]
