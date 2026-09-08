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


class StreamedResponse:
    """Resposta de LLM em streaming.

    Itere para receber os tokens de conteúdo (``async for token in resp``);
    após a iteração, ``content`` agrega o texto completo e ``tool_calls``
    traz as tool calls detectadas no turno, quando houver.
    """

    def __init__(self) -> None:
        self.generator: Any | None = None
        self.content: str = ""
        self.tool_calls: list[ToolCall] | None = None

    def __aiter__(self):
        if self.generator is None:
            raise TypeError("StreamedResponse não inicializada")
        return self.generator.__aiter__()


class LLMProvider(Protocol):
    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
    ) -> LLMResponse:
        ...
