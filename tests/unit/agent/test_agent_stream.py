"""Testes do `chat_stream` focados na race condition entre fila e task.

Cobre: conclusão da task antes/durante o consumo, fila vazia, exceção na
task, cancelamento e stream normal — todos com timeout para detectar hangs.
"""
from __future__ import annotations

import asyncio

import pytest

from app.agent.agent import AgentCore
from app.core.events import EventBus, EventType
from app.llm.base import LLMResponse, StreamedResponse
from app.llm.router import LLMRouter
from app.tools.registry import ToolRegistry


class BurstProvider:
    """Emite todos os tokens e conclui sem esperar."""

    def __init__(self, tokens: list[str]) -> None:
        self.tokens = list(tokens)

    async def complete(self, messages, tools=None, temperature=0.2):
        return LLMResponse(content="".join(self.tokens))

    async def stream_turn(self, messages, tools=None, temperature=0.2):
        streamed = StreamedResponse()

        async def _iterate():
            for token in self.tokens:
                yield token
            streamed.content = "".join(self.tokens)

        streamed.generator = _iterate()
        return streamed


class GatedProvider:
    """Stream que tranca a conclusão num asyncio.Event."""

    def __init__(self, tokens: list[str] | None = None) -> None:
        self.tokens = list(tokens or ["o", "k"])
        self.release = asyncio.Event()
        self.consumed_first_token = asyncio.Event()

    async def complete(self, messages, tools=None, temperature=0.2):
        await self.release.wait()
        return LLMResponse(content="".join(self.tokens))

    async def stream_turn(self, messages, tools=None, temperature=0.2):
        streamed = StreamedResponse()

        async def _iterate():
            for i, token in enumerate(self.tokens):
                yield token
                if i == 0:
                    self.consumed_first_token.set()
            await self.release.wait()
            streamed.content = "".join(self.tokens)

        streamed.generator = _iterate()
        return streamed


class FailingProvider(GatedProvider):
    """Emite um token e então falha de forma controlável."""

    def __init__(self) -> None:
        super().__init__(tokens=["parcial"])
        self.fail_now = asyncio.Event()

    async def stream_turn(self, messages, tools=None, temperature=0.2):
        streamed = StreamedResponse()

        async def _iterate():
            yield "parcial"
            self.consumed_first_token.set()
            await self.fail_now.wait()
            raise RuntimeError("modelo explodiu")

        streamed.generator = _iterate()
        return streamed


class FakeMemoryService:
    async def search_memories(self, query: str, limit: int = 5):
        return []

    async def load_profile(self, limit: int = 50):
        return []

    async def save_episode(self, user_message, response, tool_names=None):
        return type("Memory", (), {"content": user_message})()


def _agent(event_bus: EventBus, provider) -> AgentCore:
    return AgentCore(
        llm_router=LLMRouter(local_provider=provider, cloud_provider=provider),
        tool_registry=ToolRegistry(tools={}),
        memory_service=FakeMemoryService(),
        event_bus=event_bus,
    )


@pytest.mark.anyio
async def test_stream_normal_delivers_all_events():
    bus = EventBus()
    finished: list[dict] = []
    bus.subscribe(EventType.agent_finished, lambda e: finished.append(e.payload))
    agent = _agent(bus, BurstProvider(["a", "b", "c"]))

    types: list[EventType] = []
    async for event in agent.chat_stream("oi"):
        types.append(event.type)

    assert EventType.token_stream in types
    assert EventType.assistant_message in types
    assert finished


