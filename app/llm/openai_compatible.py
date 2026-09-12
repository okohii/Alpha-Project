from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.core.config import get_settings
from app.llm.base import LLMMessage, LLMResponse, ToolCall

logger = logging.getLogger("app.llm.openai_compatible")


class OpenAICompatibleAPIError(RuntimeError):
    def __init__(self, status_code: int, url: str, body: str | None = None) -> None:
        super().__init__(f"OpenAI-compatible request failed: status={status_code}, url={url}, body={body}")
        self.status_code = status_code
        self.url = url
        self.body = body


class OpenAICompatibleProvider:
    """Provider for OpenAI-compatible gateways such as 9Router.

    ALPHA talks only to the gateway. Provider/account fallback stays outside
    ALPHA, which keeps the agent independent from any individual cloud vendor.
    """

    def __init__(self, api_key: str | None = None, model: str | None = None, base_url: str | None = None) -> None:
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.cloud_llm_api_key
        self.model = model or settings.cloud_llm_model
        self.base_url = (base_url or settings.cloud_llm_base_url).rstrip("/")
        self.timeout = settings.cloud_llm_timeout_seconds

    @staticmethod
    def _message_payload(message: LLMMessage) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": message.role, "content": message.content}
        if message.tool_call_id:
            payload["tool_call_id"] = message.tool_call_id
        if message.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments or {}, ensure_ascii=False),
                    },
                }
                for call in message.tool_calls
            ]
        return payload

    @staticmethod
    def _tools_payload(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for tool in tools:
            function = dict(tool["function"]) if "function" in tool else dict(tool)
            normalized.append({"type": "function", "function": function})
        return normalized

    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
    ) -> LLMResponse:
        if not self.base_url:
            raise RuntimeError("CLOUD_LLM_BASE_URL não configurada")
        if not self.model:
            raise RuntimeError("CLOUD_LLM_MODEL não configurado")

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [self._message_payload(message) for message in messages],
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = self._tools_payload(tools)
            payload["tool_choice"] = "auto"

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        url = f"{self.base_url}/chat/completions"
        logger.debug("Enviando requisição OpenAI-compatible: model=%s url=%s", self.model, url)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
            if response.is_error:
                raise OpenAICompatibleAPIError(response.status_code, url, response.text)
            data = response.json()

        choices = data.get("choices") or []
        if not choices:
            return LLMResponse(content="", raw=data)
        message = choices[0].get("message") or {}
        content = message.get("content") or ""
        raw_tool_calls = message.get("tool_calls") or []
        tool_calls: list[ToolCall] = []
        for raw_call in raw_tool_calls:
            function = raw_call.get("function") or {}
            name = function.get("name")
            if not name:
                continue
            arguments = function.get("arguments") or {}
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {"raw": arguments}
            if not isinstance(arguments, dict):
                arguments = {"raw": arguments}
            tool_calls.append(
                ToolCall(
                    name=name,
                    arguments=arguments,
                    id=raw_call.get("id") or ToolCall(name=name, arguments={}).id,
                )
            )
        return LLMResponse(content=content, tool_calls=tool_calls or None, raw=data)


__all__ = ["OpenAICompatibleAPIError", "OpenAICompatibleProvider"]
