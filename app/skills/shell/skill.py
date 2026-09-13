from __future__ import annotations

from app.skills.base import Skill

SKILL = Skill(
    name="Shell",
    description="Execução de código Python e comandos de shell em sandbox.",
    keywords=["terminal", "comando de shell", "script", "código", "codigo"],
    tools=[
        "run_code",
        "run_shell",
    ],
)

__all__ = ["SKILL"]
