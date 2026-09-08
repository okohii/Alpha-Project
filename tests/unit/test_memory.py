from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

from app.memory.service import MemoryService


class FakeEmbeddingProvider:
    async def embed(self, text: str) -> list[float]:
        return [float(len(text))]


@dataclass
class FakeMemory:
    id: str
    content: str
    memory_type: str
    source: str
    importance: float
    embedding: list[float] | None
    metadata_: dict
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class FakeRepository:
    def __init__(self) -> None:
        self.items: list[FakeMemory] = []

    async def save(self, memory):
        self.items.append(memory)
        return memory

    async def list(self, limit: int = 100):
        return list(self.items[:limit])

    async def search_by_embedding(self, embedding, limit: int = 5):
        return list(self.items[:limit])

    async def delete(self, memory_id: str):
        self.items = [item for item in self.items if item.id != memory_id]


@pytest.mark.anyio
async def test_memory_service_saves_explicit_memory():
    service = MemoryService(FakeRepository(), FakeEmbeddingProvider())
    saved = await service.save_memory("Meu projeto usa PostgreSQL.", importance=1.0)

    assert saved is not None
    assert saved.content == "Meu projeto usa PostgreSQL."
    assert saved.embedding == [27.0]


@pytest.mark.anyio
async def test_memory_service_skips_low_importance_by_default():
    service = MemoryService(FakeRepository(), FakeEmbeddingProvider())
    saved = await service.save_memory("Oi.")

    assert saved is None


@pytest.mark.anyio
async def test_memory_service_searches_memories():
    repository = FakeRepository()
    service = MemoryService(repository, FakeEmbeddingProvider())
    await service.save_memory("Meu projeto usa PostgreSQL.", importance=1.0)
    results = await service.search_memories("PostgreSQL")

    assert len(results) == 1
    assert results[0].content.startswith("Meu projeto")
