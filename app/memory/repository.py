from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
import logging

from app.database.models import Memory as MemoryModel


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
            result = await self.session.execute(select(MemoryModel).order_by(MemoryModel.created_at.desc()).limit(limit))
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

    async def search_by_embedding(self, embedding: Sequence[float], limit: int = 5) -> list[MemoryModel]:
        try:
            result = await self.session.execute(select(MemoryModel).order_by(MemoryModel.created_at.desc()).limit(limit))
            return list(result.scalars().all())
        except SQLAlchemyError as exc:
            self.logger.debug("DB search error, returning empty: %s", exc)
            return []
