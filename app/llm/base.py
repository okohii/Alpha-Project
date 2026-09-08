from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(slots=True)
class LLMMessage:
    role: str
    content: str


@dataclass(slots=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class LLMResponse:
    content: str
    tool_calls: list[ToolCall] | None = None
    raw: dict[str, Any] | None = None


class LLMProvider(Protocol):
    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
    ) -> LLMResponse:
        ...
