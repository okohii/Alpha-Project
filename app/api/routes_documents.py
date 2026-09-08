from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.database.session import get_session
from app.documents.indexer import DocumentIndexer
from app.memory.embeddings import LocalEmbeddingProvider
from app.memory.repository import MemoryRepository
from app.memory.service import MemoryService
from app.tools.files import FileManager

router = APIRouter(prefix="/documents", tags=["documents"])


class DocumentSearchRequest(BaseModel):
    query: str = Field(min_length=1)


@router.post("/index")
async def index_documents(session=Depends(get_session)) -> dict:
    path_repo = __import__("app.tasks.service", fromlist=["ManagedPathRepository"]).ManagedPathRepository(session)
    allowed_paths = await path_repo.list()
    file_manager = FileManager()
    if hasattr(file_manager, "allowed_directories"):
        file_manager.allowed_directories = [__import__("pathlib").Path(record.path).expanduser().resolve() for record in allowed_paths if getattr(record, "is_allowed", 1)]
    indexer = DocumentIndexer(file_manager, MemoryService(MemoryRepository(session), LocalEmbeddingProvider()))
    return await indexer.index_allowed_directories()


@router.get("")
async def list_documents() -> list[dict]:
    return []


@router.post("/search")
async def search_documents(payload: DocumentSearchRequest) -> dict:
    return {"query": payload.query, "results": []}
