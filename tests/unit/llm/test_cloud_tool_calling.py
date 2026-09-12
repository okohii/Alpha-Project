"""Tool calling no modo cloud (gateway OpenAI-compatível / 9Router)."""
from __future__ import annotations

import json

from app.llm import openai_compatible
from app.llm.base import LLMMessage
from app.llm.openai_compatible import OpenAICompatibleProvider

SCHEMA = {
    "type": "function",
    "function": {
        "name": "open_app",
        "description": "abre um aplicativo",
        "parameters": {
            "type": "object",
            "properties": {"app": {"type": "string"}},
            "required": ["app"],
        },
    },
}


class FakeResponse:
    is_error = False

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, payload):
        self._payload = payload
        self.url = None
        self.payload = None
        self.headers = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json=None, headers=None):
        self.url = url
        self.payload = json
        self.headers = headers
        return FakeResponse(self._payload)


def _payload_with_tool_call() -> dict:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_cloud_01",
                            "type": "function",
                            "function": {
                                "name": "open_app",
                                "arguments": json.dumps({"app": "bloco de notas"}),
                            },
                        }
                    ],
                }
            }
        ]
    }


async def test_cloud_provider_sends_tools_and_parses_tool_call(monkeypatch):
    client = FakeClient(_payload_with_tool_call())
    monkeypatch.setattr(openai_compatible.httpx, "AsyncClient", lambda **kw: client)

    provider = OpenAICompatibleProvider(
        api_key="secret", base_url="http://gateway:20128/v1", model="alpha"
    )
    response = await provider.complete(
        [LLMMessage(role="user", content="abrir bloco de notas")],
        tools=[SCHEMA],
    )

    assert response.tool_calls and len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "open_app"
    assert response.tool_calls[0].arguments == {"app": "bloco de notas"}
    assert response.tool_calls[0].id == "call_cloud_01"

    # O payload enviado ao gateway inclui as tools e tool_choice=auto.
    assert client.payload["tools"] == [SCHEMA]
    assert client.payload["tool_choice"] == "auto"
    assert client.url.endswith("/chat/completions")


async def test_cloud_provider_round_trips_assistant_tool_calls_back(monkeypatch):
    client = FakeClient({"choices": [{"message": {"role": "assistant", "content": "fim"}}]})
    monkeypatch.setattr(openai_compatible.httpx, "AsyncClient", lambda **kw: client)

    provider = OpenAICompatibleProvider(
        api_key="secret", base_url="http://gateway:20128/v1", model="alpha"
    )
    from app.llm.base import LLMMessage as M
    from app.llm.base import ToolCall

    messages = [
        M(role="user", content="abra o bloco"),
        M(role="assistant", content="", tool_calls=[ToolCall(name="open_app", arguments={"app": "x"}, id="call_1")]),
        M(role="tool", content=json.dumps({"type": "function_response", "name": "open_app", "success": True, "response": {}, "tool_call_id": "call_1"})),
    ]
    response = await provider.complete(messages, tools=[SCHEMA])
    assert response.content == "fim"

    # A msg assistant(tool_calls) e a msg tool são serializadas no formato OpenAI.
    sent = client.payload["messages"]
    assistant_call = next(m for m in sent if m["role"] == "assistant" and m.get("tool_calls"))
    assert assistant_call["tool_calls"][0]["id"] == "call_1"
    assert json.loads(assistant_call["tool_calls"][0]["function"]["arguments"]) == {"app": "x"}
    tool_msg = next(m for m in sent if m["role"] == "tool")
    assert tool_msg["tool_call_id"] == "call_1"