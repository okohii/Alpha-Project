from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence
from uuid import uuid4

from app.core.config import get_settings
from app.db.models import Memory as MemoryModel
from app.memory.embeddings import EmbeddingProvider
from app.memory.episode import build_episode_memory, detect_kind
from app.memory.policies import is_expired, preference_key, utcnow
from app.memory.repository import MemoryRepositoryProtocol
from app.memory.types import MemoryType


@dataclass(slots=True)
class MemoryItem:
    id: str
    content: str
    memory_type: str
    source: str
    importance: float
    confidence: float
    embedding: list[float] | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    expiration: datetime | None

    def model_dump(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "memory_type": self.memory_type,
            "type": self.memory_type,
            "source": self.source,
            "importance": self.importance,
            "confidence": self.confidence,
            "embedding": self.embedding,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "expiration": self.expiration.isoformat() if self.expiration else None,
        }


class MemoryService:
    """Orquestra memória sem acoplar Agent ao backend.

    Working memory é transitória e fica em RAM. Ela é limitada por contexto e
    pelo número máximo de contextos ativos; memória persistente passa pelo
    repositório (SQLite hoje) e só é carregada sob demanda.
    """

    def __init__(self, repository: MemoryRepositoryProtocol, embedding_provider: EmbeddingProvider) -> None:
        self.repository = repository
        self.embedding_provider = embedding_provider
        self.settings = get_settings()
        # OrderedDict permite LRU de contextos sem deixar conversas antigas
        # ocuparem RAM indefinidamente. Os itens de cada contexto também são
        # limitados por memory_working_max_items.
        self._working: OrderedDict[str, list[MemoryItem]] = OrderedDict()

    def score_importance(self, content: str) -> float:
        text = (content or "").strip().lower()
        if not text:
            return 0.0
        score = 0.10
        markers = ("projeto", "importante", "lembre", "memorize", "regra", "prefer", "sempre", "nunca")
        if any(marker in text for marker in markers):
            score += 0.50
        if len(text) > 120:
            score += 0.15
        if any(marker in text for marker in ("memorize que", "lembre que", "minha preferência", "minha preferencia")):
            score = 1.0
        return min(1.0, score)

    def _resolve_type(self, memory_type: str | None, content: str) -> str:
        raw = (memory_type or "").strip().lower()
        aliases = {
            "episodic": MemoryType.EPISODIC.value,
            "episode": MemoryType.EPISODIC.value,
            "semantic": MemoryType.SEMANTIC.value,
            "preference": MemoryType.PREFERENCE.value,
            "preferencia": MemoryType.PREFERENCE.value,
            "working": MemoryType.WORKING.value,
            "perfil": MemoryType.SEMANTIC.value,
            "procedimento": MemoryType.SEMANTIC.value,
        }
        if raw in aliases:
            return aliases[raw]
        return MemoryType.PREFERENCE.value if detect_kind(content) == "preferencia" else MemoryType.SEMANTIC.value

    def _touch_working_context(self, context_id: str) -> list[MemoryItem]:
        bucket = self._working.pop(context_id, None)
        if bucket is None:
            bucket = []
        self._working[context_id] = bucket
        max_contexts = max(1, self.settings.memory_working_max_contexts)
        while len(self._working) > max_contexts:
            self._working.popitem(last=False)
        return bucket

    async def save_memory(
        self,
        content: str,
        memory_type: str = "semantic",
        source: str = "chat",
        importance: float | None = None,
        confidence: float = 1.0,
        metadata: dict[str, Any] | None = None,
        expiration: datetime | None = None,
        persist_if_relevant: bool = True,
        context_id: str | None = None,
    ) -> MemoryItem | None:
        content = (content or "").strip()
        if not content:
            return None
        resolved_type = self._resolve_type(memory_type, content)
        resolved_importance = max(0.0, min(1.0, importance if importance is not None else self.score_importance(content)))
        confidence = max(0.0, min(1.0, confidence))

        if resolved_type == MemoryType.WORKING.value:
            context_key = context_id or "default"
            item = self._make_item(content, resolved_type, source, resolved_importance, confidence, metadata, expiration)
            bucket = self._touch_working_context(context_key)
            bucket.append(item)
            self._working[context_key] = bucket[-max(1, self.settings.memory_working_max_items):]
            return item

        if persist_if_relevant and resolved_importance < self.settings.memory_min_importance:
            return None
        if expiration is not None and is_expired(expiration):
            return None

        metadata = dict(metadata or {})
        if resolved_type == MemoryType.PREFERENCE.value:
            metadata.setdefault("preference_key", preference_key(content, metadata))
            resolved_importance = 1.0
            key = metadata["preference_key"]
            existing = await self.repository.list(limit=50, memory_type=MemoryType.PREFERENCE.value)
            for old in existing:
                if (old.metadata_ or {}).get("preference_key") == key:
                    await self.repository.delete(old.id)

        embedding = await self.embedding_provider.embed(content)
        now = utcnow()
        row = MemoryModel(
            id=str(uuid4()),
            content=content,
            memory_type=resolved_type,
            source=source,
            importance=resolved_importance,
            confidence=confidence,
            embedding=embedding,
            metadata_=metadata,
            created_at=now,
            updated_at=now,
            expiration=expiration,
        )
        saved = await self.repository.save(row)
        return self._to_item(saved)

    async def save_working(self, context_id: str, content: str, *, source: str = "runtime", importance: float = 1.0, confidence: float = 1.0, metadata: dict[str, Any] | None = None, expiration: datetime | None = None) -> MemoryItem | None:
        return await self.save_memory(content, MemoryType.WORKING.value, source, importance, confidence, metadata, expiration, persist_if_relevant=False, context_id=context_id)

    def get_working(self, context_id: str) -> list[MemoryItem]:
        now = utcnow()
        bucket = self._touch_working_context(context_id)
        bucket[:] = [item for item in bucket if not is_expired(item.expiration, now=now)]
        if not bucket:
            self._working.pop(context_id, None)
        return list(bucket)

    def clear_working(self, context_id: str) -> None:
        """Libera imediatamente as referências do contexto da RAM."""
        self._working.pop(context_id, None)

    def clear_all_working(self) -> None:
        """Libera todos os contextos de Working Memory."""
        self._working.clear()

    def working_stats(self) -> dict[str, int]:
        return {
            "contexts": len(self._working),
            "items": sum(len(items) for items in self._working.values()),
        }

    async def save_episode(self, user_message: str, response: str, tool_names: list[str] | None = None, *, confidence: float = 1.0, metadata: dict[str, Any] | None = None) -> MemoryItem | None:
        if detect_kind(user_message or "") == "preferencia":
            return await self.save_preference(user_message.strip(), source="agent", confidence=confidence, metadata=metadata)
        tools = tool_names or []
        importance = 0.85 if tools else self.score_importance(user_message)
        if importance < self.settings.memory_min_importance:
            return None
        content = build_episode_memory(user_message or "", response or "", tools)
        return await self.save_memory(content, MemoryType.EPISODIC.value, "agent", importance, confidence, {**(metadata or {}), "episode": True, "tools": tools})

    async def save_semantic(self, content: str, *, source: str = "semantic", importance: float | None = None, confidence: float = 1.0, metadata: dict[str, Any] | None = None) -> MemoryItem | None:
        return await self.save_memory(content, MemoryType.SEMANTIC.value, source, importance, confidence, metadata)

    async def save_preference(self, content: str, *, source: str = "explicit", confidence: float = 1.0, metadata: dict[str, Any] | None = None) -> MemoryItem | None:
        return await self.save_memory(content, MemoryType.PREFERENCE.value, source, 1.0, confidence, metadata)

    async def save_profile(self, content: str) -> MemoryItem | None:
        return await self.save_semantic(content, source="profile", importance=1.0, confidence=1.0, metadata={"profile": True})

    async def list_memories(self, limit: int = 100, memory_type: str | None = None) -> list[MemoryItem]:
        memories = await self.repository.list(limit=limit, memory_type=memory_type)
        return [self._to_item(memory) for memory in memories if not is_expired(memory.expiration)]

    async def load_profile(self, limit: int = 50) -> list[MemoryItem]:
        semantic = await self.repository.list(limit=limit, memory_type=MemoryType.SEMANTIC.value)
        preferences = await self.repository.list(limit=limit, memory_type=MemoryType.PREFERENCE.value)
        items = [self._to_item(m) for m in [*semantic, *preferences] if not is_expired(m.expiration)]
        items.sort(key=lambda item: (item.importance, item.updated_at), reverse=True)
        return items[:limit]

    async def search_memories(self, query: str, limit: int = 5, min_score: float | None = None, *, memory_types: Sequence[str] | None = None, context: dict[str, Any] | None = None) -> list[MemoryItem]:
        query = (query or "").strip()
        if not query:
            return []
        threshold = self.settings.memory_relevance_min_score if min_score is None else min_score
        embedding = await self.embedding_provider.embed(query)
        memories = await self.repository.search(query, embedding, limit=limit, min_score=threshold, memory_types=memory_types, context=context)
        return [self._to_item(memory) for memory in memories if not is_expired(memory.expiration)]

    async def purge_expired(self) -> int:
        return await self.repository.purge_expired()

    async def delete_memory(self, memory_id: str) -> None:
        await self.repository.delete(memory_id)

    def _make_item(self, content: str, memory_type: str, source: str, importance: float, confidence: float, metadata: dict[str, Any] | None, expiration: datetime | None) -> MemoryItem:
        now = utcnow()
        return MemoryItem(id=str(uuid4()), content=content, memory_type=memory_type, source=source, importance=importance, confidence=confidence, embedding=None, metadata=dict(metadata or {}), created_at=now, updated_at=now, expiration=expiration)

    def _to_item(self, memory: MemoryModel) -> MemoryItem:
        return MemoryItem(id=memory.id, content=memory.content, memory_type=memory.memory_type, source=memory.source, importance=memory.importance, confidence=memory.confidence, embedding=memory.embedding, metadata=dict(memory.metadata_ or {}), created_at=memory.created_at, updated_at=memory.updated_at, expiration=memory.expiration)
