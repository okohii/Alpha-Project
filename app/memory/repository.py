from __future__ import annotations

import logging
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Memory as MemoryModel

_TOKEN_RE = re.compile(r"[a-zA-Z\u00C0-\u017F0-9]+")


def cosine_similarity(a: Sequence[float] | None, b: Sequence[float] | None) -> float:
    """Cosseno entre dois vetores; 0.0 se algum deles for inválido/vazio."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a)) or 1.0
    norm_b = math.sqrt(sum(y * y for y in b)) or 1.0
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))


def keyword_overlap_score(query: str, content: str) -> float:
    """Similaridade léxica simples entre consulta e conteúdo (0..1)."""
    if not query or not content:
        return 0.0
    query_tokens = set(_TOKEN_RE.findall(query.lower()))
    content_tokens = set(_TOKEN_RE.findall(content.lower()))
    if not query_tokens or not content_tokens:
        return 0.0
    intersection = len(query_tokens & content_tokens)
    return intersection / math.sqrt(len(query_tokens) * len(content_tokens))


def hybrid_score(
    query: str,
    content: str,
    query_embedding: Sequence[float] | None,
    memory_embedding: Sequence[float] | None,
    *,
    embedding_weight: float = 0.55,
    keyword_weight: float = 0.45,
) -> float:
    """Combina similaridade de embedding e léxica em uma nota única (0..1)."""
    cosine = cosine_similarity(query_embedding, memory_embedding)
    lexical = keyword_overlap_score(query, content)
    return embedding_weight * cosine + keyword_weight * lexical


@dataclass(slots=True)
class MemoryRecord:
    id: str
    content: str
    memory_type: str
    source: str
    importance: float
    embedding: list[float] | None
    metadata: dict
    created_at: object
    updated_at: object


class MemoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = logging.getLogger("app.memory.repository")

    async def list(self, limit: int = 100) -> list[MemoryModel]:
        try:
            result = await self.session.execute(
                select(MemoryModel).order_by(MemoryModel.created_at.desc()).limit(limit)
            )
            return list(result.scalars().all())
        except SQLAlchemyError as exc:
            self.logger.debug("DB list error, returning empty list: %s", exc)
            return []

    async def get(self, memory_id: str) -> MemoryModel | None:
        try:
            return await self.session.get(MemoryModel, memory_id)
        except SQLAlchemyError:
            return None

    async def save(self, memory: MemoryModel) -> MemoryModel:
        try:
            self.session.add(memory)
            await self.session.commit()
            await self.session.refresh(memory)
            return memory
        except SQLAlchemyError as exc:
            self.logger.debug("DB save error, aborting save: %s", exc)
            return memory

    async def delete(self, memory_id: str) -> None:
        try:
            await self.session.execute(delete(MemoryModel).where(MemoryModel.id == memory_id))
            await self.session.commit()
        except SQLAlchemyError as exc:
            self.logger.debug("DB delete error: %s", exc)

    async def search_by_embedding(
        self,
        embedding: Sequence[float],
        limit: int = 5,
        keyword: str | None = None,
        min_score: float = 0.0,
    ) -> list[MemoryModel]:
        """Busca memórias relevantes combinando vetor e léxico.

        O filtro carrega um conjunto de candidatos recentes e ordena por uma
        nota híbrida (cosseno do embedding + sobreposição de tokens). Isso evita
        devolver as N memórias mais recentes quando não têm relação com a
        consulta — causa de contexto alucinado do modelo.

        ``min_score`` corta candidatos irrelevantes (>= 0): memória que fica
        abaixo do limiar NÃO vira contexto do agente.
        """
        query = (keyword or "").strip()
        try:
            result = await self.session.execute(
                select(MemoryModel).order_by(MemoryModel.created_at.desc()).limit(500)
            )
            candidates = list(result.scalars().all())
        except SQLAlchemyError as exc:
            self.logger.debug("DB search error, returning empty: %s", exc)
            return []

        scored = sorted(
            (
                (memory, hybrid_score(query, memory.content, embedding, memory.embedding))
                for memory in candidates
            ),
            key=lambda pair: pair[1],
            reverse=True,
        )
        relevant = [
            memory for memory, score in scored if score >= min_score
        ]
        return relevant[:limit]