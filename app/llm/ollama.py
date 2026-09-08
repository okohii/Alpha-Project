from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.core.config import get_settings
from app.llm.base import LLMMessage, LLMResponse, ToolCall


class OllamaUnavailableError(RuntimeError):
    pass


def _render_value(value: Any, indent: int = 0) -> str:
    pad = "  " * indent
    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}{key}:")
                lines.append(_render_value(item, indent + 1))
            else:
                lines.append(f"{pad}{key}={item}")
        return "\n".join(lines)
    if isinstance(value, list):
        lines = []
        for item in value:
            rendered = _render_value(item, indent + 1)
            lines.append(f"{pad}- {rendered}")
        return "\n".join(lines)
    return f"{pad}{value}"


def _render_tool_content(content: str) -> str:
    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        return content
    if not isinstance(payload, dict) or payload.get("type") != "function_response":
        return content
    name = payload.get("name", "ferramenta")
    success = bool(payload.get("success"))
    error = payload.get("error")
    data = payload.get("response")
    lines = [f"[resultado da ferramenta: {name}]"]
    if success:
        rendered = _render_value(data)
        lines.append("Sucesso. Resultado:" if rendered else "Sucesso.")
        if rendered:
            lines.append(rendered)
    else:
        lines.append(f"ERRO: {error or 'falha desconhecida'}")
    return "\n".join(lines)


class OllamaProvider:
    def __init__(self, base_url: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = model or settings.ollama_model
        self.timeout = settings.llm_timeout_seconds
        self.tools_supported = True
        self._logger = logging.getLogger("app.llm.ollama")

    async def health(self) -> bool:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            response = await client.get("/api/tags")
            return response.is_success

    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
    ) -> LLMResponse:
        if not self.model:
            raise OllamaUnavailableError("OLLAMA_MODEL não configurado")
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {
                    "role": message.role,
                    "content": _render_tool_content(message.content)
                    if message.role == "tool"
                    else message.content,
                }
                for message in messages
            ],
            "stream": False,
            "options": {"temperature": temperature},
        }
        if tools:
            payload["tools"] = tools
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            try:
                response = await client.post("/api/chat", json=payload)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if (
                    tools
                    and exc.response.status_code == 400
                    and "does not support tools" in exc.response.text
                ):
                    self.tools_supported = False
                    self._logger.warning(
                        "Modelo %s não suporta tool calling; "
                        "degradando para conversa sem ferramentas.",
                        self.model,
                    )
                    payload.pop("tools", None)
                    response = await client.post("/api/chat", json=payload)
                    response.raise_for_status()
                else:
                    raise
            data = response.json()
        message = data.get("message", {})
        tool_calls = parse_tool_calls(message.get("tool_calls") or [])
        return LLMResponse(
            content=message.get("content", ""),
            tool_calls=tool_calls or None,
            raw=data,
        )

    async def stream_turn(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
    ) -> Any:
        """Streaming de um turno com captura de ``tool_calls``.

        Retorna um ``StreamedResponse``: itere para receber os tokens de
        conteúdo e, ao final, ``.content`` agrega o texto completo e
        ``.tool_calls`` traz as tool calls detectadas.
        """
        from app.llm.base import StreamedResponse

        if not self.model:
            raise OllamaUnavailableError("OLLAMA_MODEL não configurado")
        streamed = StreamedResponse()

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {
                    "role": message.role,
                    "content": _render_tool_content(message.content)
                    if message.role == "tool"
                    else message.content,
                }
                for message in messages
            ],
            "stream": True,
            "options": {"temperature": temperature},
        }
        if tools:
            payload["tools"] = tools

        async def _iterate() -> Any:
            buffer: list[str] = []
            calls: list[ToolCall] = []
            async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
                async with client.stream("POST", "/api/chat", json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        try:
                            line_data = json.loads(line)
                        except ValueError:
                            continue
                        message = line_data.get("message") or {}
                        content = message.get("content")
                        if content:
                            buffer.append(content)
                            yield content
                        if message.get("tool_calls"):
                            calls = parse_tool_calls(message["tool_calls"])
                        if line_data.get("done"):
                            break
            streamed.content = "".join(buffer)
            streamed.tool_calls = calls or None

        streamed.generator = _iterate()
        return streamed


def parse_tool_calls(items: list[dict[str, Any]]) -> list[ToolCall]:
    tool_calls: list[ToolCall] = []
    for item in items:
        function = item.get("function", {})
        tool_calls.append(
            ToolCall(
                name=function.get("name", ""),
                arguments=function.get("arguments", {}) or {},
            )
        )
    return tool_calls
