from __future__ import annotations

from app.skills.base import Skill

SKILL = Skill(
    name="Files",
    description="Leitura, escrita, busca e metadados de arquivos autorizados.",
    tools=[
        "file_search",
        "file_read",
        "file_write",
        "file_info",
        "open_file",
    ],
)

__all__ = ["SKILL"]
