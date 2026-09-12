from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.memory.service import MemoryService


class FakeRepository:
    def __init__(self):
        self.rows = []

    async def list(self, limit=100, memory_type=None):
        rows = [row for row in self.rows if memory_type is None or row.memory_type == memory_type]
        return rows[:limit]

    async def get(self, memory_id):
        return next((row for row in self.rows if row.id == memory_id), None)

    async def save(self, memory):
        self.rows.append(memory)
        return memory

    async def delete(self, memory_id):
        self.rows = [row for row in self.rows if row.id != memory_id]

    async def search(self, *args, **kwargs):
        return []

    async def purge_expired(self):
        return 0


class FakeEmbedding:
    async def embed(self, text):
        return [1.0, 0.0]


@pytest.mark.anyio
async def test_working_memory_is_bounded_per_context(monkeypatch):
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "memory_working_max_items", 3)
    monkeypatch.setattr(settings, "memory_working_max_contexts", 2)

    service = MemoryService(FakeRepository(), FakeEmbedding())
    for index in range(5):
        await service.save_working("session-a", f"step {index}")

    assert [item.content for item in service.get_working("session-a")] == ["step 2", "step 3", "step 4"]
    assert service.working_stats() == {"contexts": 1, "items": 3}


@pytest.mark.anyio
async def test_old_working_contexts_are_evicted_from_ram(monkeypatch):
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "memory_working_max_contexts", 2)

    service = MemoryService(FakeRepository(), FakeEmbedding())
    await service.save_working("a", "A")
    await service.save_working("b", "B")
    await service.save_working("c", "C")

    assert service.get_working("a") == []
    assert service.working_stats()["contexts"] == 2


@pytest.mark.anyio
async def test_low_importance_chat_is_not_persisted(monkeypatch):
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "memory_min_importance", 0.70)

    repository = FakeRepository()
    service = MemoryService(repository, FakeEmbedding())
    saved = await service.save_memory("oi tudo bem", memory_type="semantic", importance=0.10)

    assert saved is None
    assert repository.rows == []


@pytest.mark.anyio
async def test_explicit_preference_replaces_same_preference_key():
    repository = FakeRepository()
    service = MemoryService(repository, FakeEmbedding())

    first = await service.save_preference("Minha preferência é resposta curta", metadata={"preference_key": "response_style"})
    second = await service.save_preference("Minha preferência é resposta detalhada", metadata={"preference_key": "response_style"})

    assert first is not None
    assert second is not None
    assert len(repository.rows) == 1
    assert repository.rows[0].content == "Minha preferência é resposta detalhada"
