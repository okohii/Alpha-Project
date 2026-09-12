"""Regressões para impedir contaminação entre execuções concorrentes."""
from __future__ import annotations

import asyncio

import pytest

from app.agent.serialized import SerializedAgentCore
from app.llm.base import LLMResponse
from app.llm.router import LLMRouter
from app.tools.registry import ToolRegistry


class _Provider:
    async def complete(self, messages, tools=None, temperature=0.2):
        return LLMResponse(content="ok")


@pytest.mark.anyio
async def test_shared_agent_serializes_concurrent_chat_turns():
    agent = SerializedAgentCore(
        llm_router=LLMRouter(local_provider=_Provider(), cloud_provider=_Provider()),
        tool_registry=ToolRegistry(tools={}),
    )

    active = 0
    maximum = 0
    original = agent._chat_impl

    async def wrapped(message, conversation_id):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0.01)
        try:
            return await original(message, conversation_id)
        finally:
            active -= 1

    agent._chat_impl = wrapped
    await asyncio.gather(
        agent.chat("primeiro", "conv-1"),
        agent.chat("segundo", "conv-2"),
    )

    assert maximum == 1


@pytest.mark.anyio
async def test_shared_agent_serializes_stream_turns():
    agent = SerializedAgentCore(
        llm_router=LLMRouter(local_provider=_Provider(), cloud_provider=_Provider()),
        tool_registry=ToolRegistry(tools={}),
    )

    active = 0
    maximum = 0
    original = agent._chat_impl

    async def wrapped(message, conversation_id):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0.01)
        try:
            return await original(message, conversation_id)
        finally:
            active -= 1

    agent._chat_impl = wrapped

    async def consume(message, conversation_id):
        return [event async for event in agent.chat_stream(message, conversation_id)]

    await asyncio.gather(
        consume("primeiro", "conv-1"),
        consume("segundo", "conv-2"),
    )

    assert maximum == 1
