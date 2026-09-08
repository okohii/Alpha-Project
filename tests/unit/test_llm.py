from __future__ import annotations

from app.llm.base import LLMMessage, LLMResponse, ToolCall
from app.llm.mock import MockLLMProvider
from app.llm.ollama import parse_tool_calls
from app.llm.router import LLMRouter


def test_mock_llm_provider_returns_configured_response():
    provider = MockLLMProvider([LLMResponse(content="ok")])

    import anyio

    response = anyio.run(provider.complete, [LLMMessage(role="user", content="Olá")])
    assert response.content == "ok"


def test_llm_router_defaults_to_local_provider():
    router = LLMRouter(local_provider=MockLLMProvider(), cloud_provider=MockLLMProvider())

    assert router.choose() is router.local_provider


def test_parse_tool_calls():
    tool_calls = parse_tool_calls(
        [{"function": {"name": "time", "arguments": {"timezone": "UTC"}}}]
    )
    assert tool_calls == [ToolCall(name="time", arguments={"timezone": "UTC"})]


def test_gemini_provider_returns_content_from_api(monkeypatch):
    import anyio

    from app.llm.gemini import GeminiProvider

    captured = {}

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return FakeResponse({
                "candidates": [{
                    "content": {"parts": [{"text": "Resposta do Gemini"}]}
                }]
            })

    monkeypatch.setattr("app.llm.gemini.httpx.AsyncClient", FakeClient)
    provider = GeminiProvider(api_key="secret-key", model="gemini-2.0-flash")

    response = anyio.run(provider.complete, [LLMMessage(role="user", content="Olá")])

    assert response.content == "Resposta do Gemini"
    assert captured["headers"]["x-goog-api-key"] == "secret-key"
    assert captured["json"]["contents"][0]["parts"][0]["text"] == "Olá"
