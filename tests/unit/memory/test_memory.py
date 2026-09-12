from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from app.memory.service import MemoryService
from app.memory.types import MemoryType
from app.skills.memory.tools.save import MemorySaveTool


class FakeEmbeddingProvider:
    async def embed(self, text: str) -> list[float]:
        tokens = {token.lower() for token in text.split()}
        return [float(len(tokens)), float(sum(map(len, tokens)) or 1)]


@dataclass
class FakeMemory:
    id: str
    content: str
    memory_type: str
    source: str
    importance: float
    confidence: float
    embedding: list[float] | None
    metadata_: dict
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expiration: datetime | None = None


class FakeRepository:
    def __init__(self) -> None:
        self.items: list[FakeMemory] = []

    async def save(self, memory):
        self.items.append(memory)
        return memory

    async def list(self, limit: int = 100, memory_type: str | None = None):
        items = [item for item in self.items if memory_type is None or item.memory_type == memory_type]
        now = datetime.now(UTC)
        return [item for item in items if item.expiration is None or item.expiration > now][:limit]

    async def get(self, memory_id: str):
        return next((item for item in self.items if item.id == memory_id), None)

    async def delete(self, memory_id: str):
        self.items = [item for item in self.items if item.id != memory_id]

    async def search(self, query, embedding=None, *, limit=5, min_score=0.0, memory_types=None, context=None):
        query_tokens = {token.lower() for token in query.split()}
        now = datetime.now(UTC)
        candidates = [
            item for item in self.items
            if (memory_types is None or item.memory_type in memory_types)
            and (item.expiration is None or item.expiration > now)
        ]
        scored = []
        for item in candidates:
            content_tokens = {token.lower() for token in item.content.split()}
            overlap = len(query_tokens & content_tokens) / max(1, len(query_tokens))
            score = 0.7 * overlap + 0.3 * item.importance
            if score >= min_score:
                scored.append((item, score))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return [item for item, _ in scored[:limit]]

    async def purge_expired(self):
        before = len(self.items)
        now = datetime.now(UTC)
        self.items = [item for item in self.items if item.expiration is None or item.expiration > now]
        return before - len(self.items)


@pytest.mark.anyio
async def test_creation_contains_required_memory_fields():
    repository = FakeRepository()
    service = MemoryService(repository, FakeEmbeddingProvider())
    saved = await service.save_semantic("Meu projeto usa PostgreSQL.", importance=0.9, confidence=0.8)

    assert saved is not None
    assert saved.memory_type == MemoryType.SEMANTIC.value
    assert saved.source == "semantic"
    assert saved.importance == 0.9
    assert saved.confidence == 0.8
    assert saved.created_at
    assert saved.updated_at
    assert saved.metadata == {}
    assert saved.expiration is None


@pytest.mark.anyio
async def test_memory_respects_min_importance():
    service = MemoryService(FakeRepository(), FakeEmbeddingProvider())
    saved = await service.save_semantic("oi", importance=0.69)
    assert saved is None


@pytest.mark.anyio
async def test_working_memory_is_transient_and_not_persisted():
    repository = FakeRepository()
    service = MemoryService(repository, FakeEmbeddingProvider())
    saved = await service.save_working("exec-1", "usuário está no fluxo de login")

    assert saved is not None
    assert saved.memory_type == MemoryType.WORKING.value
    assert repository.items == []
    assert service.get_working("exec-1")[0].content.startswith("usuário")


@pytest.mark.anyio
async def test_working_memory_expiration():
    service = MemoryService(FakeRepository(), FakeEmbeddingProvider())
    saved = await service.save_working(
        "exec-1", "contexto temporário", expiration=datetime.now(UTC) - timedelta(seconds=1)
    )
    assert saved is not None
    assert service.get_working("exec-1") == []


@pytest.mark.anyio
async def test_episodic_memory_skips_trivial_chat():
    repository = FakeRepository()
    service = MemoryService(repository, FakeEmbeddingProvider())
    saved = await service.save_episode("oi", "olá")
    assert saved is None
    assert repository.items == []


@pytest.mark.anyio
async def test_episodic_memory_keeps_important_tool_event():
    service = MemoryService(FakeRepository(), FakeEmbeddingProvider())
    saved = await service.save_episode("abra o GitHub", "ok", ["open_url", "verify_screen"])
    assert saved is not None
    assert saved.memory_type == MemoryType.EPISODIC.value
    assert saved.importance == 0.85
    assert saved.metadata["tools"] == ["open_url", "verify_screen"]


@pytest.mark.anyio
async def test_preference_is_persistent_and_conflicts_by_key():
    repository = FakeRepository()
    service = MemoryService(repository, FakeEmbeddingProvider())
    first = await service.save_preference(
        "Prefiro abrir o Discord no monitor 1",
        metadata={"preference_key": "discord.monitor"},
    )
    second = await service.save_preference(
        "Prefiro abrir o Discord no monitor 2",
        metadata={"preference_key": "discord.monitor"},
    )

    assert first is not None and second is not None
    assert second.importance == 1.0
    assert len(repository.items) == 1
    assert repository.items[0].content.endswith("monitor 2")


@pytest.mark.anyio
async def test_semantic_search_uses_relevance_and_ignores_irrelevant_memory():
    repository = FakeRepository()
    service = MemoryService(repository, FakeEmbeddingProvider())
    await service.save_semantic("O projeto ALPHA usa Python e SQLite", importance=0.9)
    await service.save_semantic("O usuário gosta de jogos de corrida", importance=0.9)

    results = await service.search_memories("projeto ALPHA Python", limit=5, min_score=0.45)
    contents = " | ".join(item.content for item in results)
    assert "ALPHA" in contents
    assert "jogos de corrida" not in contents


@pytest.mark.anyio
async def test_expired_persistent_memory_is_not_recovered():
    repository = FakeRepository()
    service = MemoryService(repository, FakeEmbeddingProvider())
    await service.save_semantic(
        "token temporário do projeto",
        importance=1.0,
        metadata={"kind": "temporary"},
    )
    repository.items[0].expiration = datetime.now(UTC) - timedelta(seconds=1)

    results = await service.search_memories("token projeto", min_score=0.1)
    assert results == []


@pytest.mark.anyio
async def test_explicit_memory_save_remains_above_threshold():
    repository = FakeRepository()
    service = MemoryService(repository, FakeEmbeddingProvider())
    tool = MemorySaveTool(service)
    result = await tool.execute(content="meu perfil do github é https://github.com/okohii")

    assert result.success
    assert result.data["importance"] == 1.0
    assert len(repository.items) == 1


@pytest.mark.anyio
async def test_memory_save_tool_rejects_empty_content():
    service = MemoryService(FakeRepository(), FakeEmbeddingProvider())
    result = await MemorySaveTool(service).execute(content="   ")
    assert not result.success
    assert "conteúdo" in result.error
