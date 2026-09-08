from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from app.memory.episode import build_episode_memory, detect_kind
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
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


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


def test_detect_kind_tags_preference():
    assert detect_kind("sempre abro o valorant no monitor 2") == "preferencia"


def test_detect_kind_tags_procedure():
    assert detect_kind("sempre que eu abrir o pc, execute a rotina") == "procedimento"


def test_detect_kind_fallback_semantic():
    assert detect_kind("qual é a capital do rj?") == "semantic"


def test_build_episode_memory_compact():
    episode = build_episode_memory(
        "abra o site do github", "site aberto no chrome", ["open_url"]
    )
    assert "abra o site do github" in episode
    assert "open_url" in episode
    assert "site aberto no chrome" not in episode


def test_build_episode_memory_never_stores_model_response():
    episode = build_episode_memory(
        "abra o linkedin",
        "Você é uma pessoa, não entendeu? na verdade fui eu que abri",
        ["open_url"],
    )
    assert "fui eu que abri" not in episode
    assert "resultado" not in episode


@pytest.mark.anyio
async def test_save_episode_stores_preference_at_max_importance():
    service = MemoryService(FakeRepository(), FakeEmbeddingProvider())
    saved = await service.save_episode("sempre abra o discord no monitor 2", "ok, anotado")

    assert saved is not None
    assert saved.memory_type == "preferencia"
    assert saved.importance == 1.0
    assert saved.source == "agent"
    assert saved.metadata["episode"] is True


@pytest.mark.anyio
async def test_save_episode_keeps_tool_turns_above_threshold():
    service = MemoryService(FakeRepository(), FakeEmbeddingProvider())
    saved = await service.save_episode(
        "abra o valorant", "abri no monitor 1", ["open_app", "verify_screen"]
    )

    assert saved is not None
    assert saved.memory_type == "semantic"
    assert saved.importance == 0.75


@pytest.mark.anyio
async def test_save_episode_discards_trivial_chitchat():
    repository = FakeRepository()
    service = MemoryService(repository, FakeEmbeddingProvider())
    saved = await service.save_episode("oi", "olá! como posso ajudar?")

    assert saved is None
    assert repository.items == []