from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.core.config import get_settings
from app.db.models import Memory as MemoryModel
from app.memory.embeddings import EmbeddingProvider
from app.memory.episode import build_episode_memory, detect_kind
from app.memory.repository import MemoryRepository


@dataclass(slots=True)
class MemoryItem:
    id: str
    content: str
    memory_type: str
    source: str
    importance: float
    embedding: list[float] | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    def model_dump(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "memory_type": self.memory_type,
            "source": self.source,
            "importance": self.importance,
            "embedding": self.embedding,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class MemoryService:
    def __init__(self, repository: MemoryRepository, embedding_provider: EmbeddingProvider) -> None:
        self.repository = repository
        self.embedding_provider = embedding_provider
        self.settings = get_settings()

    def score_importance(self, content: str) -> float:
        keywords = ["projeto", "prefer", "importante", "lembre", "memorize", "regra"]
        score = 0.15
        lowered = content.lower()
        if any(keyword in lowered for keyword in keywords):
            score += 0.5
        if len(content) > 120:
            score += 0.2
        if "memorize que" in lowered:
            score = 1.0
        return min(score, 1.0)

    async def save_memory(
        self,
        content: str,
        memory_type: str = "semantic",
        source: str = "chat",
        importance: float | None = None,
        metadata: dict[str, Any] | None = None,
        persist_if_relevant: bool = True,
    ) -> MemoryItem | None:
        resolved_importance = (
            importance if importance is not None else self.score_importance(content)
        )
        if persist_if_relevant and resolved_importance < self.settings.memory_min_importance:
            return None
        embedding = await self.embedding_provider.embed(content)
        row = MemoryModel(
            id=str(uuid4()),
            content=content,
            memory_type=memory_type,
            source=source,
            importance=resolved_importance,
            embedding=embedding,
            metadata_=metadata or {},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        saved = await self.repository.save(row)
        return self._to_item(saved)

    async def save_episode(
        self,
        user_message: str,
        response: str,
        tool_names: list[str] | None = None,
    ) -> MemoryItem | None:
        """Grava o episódio de um turno de conversa.

        Preferências (ex.: "sempre abra o Discord no monitor 2") são guardadas com
        importância máxima e recebem o tipo "preferencia". Episódios que usaram
        ferramentas são guardados com importância alta; conversas corriqueiras ficam
        abaixo do limiar e são descartadas.
        """
        memory_type = detect_kind(user_message or "")
        tool_names = tool_names or []
        if memory_type == "perfil":
            return await self.save_profile(user_message.strip())
        if memory_type == "preferencia":
            importance = 1.0
        elif tool_names:
            importance = 0.75
        else:
            importance = 0.4
        content = build_episode_memory(user_message or "", response or "", tool_names)
        return await self.save_memory(
            content,
            memory_type=memory_type,
            source="agent",
            importance=importance,
            metadata={"kind": memory_type, "episode": True},
        )

    async def list_memories(self, limit: int = 100) -> list[MemoryItem]:
        memories = await self.repository.list(limit=limit)
        return [self._to_item(memory) for memory in memories]

    async def save_profile(self, content: str) -> MemoryItem | None:
        """Grava um fato estável sobre o usuário (identidade, ambiente, preferências duradouras).

        Perfis têm memória_type 'perfil' e importância máxima; são sempre
        injetados no contexto do agente, independente da consulta atual.
        """
        return await self.save_memory(
            content=content,
            memory_type="perfil",
            source="profile",
            importance=1.0,
            metadata={"kind": "perfil", "profile": True},
        )

    async def load_profile(self, limit: int = 50) -> list[MemoryItem]:
        """Retorna os registros de perfil (identidade do usuário e do agente)."""
        memories = await self.repository.list(limit=limit)
        profile = [
            self._to_item(memory)
            for memory in memories
            if memory.memory_type == "perfil" or (memory.metadata_ or {}).get("profile")
        ]
        return profile[:limit]

    async def search_memories(self, query: str, limit: int = 5) -> list[MemoryItem]:
        embedding = await self.embedding_provider.embed(query)
        memories = await self.repository.search_by_embedding(
            embedding, limit=limit, keyword=query
        )
        return [self._to_item(memory) for memory in memories]

    async def delete_memory(self, memory_id: str) -> None:
        await self.repository.delete(memory_id)

    def _to_item(self, memory: MemoryModel) -> MemoryItem:
        return MemoryItem(
            id=memory.id,
            content=memory.content,
            memory_type=memory.memory_type,
            source=memory.source,
            importance=memory.importance,
            embedding=memory.embedding,
            metadata=dict(memory.metadata_ or {}),
            created_at=memory.created_at,
            updated_at=memory.updated_at,
        )
