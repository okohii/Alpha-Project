"""Grounding de memória: busca separada da decisão.

Garante que memórias irrelevantes NÃO viram contexto operacional do agente e
que memória recuperada nunca é tratada como instrução de ação.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.agent.agent import AgentCore
from app.llm.base import LLMResponse
from app.llm.router import LLMRouter
from app.memory.embeddings import LocalEmbeddingProvider
from app.memory.repository import MemoryRepository
from app.memory.service import MemoryService
from app.tools.registry import ToolRegistry


class FakeRow:
    def __init__(self, content: str, embedding) -> None:
        self.id = str(uuid.uuid4())
        self.content = content
        self.memory_type = "semantic"
        self.source = "test"
        self.importance = 1.0
        self.confidence = 1.0
        self.embedding = embedding
        self.metadata_ = {}
        self.created_at = datetime.now(UTC)
        self.updated_at = datetime.now(UTC)
        self.expiration = None


class _Scalars:
    def __init__(self, rows) -> None:
        self._rows = rows

    def all(self):
        return self._rows


class _Result:
    def __init__(self, rows) -> None:
        self._rows = rows

    def scalars(self):
        return _Scalars(self._rows)


class FakeSession:
    def __init__(self, rows) -> None:
        self.rows = rows

    async def execute(self, stmt):
        return _Result(self.rows)


MEMORY_ROWS = [
    "Ellen é amiga do usuário.",
    "Usuário gosta de determinado clima.",
    "Usuário quer abrir WhatsApp.",
    "Psyche.",
    "Ellen.",
]


@pytest.mark.anyio
async def test_repository_filters_irrelevant_memories():
    provider = LocalEmbeddingProvider()
    rows = [FakeRow(content, await provider.embed(content)) for content in MEMORY_ROWS]
    repo = MemoryRepository(FakeSession(rows))
    query_embedding = await provider.embed("Quem é Ellen?")

    results = await repo.search_by_embedding(
        query_embedding, limit=10, keyword="Quem é Ellen?", min_score=0.15
    )

    contents = [row.content for row in results]
    assert any("Ellen" in content for content in contents)
    assert "WhatsApp" not in "\n".join(contents)
    assert "clima" not in "\n".join(contents).lower()
    assert "Psyche" not in "\n".join(contents)


@pytest.mark.anyio
async def test_service_passes_min_score_through():
    provider = LocalEmbeddingProvider()
    rows = [FakeRow(content, await provider.embed(content)) for content in MEMORY_ROWS]
    service = MemoryService(MemoryRepository(FakeSession(rows)), provider)

    results = await service.search_memories("Quem é Ellen?", limit=10, min_score=0.15)

    contents = " | ".join(item.content for item in results)
    assert "Ellen" in contents
    assert "WhatsApp" not in contents
    assert "clima" not in contents


@pytest.mark.anyio
async def test_agent_memory_context_only_relevant():
    """O contexto injetado contém apenas memórias relevantes a Ellen."""
    seen_messages: list[list] = []

    class CapturingProvider:
        async def complete(self, messages, tools=None, temperature=0.2):
            seen_messages.append(list(messages))
            return LLMResponse(content="Ellen é uma amiga do usuário.")

    provider = LocalEmbeddingProvider()
    rows = [FakeRow(content, await provider.embed(content)) for content in MEMORY_ROWS]

    class GroundedService:
        async def search_memories(self, query, limit=5, min_score=0.0):
            assert min_score > 0
            results = await MemoryRepository(FakeSession(rows)).search_by_embedding(
                await provider.embed(query), limit=limit, keyword=query, min_score=min_score
            )
            return results

        async def load_profile(self, limit=50):
            return []

        async def save_episode(self, user_message, response, tool_names=None):
            return None

    agent = AgentCore(
        llm_router=LLMRouter(
            local_provider=CapturingProvider(), cloud_provider=CapturingProvider()
        ),
        tool_registry=ToolRegistry(tools={}),
        memory_service=GroundedService(),
    )
    agent.settings.memory_relevance_min_score = 0.15

    await agent.chat("Quem é Ellen?")

    system_texts = [m.content for m in seen_messages[0] if m.role == "system"]
    memory_block = next(
        (text for text in system_texts if "Registros de conversas anteriores" in text), ""
    )
    assert memory_block != ""
    assert "NÃO são ações executadas" in memory_block
    assert "Ellen é amiga" in memory_block or "Ellen." in memory_block
    assert "WhatsApp" not in memory_block
    assert "clima" not in memory_block
    assert "Psyche" not in memory_block
