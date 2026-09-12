from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import uuid4


def _new_call_id() -> str:
    return f"call_{uuid4().hex[:8]}"


@dataclass(slots=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]
    id: str = field(default_factory=_new_call_id)


@dataclass(slots=True)
class LLMMessage:
    role: str
    content: str
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None


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
    status: str | None = None

    def __post_init__(self) -> None:
        if not self.status:
            self.status = "executed" if self.success else "failed"

    def to_dict(self) -> dict[str, Any]:
        return {key: getattr(self, key) for key in self.__dataclass_fields__}


@dataclass(slots=True)
class LLMResponse:
    content: str
    tool_calls: list[ToolCall] | None = None
    raw: dict[str, Any] | None = None


class StreamedResponse:
    """Resposta de LLM em streaming."""

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
