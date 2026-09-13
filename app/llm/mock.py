from __future__ import annotations

from app.llm.base import LLMMessage, LLMResponse


class MockLLMProvider:
    def __init__(self, responses: list[LLMResponse] | None = None) -> None:
        self._responses = responses or [LLMResponse(content="Olá. Estou em modo mock.")]
        self.calls: list[tuple[list[LLMMessage], list[dict] | None]] = []

    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[dict] | None = None,
        temperature: float = 0.2,
    ) -> LLMResponse:
        self.calls.append((messages, tools))
        if len(self._responses) > 1:
            return self._responses.pop(0)
        return self._responses[0]