@pytest.mark.anyio
async def test_stream_task_completes_while_consumer_waits_on_empty_queue():
    """Regressão da race: task conclui entre task.done() e queue.get()."""
    bus = EventBus()
    provider = GatedProvider(tokens=["o", "k"])
    finished: list[dict] = []
    bus.subscribe(EventType.agent_finished, lambda e: finished.append(e.payload))
    agent = _agent(bus, provider)

    async def run():
        collected: list[EventType] = []
        async for event in agent.chat_stream("oi"):
            collected.append(event.type)
        return collected

    consumer = asyncio.create_task(run())
    # Garante que o token já foi consumido e a fila pode estar vazia.
    await asyncio.wait_for(provider.consumed_first_token.wait(), timeout=5)
    await asyncio.sleep(0.05)
    provider.release.set()

    types = await asyncio.wait_for(consumer, timeout=5)

    assert EventType.assistant_message in types
    assert finished


@pytest.mark.anyio
async def test_stream_drains_burst_events_after_task_done():
    """Task conclui em rajada; eventos remanescentes não são perdidos."""
    bus = EventBus()
    tokens = [f"t{i}" for i in range(300)]
    agent = _agent(bus, BurstProvider(tokens))

    token_count = 0
    async for event in agent.chat_stream("oi"):
        if event.type is EventType.token_stream:
            token_count += 1

    assert token_count == len(tokens)


@pytest.mark.anyio
async def test_stream_propagates_task_exception_and_emits_agent_failed():
    """Exceção da task é propagada e gera agent_failed (sem hang)."""
    bus = EventBus()
    provider = FailingProvider()
    failed: list[dict] = []

    def _on_failed(event):
        failed.append(event.payload)

    bus.subscribe(EventType.agent_failed, _on_failed)
    agent = _agent(bus, provider)

    async def run():
        async for _ in agent.chat_stream("oi"):
            pass

    consumer = asyncio.create_task(run())
    await asyncio.wait_for(provider.consumed_first_token.wait(), timeout=5)
    provider.fail_now.set()

    with pytest.raises(RuntimeError, match="modelo explodiu"):
        await asyncio.wait_for(consumer, timeout=5)

    assert failed
    assert "modelo explodiu" in str(failed[0].get("error", ""))


@pytest.mark.anyio
async def test_stream_cancellation_propagates_and_emits_agent_cancelled():
    """Cancelamento do consumidor propaga e gera agent_cancelled."""
    bus = EventBus()
    provider = GatedProvider()  # nunca liberado de propósito
    cancelled: list[dict] = []

    def _on_cancelled(event):
        cancelled.append(event.payload)

    bus.subscribe(EventType.agent_cancelled, _on_cancelled)
    agent = _agent(bus, provider)

    async def run():
        async for _ in agent.chat_stream("oi"):
            pass

    consumer = asyncio.create_task(run())
    await asyncio.wait_for(provider.consumed_first_token.wait(), timeout=5)
    consumer.cancel()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(consumer, timeout=5)

    assert cancelled


@pytest.mark.anyio
async def test_stream_task_completed_before_any_consumption():
    """Task conclui antes do consumidor drenar: eventos ainda são entregues."""
    bus = EventBus()
    finished: list[dict] = []
    bus.subscribe(EventType.agent_finished, lambda e: finished.append(e.payload))
    agent = _agent(bus, BurstProvider(["x", "y"]))

    got_assistant = False
    async for event in agent.chat_stream("oi"):
        if event.type is EventType.assistant_message:
            got_assistant = True

    assert got_assistant
    assert finished


@pytest.mark.anyio
async def test_stream_queue_empty_does_not_hang():
    """Sem eventos na fila e task ainda rodando, o stream aguarda sem travar."""
    bus = EventBus()
    provider = GatedProvider(tokens=["único"])
    agent = _agent(bus, provider)

    async def run():
        count = 0
        async for event in agent.chat_stream("oi"):
            if event.type is EventType.token_stream:
                count += 1
            if event.type is EventType.agent_finished:
                break
        return count

    consumer = asyncio.create_task(run())
    await asyncio.wait_for(provider.consumed_first_token.wait(), timeout=5)
    await asyncio.sleep(0.05)
    provider.release.set()

    count = await asyncio.wait_for(consumer, timeout=5)
    assert count == 1