from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.llm.base import LLMMessage


@dataclass(slots=True)
class AgentContext:
    messages: list[LLMMessage] = field(default_factory=list)
    memories: list[dict[str, Any]] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)
