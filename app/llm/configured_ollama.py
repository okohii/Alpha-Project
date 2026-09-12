from __future__ import annotations

from typing import Any

from app.llm.base import LLMMessage, LLMResponse
from app.llm.ollama import OllamaProvider


class ConfiguredOllamaProvider(OllamaProvider):
    """Ollama provider that uses ALPHA inference settings when the caller omits them."""

    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        value = self._settings.llm_temperature if temperature is None else temperature
        return await super().complete(messages, tools=tools, temperature=value)

    async def stream_turn(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
    ) -> Any:
        value = self._settings.llm_temperature if temperature is None else temperature
        return await super().stream_turn(messages, tools=tools, temperature=value)


__all__ = ["ConfiguredOllamaProvider"]
