from __future__ import annotations

import logging
from typing import Any
import json

import httpx

from app.core.config import get_settings
from app.llm.base import LLMMessage, LLMResponse, ToolCall

logger = logging.getLogger("app.llm.gemini")


class GeminiAPIError(RuntimeError):
    def __init__(self, status_code: int, url: str, body: str | None = None) -> None:
        super().__init__(f"Gemini API request failed: status={status_code}, url={url}, body={body}")
        self.status_code = status_code
        self.url = url
        self.body = body


class GeminiProvider:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        settings = get_settings()

        self.api_key = (
            api_key
            or settings.gemini_api_key
            or settings.model_dump().get("google_api_key", "")
        )

        self.model = model or settings.gemini_model
        self.base_url = (base_url or settings.gemini_base_url).rstrip("/")
        self.timeout = settings.llm_timeout_seconds

    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
    ) -> LLMResponse:

        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY não configurada")

        contents: list[dict[str, Any]] = []
        system_instruction: str | None = None

        # ---------------------------------------------------------
        # 1. Separar SYSTEM de USER/ASSISTANT
        # ---------------------------------------------------------
        for message in messages:

            if message.role == "system":
                if system_instruction:
                    system_instruction += "\n\n" + message.content
                else:
                    system_instruction = message.content
                continue

            if message.role == "tool":
                # tool messages should be treated as function responses when structured
                parsed = None
                try:
                    parsed = json.loads(message.content)
                except Exception:
                    parsed = None

                if parsed and parsed.get("type") == "function_response":
                    name = parsed.get("name")
                    response_payload = parsed.get("response", {})
                    # Gemini endpoint does not accept role 'tool' in contents; use 'assistant' role
                    # and include a structured function_response object. This avoids "Role 'tool' is not supported" errors.
                    contents.append(
                        {
                            "role": "assistant",
                            "parts": [
                                {
                                    "function_response": {
                                        "name": name,
                                        "response": response_payload,
                                    }
                                }
                            ],
                        }
                    )
                else:
                    contents.append(
                        {
                            "role": "tool",
                            "parts": [
                                {
                                    "text": message.content
                                }
                            ],
                        }
                    )
                continue

            role = "user" if message.role == "user" else "model"

            contents.append(
                {
                    "role": role,
                    "parts": [
                        {
                            "text": message.content
                        }
                    ],
                }
            )

        # ---------------------------------------------------------
        # 2. Payload
        # ---------------------------------------------------------
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
            },
        }

        if system_instruction:
            payload["systemInstruction"] = {
                "parts": [
                    {
                        "text": system_instruction
                    }
                ]
            }

        # ---------------------------------------------------------
        # 3. Tools
        # ---------------------------------------------------------
        if tools:
            function_declarations: list[dict[str, Any]] = []

            for tool in tools:

                if "function" in tool:
                    fd = dict(tool["function"])
                else:
                    fd = dict(tool)

                parameters = fd.get(
                    "parameters",
                    {
                        "type": "object",
                        "properties": {},
                    },
                )

                sanitized_parameters: dict[str, Any] = {
                    "type": parameters.get("type", "object"),
                    "properties": parameters.get("properties", {}),
                }

                required = parameters.get("required")

                if required:
                    sanitized_parameters["required"] = required

                function_declaration = {
                    "name": fd.get("name"),
                    "description": fd.get("description", ""),
                    "parameters": sanitized_parameters,
                }

                function_declarations.append(function_declaration)

            payload["tools"] = [
                {
                    "function_declarations": function_declarations
                }
            ]

        # ---------------------------------------------------------
        # 4. Requisição
        # ---------------------------------------------------------
        async with httpx.AsyncClient(timeout=self.timeout) as client:

            url = f"{self.base_url}/{self.model}:generateContent"

            logger.debug(
                "Enviando requisição Gemini: model=%s url=%s",
                self.model,
                url,
            )

            response = await client.post(
                url,
                json=payload,
                headers={
                    "x-goog-api-key": self.api_key,
                    "Content-Type": "application/json",
                },
            )

            try:
                response.raise_for_status()

            except httpx.HTTPStatusError as exc:
                # Raise a typed exception with status_code for upstream handling
                raise GeminiAPIError(response.status_code, url, response.text) from exc

            data = response.json()

        # ---------------------------------------------------------
        # 5. Diagnóstico bruto
        # ---------------------------------------------------------
        logger.debug(
            "Resposta bruta Gemini: %s",
            data,
        )

        # ---------------------------------------------------------
        # 6. Candidates
        # ---------------------------------------------------------
        candidates = data.get("candidates") or []

        if not candidates:

            prompt_feedback = data.get("promptFeedback")

            logger.error(
                "Gemini não retornou candidates. promptFeedback=%r raw=%r",
                prompt_feedback,
                data,
            )

            return LLMResponse(
                content="",
                raw=data,
            )

        candidate = candidates[0]

        content = candidate.get("content") or {}
        parts = content.get("parts") or []

        # Detect function/tool call requests from the model
        func_call = None

        # Candidate-level keys
        for key in ("function_call", "functionCall", "tool_call", "toolCall", "toolCallRequest"):
            if key in candidate:
                func_call = candidate[key]
                break

        # Content-level keys
        if not func_call and isinstance(content, dict):
            for key in ("function_call", "functionCall", "tool_call", "toolCall", "toolCallRequest"):
                if key in content:
                    func_call = content[key]
                    break

        # Parts-level inspection
        if not func_call and isinstance(parts, list):
            for part in parts:
                if isinstance(part, dict):
                    for key in ("function_call", "functionCall", "tool_call", "toolCall", "toolCallRequest"):
                        if key in part:
                            func_call = part[key]
                            break
                if func_call:
                    break

        if func_call:
            # normalize function call shape
            name = func_call.get("name") or func_call.get("function") or func_call.get("tool")
            args = func_call.get("arguments") or func_call.get("args") or func_call.get("parameters") or {}
            # arguments may be a JSON string
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    # fallback: leave as raw string under 'raw'
                    args = {"raw": args}

            logger.debug("Gemini requested function call: %s args=%s", name, args)

            return LLMResponse(content="", tool_calls=[ToolCall(name=name, arguments=args)], raw=data)

        text_parts: list[str] = []

        for part in parts:

            if not isinstance(part, dict):
                continue

            text = part.get("text")

            if isinstance(text, str) and text.strip():
                text_parts.append(text)

        text = "\n".join(text_parts).strip()

        # ---------------------------------------------------------
        # 7. Diagnóstico do finishReason
        # ---------------------------------------------------------
        finish_reason = candidate.get("finishReason")

        if not text:
            logger.warning(
                "Gemini retornou resposta sem texto: "
                "finishReason=%r candidate=%r raw=%r",
                finish_reason,
                candidate,
                data,
            )

        return LLMResponse(
            content=text,
            raw=data,
        )