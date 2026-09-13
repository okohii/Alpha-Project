from __future__ import annotations

import logging
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Memory as MemoryModel
from app.memory.policies import is_expired, retrieval_score

_TOKEN_RE = re.compile(r"[a-zA-Z\u00C0-\u017F0-9]+")


class MemoryRepositoryProtocol(Protocol):
    """Backend-neutral memory contract used by MemoryService/Agent.

    Interface, nunca implementação: ``SqliteMemoryRepository`` (abaixo) é a
    implementação concreta. O alias antigo ``MemoryRepository`` foi removido
    (Parte 43) para impedir confundir Protocol com classe concreta.
    """

    async def list(self, limit: int = 100, memory_type: str | None = None) -> list[Any]: ...
    async def get(self, memory_id: str) -> Any | None: ...
    async def save(self, memory: Any) -> Any: ...
    async def delete(self, memory_id: str) -> None: ...
    async def search(
        self,
        query: str,
        embedding: Sequence[float] | None = None,
        *,
        limit: int = 5,
        min_score: float = 0.0,
        memory_types: Sequence[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> list[Any]: ...
    async def purge_expired(self) -> int: ...


def cosine_similarity(a: Sequence[float] | None, b: Sequence[float] | None) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a)) or 1.0
    norm_b = math.sqrt(sum(y * y for y in b)) or 1.0
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))


def keyword_overlap_score(query: str, content: str) -> float:
    if not query or not content:
        return 0.0
    query_tokens = set(_TOKEN_RE.findall(query.lower()))
    content_tokens = set(_TOKEN_RE.findall(content.lower()))
    if not query_tokens or not content_tokens:
        return 0.0
    return len(query_tokens & content_tokens) / math.sqrt(len(query_tokens) * len(content_tokens))


def hybrid_score(
    query: str,
    content: str,
    query_embedding: Sequence[float] | None,
    memory_embedding: Sequence[float] | None,
) -> float:
    return 0.55 * cosine_similarity(query_embedding, memory_embedding) + 0.45 * keyword_overlap_score(query, content)


@dataclass(slots=True)
class MemoryRecord:
    id: str
    content: str
    memory_type: str
    source: str
    importance: float
    confidence: float
    embedding: list[float] | None
    metadata: dict[str, Any]
    created_at: object
    updated_at: object
    expiration: object | None


class SqliteMemoryRepository:
    """SQLAlchemy/SQLite implementation of the backend-neutral MemoryRepository.

    PostgreSQL remains supported through the same SQLAlchemy adapter. A future
    MongoDB implementation only needs to satisfy MemoryRepository; Agent and
    MemoryService do not need to change.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = logging.getLogger("app.memory.repository")

    async def list(self, limit: int = 100, memory_type: str | None = None) -> list[MemoryModel]:
        try:
            now = datetime.now(UTC)
            stmt = select(MemoryModel).where(
                MemoryModel.expiration.is_(None) | (MemoryModel.expiration > now)
            )
            if memory_type:
                stmt = stmt.where(MemoryModel.memory_type == memory_type)
            result = await self.session.execute(
                stmt.order_by(MemoryModel.created_at.desc()).limit(limit)
            )
            return list(result.scalars().all())
        except SQLAlchemyError as exc:
            self.logger.debug("DB list error: %s", exc)
            return []

    async def get(self, memory_id: str) -> MemoryModel | None:
        try:
            memory = await self.session.get(MemoryModel, memory_id)
            if memory is None or is_expired(memory.expiration):
                return None
            return memory
        except SQLAlchemyError:
            return None

    async def save(self, memory: MemoryModel) -> MemoryModel:
        try:
            self.session.add(memory)
            await self.session.commit()
            await self.session.refresh(memory)
            return memory
        except SQLAlchemyError as exc:
            await self.session.rollback()
            self.logger.debug("DB save error: %s", exc)
            raise

    async def delete(self, memory_id: str) -> None:
        try:
            await self.session.execute(delete(MemoryModel).where(MemoryModel.id == memory_id))
            await self.session.commit()
        except SQLAlchemyError as exc:
            await self.session.rollback()
            self.logger.debug("DB delete error: %s", exc)
            raise

    async def search(
        self,
        query: str,
        embedding: Sequence[float] | None = None,
        *,
        limit: int = 5,
        min_score: float = 0.0,
        memory_types: Sequence[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> list[MemoryModel]:
        now = datetime.now(UTC)
        try:
            stmt = select(MemoryModel).where(
                MemoryModel.expiration.is_(None) | (MemoryModel.expiration > now)
            )
            if memory_types:
                stmt = stmt.where(MemoryModel.memory_type.in_(list(memory_types)))
            result = await self.session.execute(
                stmt.order_by(MemoryModel.created_at.desc()).limit(500)
            )
            candidates = list(result.scalars().all())
        except SQLAlchemyError as exc:
            self.logger.debug("DB search error: %s", exc)
            return []

        context = context or {}
        scored: list[tuple[MemoryModel, float]] = []
        for memory in candidates:
            similarity = hybrid_score(query, memory.content, embedding, memory.embedding)
            lexical = keyword_overlap_score(query, memory.content)
            context_score = 1.0 if context and any(
                str(value).lower() in memory.content.lower()
                for value in context.values()
                if value
            ) else lexical
            score = retrieval_score(
                similarity,
                memory.importance,
                memory.created_at,
                memory.memory_type,
                context_score=context_score,
                now=now,
            )
            # min_score é o corte de RELEVÂNCIA: memória sem relevância não
            # passa mesmo sendo importante/recorrerte (piso de importância não
            # contamina o filtro). Ranking continua pelo score composto.
            relevance = max(0.0, min(1.0, similarity))
            if relevance >= min_score:
                scored.append((memory, score))

        scored.sort(key=lambda pair: pair[1], reverse=True)
        return [memory for memory, _ in scored[:limit]]

    async def search_by_embedding(
        self,
        embedding: Sequence[float],
        limit: int = 5,
        keyword: str | None = None,
        min_score: float = 0.0,
    ) -> list[MemoryModel]:
        return await self.search(keyword or "", embedding, limit=limit, min_score=min_score)

    async def purge_expired(self) -> int:
        try:
            result = await self.session.execute(
                delete(MemoryModel).where(
                    MemoryModel.expiration.is_not(None),
                    MemoryModel.expiration <= datetime.now(UTC),
                )
            )
            await self.session.commit()
            return int(result.rowcount or 0)
        except SQLAlchemyError as exc:
            await self.session.rollback()
            self.logger.debug("DB expiration cleanup error: %s", exc)
            return 0


__all__ = [
    "MemoryRecord",
    "MemoryRepositoryProtocol",
    "SqliteMemoryRepository",
    "cosine_similarity",
    "hybrid_score",
    "keyword_overlap_score",
]
