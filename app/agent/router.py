from __future__ import annotations

from enum import StrEnum


class AgentRoute(StrEnum):
    general = "general"
    memory = "memory"
    documents = "documents"
    web = "web"
