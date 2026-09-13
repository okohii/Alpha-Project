from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.db.session import get_session
from app.memory.embeddings import LocalEmbeddingProvider
from app.memory.repository import SqliteMemoryRepository
from app.memory.service import MemoryService

router = APIRouter(prefix="/memories", tags=["memories"])


class MemoryCreateRequest(BaseModel):
    content: str = Field(min_length=1)
    memory_type: str = Field(default="semantic")
    source: str = Field(default="manual")
    importance: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: dict = Field(default_factory=dict)


@router.get("")
async def list_memories(session=Depends(get_session)) -> list[dict]:
    service = MemoryService(SqliteMemoryRepository(session), LocalEmbeddingProvider())
    return [memory.model_dump() for memory in await service.list_memories()]


@router.post("")
async def create_memory(payload: MemoryCreateRequest, session=Depends(get_session)) -> dict:
    service = MemoryService(SqliteMemoryRepository(session), LocalEmbeddingProvider())
    memory = await service.save_memory(
        content=payload.content,
        memory_type=payload.memory_type,
        source=payload.source,
        importance=payload.importance,
        metadata=payload.metadata,
    )
    return memory.model_dump()


@router.delete("/{memory_id}")
async def delete_memory(memory_id: str, session=Depends(get_session)) -> dict:
    service = MemoryService(SqliteMemoryRepository(session), LocalEmbeddingProvider())
    await service.delete_memory(memory_id)
    return {"deleted": True, "id": memory_id}
