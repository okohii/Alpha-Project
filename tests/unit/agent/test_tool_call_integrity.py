from __future__ import annotations

import asyncio

import pytest

from app.agent.serialized import SerializedAgentCore
from app.llm.base import ExecutionEvidence, LLMMessage, LLMResponse, ToolCall


class FakeProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def complete(self, messages, tools=None, temperature=0.2):
        self.calls.append((messages, tools))
        return self.responses.pop(0)


@pytest.fixture
def agent():
    obj = object.__new__(SerializedAgentCore)
    obj._turn_lock = asyncio.Lock()
    obj.event_bus = None
    obj._emit = lambda *args, **kwargs: None
    return obj


def test_detects_textual_tool_intent_when_known_tool_is_mentioned():
    tools = [{"type": "function", "function": {"name": "web_search"}}]
    assert SerializedAgentCore._looks_like_tool_intent(
        "Vou usar a função web_search para consultar a previsão.", tools
    )


def test_does_not_detect_normal_answer_as_tool_intent():
    tools = [{"type": "function", "function": {"name": "web_search"}}]
    assert not SerializedAgentCore._looks_like_tool_intent(
        "Hoje está tudo bem por aqui.", tools
    )


def test_synthetic_tool_response_is_blocked_without_retry():
    tools = [{"type": "function", "function": {"name": "web_search"}}]
    assert SerializedAgentCore._scrub_synthetic_tool_response(
        "<tool_response>web_search executada com sucesso</tool_response>"
    ) == "Não posso considerar uma ferramenta executada sem uma chamada nativa real."


@pytest.mark.asyncio
async def test_provider_retries_when_model_describes_tool_without_native_call(agent):
    provider = FakeProvider(
        [
            LLMResponse(content="Vou usar web_search para pesquisar o clima."),
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(name="web_search", arguments={"query": "clima hoje"})
                ],
            ),
        ]
    )
    result = await agent._provider_turn(
        provider,
        [LLMMessage(role="user", content="qual o clima?")],
        [{"type": "function", "function": {"name": "web_search"}}],
        False,
    )
    assert result.tool_calls
    assert result.tool_calls[0].name == "web_search"
    assert len(provider.calls) == 2


@pytest.mark.asyncio
async def test_textual_tool_intent_is_not_executed_if_retry_still_has_no_call(agent):
    provider = FakeProvider(
        [
            LLMResponse(content="Vou usar web_search para pesquisar o clima."),
            LLMResponse(content="Não consegui realizar a pesquisa."),
        ]
    )
    result = await agent._provider_turn(
        provider,
        [LLMMessage(role="user", content="qual o clima?")],
        [{"type": "function", "function": {"name": "web_search"}}],
        False,
    )
    assert result.tool_calls is None
    assert len(provider.calls) == 2


def test_serialized_agent_does_not_expand_skill_catalog_after_tool_call(agent):
    allowed = {"web_search", "browser_text"}
    assert agent._expand_tools(allowed, ["web_search", "browser_text"]) == allowed


def test_open_url_does_not_verify_weather_claim(agent):
    evidence = [
        ExecutionEvidence(
            action_id="1",
            tool="open_url",
            arguments={"url": "https://example.test"},
            executed_at="now",
            success=True,
            result={"url": "https://example.test"},
        )
    ]
    result = agent._apply_honesty_gate(
        "Aqui está a previsão do tempo para hoje.", evidence
    )
    assert "não consegui verificar" in result.lower()


def test_web_search_allows_weather_claim_to_reach_normal_honesty_gate(agent):
    evidence = [
        ExecutionEvidence(
            action_id="1",
            tool="web_search",
            arguments={"query": "previsão do tempo hoje"},
            executed_at="now",
            success=True,
            result={"results": [{"title": "Previsão", "snippet": "25 °C"}]},
        )
    ]
    result = agent._apply_honesty_gate(
        "Encontrei a previsão do tempo para hoje.", evidence
    )
    assert result == "Encontrei a previsão do tempo para hoje."
