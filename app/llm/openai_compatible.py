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

    ALPHA talks only to the gateway. Provider/account/model selection remains
    outside ALPHA. ``alpha`` is used as the default 9Router combo/profile when
    no explicit gateway model is configured.
    """

    DEFAULT_GATEWAY_MODEL = "alpha"

    def __init__(self, api_key: str | None = None, model: str | None = None, base_url: str | None = None) -> None:
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.cloud_llm_api_key
        self.model = model or settings.cloud_llm_model or self.DEFAULT_GATEWAY_MODEL
        self.base_url = (base_url or settings.cloud_llm_base_url).rstrip("/")
        self.timeout = settings.cloud_llm_timeout_seconds

    @staticmethod
    def _message_payload(message: LLMMessage) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": message.role, "content": message.content}
        if message.tool_call_id:
            payload["tool_call_id"] = message.tool_call_id
        elif message.role == "tool" and isinstance(message.content, str):
            # O envelope JSON do tool result carrega o ``tool_call_id``; o
            # formato OpenAI exige o campo no TOPO da mensagem ``tool`` para o
            # gateway conseguir correlacionar com o assistant(tool_calls).
            try:
                parsed = json.loads(message.content)
                if isinstance(parsed, dict) and parsed.get("tool_call_id"):
                    payload["tool_call_id"] = parsed["tool_call_id"]
            except (TypeError, ValueError):
                pass
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

    @staticmethod
    def _decode_response(response: httpx.Response) -> dict[str, Any]:
        """Decode normal JSON and tolerate gateways that append SSE DONE framing."""
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            text = response.text.strip()
            # Some OpenAI-compatible gateways have returned a valid JSON object
            # followed by an SSE-style terminator even with non-streaming calls.
            # Recover only the first complete JSON object; never silently merge
            # arbitrary trailing data into the response.
            decoder = json.JSONDecoder()
            try:
                data, end = decoder.raw_decode(text)
            except json.JSONDecodeError:
                raise exc
            trailing = text[end:].strip()
            if trailing and trailing not in {"data: [DONE]", "[DONE]"}:
                raise exc
            if not isinstance(data, dict):
                raise exc
            logger.warning("[9ROUTER] tolerated trailing non-JSON framing after response")
            return data

    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
    ) -> LLMResponse:
        if not self.base_url:
            raise RuntimeError("CLOUD_LLM_BASE_URL não configurada")

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [self._message_payload(message) for message in messages],
            "temperature": temperature,
            "stream": False,
        }
        if tools:
            payload["tools"] = self._tools_payload(tools)
            payload["tool_choice"] = "auto"

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        url = f"{self.base_url}/chat/completions"
        logger.info("[9ROUTER] POST %s model=%s tools=%s stream=false", url, self.model, bool(tools))

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
            if response.is_error:
                raise OpenAICompatibleAPIError(response.status_code, url, response.text)
            data = self._decode_response(response)

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
