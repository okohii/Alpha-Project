from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.db.session import get_session
from app.documents.indexer import DocumentIndexer, DocumentRepository
from app.memory.embeddings import LocalEmbeddingProvider
from app.tasks.service import ManagedPathRepository
from app.tools.files import FileManager

router = APIRouter(prefix="/documents", tags=["documents"])


class DocumentSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=20)


def _build_indexer(session) -> DocumentIndexer:
    path_repo = ManagedPathRepository(session)
    allowed_paths = [record.path for record in path_repo.list()]
    file_manager = FileManager()
    if allowed_paths:
        file_manager.allowed_directories = [
            Path(path).expanduser().resolve() for path in allowed_paths
        ]
    return DocumentIndexer(
        file_manager=file_manager,
        repository=DocumentRepository(session),
        embedding_provider=LocalEmbeddingProvider(),
    )


@router.post("/index")
async def index_documents(session=Depends(get_session)) -> dict:
    indexer = _build_indexer(session)
    return await indexer.index_allowed_directories()


@router.get("")
async def list_documents(session=Depends(get_session)) -> list[dict]:
    repository = DocumentRepository(session)
    return await repository.list_documents()


@router.post("/search")
async def search_documents(payload: DocumentSearchRequest, session=Depends(get_session)) -> dict:
    indexer = _build_indexer(session)
    return await indexer.search_documents(payload.query, limit=payload.limit)