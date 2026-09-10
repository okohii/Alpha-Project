from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(slots=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class LLMMessage:
    role: str
    content: str
    tool_calls: list[ToolCall] | None = None


@dataclass(slots=True)
class ExecutionEvidence:
    """Registro observado de uma execução de ferramenta.

    Permite distinguir o que foi *observado* (success/result reais) de
    suposições do modelo ou memória. Todo turno de ferramenta produz uma.
    """

    action_id: str
    tool: str
    arguments: dict[str, Any]
    executed_at: str
    success: bool
    result: dict[str, Any]
    error: str | None = None
    verified: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {key: getattr(self, key) for key in self.__dataclass_fields__}


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
