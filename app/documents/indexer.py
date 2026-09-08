from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select

from app.db.models import Document, DocumentChunk
from app.documents.chunker import DocumentChunker
from app.documents.parser import DocumentParser
from app.memory.embeddings import EmbeddingProvider
from app.memory.repository import hybrid_score
from app.skills.files.service import FileManager

SUPPORTED_SUFFIXES = {
    ".txt",
    ".md",
    ".json",
    ".csv",
    ".py",
    ".js",
    ".ts",
    ".html",
    ".css",
    ".yaml",
    ".yml",
    ".xml",
}


@dataclass(slots=True)
class IndexedDocument:
    path: str
    hash: str
    chunks: int


class DocumentRepository:
    """Persistência de documentos e chunks indexados no banco."""

    def __init__(self, session: Any) -> None:
        self.session = session

    async def get_by_path(self, path: str) -> Document | None:
        result = await self.session.execute(
            select(Document).where(Document.path == str(Path(path).resolve()))
        )
        return result.scalar_one_or_none()

    async def upsert(self, path: str, filename: str, hash_value: str) -> Document:
        existing = await self.get_by_path(path)
        if existing is not None:
            if existing.hash == hash_value:
                return existing
            await self.delete_chunks(existing.id)
            existing.hash = hash_value
            await self.session.commit()
            await self.session.refresh(existing)
            return existing
        document = Document(
            id=str(uuid4()),
            filename=filename,
            path=str(Path(path).resolve()),
            hash=hash_value,
        )
        self.session.add(document)
        await self.session.commit()
        await self.session.refresh(document)
        return document

    async def delete_chunks(self, document_id: str) -> None:
        await self.session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )
        await self.session.commit()

    async def save_chunks(
        self, document_id: str, chunks: list[str], embeddings: list[list[float]]
    ) -> None:
        for index, (chunk, embedding) in enumerate(zip(chunks, embeddings, strict=True)):
            self.session.add(
                DocumentChunk(
                    id=str(uuid4()),
                    document_id=document_id,
                    content=chunk,
                    chunk_index=index,
                    embedding=embedding,
                )
            )
        await self.session.commit()

    async def upsert_all(
        self,
        path: str,
        filename: str,
        hash_value: str,
        chunks: list[str],
        embeddings: list[list[float]],
    ) -> Document:
        document = await self.upsert(path, filename, hash_value)
        if await self.chunk_count(document.id) != len(chunks):
            await self.delete_chunks(document.id)
            await self.save_chunks(document.id, chunks, embeddings)
        return document

    async def chunk_count(self, document_id: str) -> int:
        from sqlalchemy import func

        result = await self.session.execute(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
        )
        return int(result.scalar() or 0)

    async def list_documents(self, limit: int = 100) -> list[dict[str, Any]]:
        result = await self.session.execute(
            select(Document).order_by(Document.created_at.desc()).limit(limit)
        )
        return [
            {
                "id": doc.id,
                "filename": doc.filename,
                "path": doc.path,
                "hash": doc.hash,
                "mime_type": doc.mime_type,
                "created_at": doc.created_at.isoformat() if doc.created_at else None,
            }
            for doc in result.scalars().all()
        ]

    async def search(
        self,
        query: str,
        query_embedding: list[float],
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        result = await self.session.execute(
            select(DocumentChunk, Document)
            .join(Document, Document.id == DocumentChunk.document_id)
            .order_by(DocumentChunk.chunk_index)
            .limit(500)
        )
        rows = list(result.all())
        paths_by_document = {document.id: document.path for _, document in rows}
        candidates = [chunk for chunk, _ in rows]
        ranked = sorted(
            candidates,
            key=lambda chunk: hybrid_score(
                query,
                chunk.content,
                query_embedding,
                chunk.embedding,
            ),
            reverse=True,
        )
        return [
            {
                "document_id": chunk.document_id,
                "path": paths_by_document.get(chunk.document_id, ""),
                "content": chunk.content,
                "score": round(
                    hybrid_score(query, chunk.content, query_embedding, chunk.embedding), 4
                ),
            }
            for chunk in ranked[:limit]
        ]


class DocumentIndexer:
    def __init__(
        self,
        file_manager: FileManager,
        repository: DocumentRepository,
        embedding_provider: EmbeddingProvider,
        parser: DocumentParser | None = None,
        chunker: DocumentChunker | None = None,
    ) -> None:
        self.file_manager = file_manager
        self.repository = repository
        self.embedding_provider = embedding_provider
        self.parser = parser or DocumentParser()
        self.chunker = chunker or DocumentChunker()

    async def index_allowed_directories(self) -> dict[str, Any]:
        indexed: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        seen: set[str] = set()
        for allowed in self.file_manager.allowed_directories:
            for path in allowed.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
                    continue
                key = str(path.resolve())
                if key in seen:
                    continue
                seen.add(key)
                try:
                    indexed.append(await self.index_document(path))
                except Exception as exc:
                    errors.append({"path": str(path), "error": str(exc)})
        return {"indexed": indexed, "errors": errors}

    async def index_document(self, path: Path) -> dict[str, Any]:
        text = self.parser.extract_text(path)
        document_hash = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
        chunks = self.chunker.chunk(text)
        embeddings = [await self.embedding_provider.embed(chunk) for chunk in chunks]
        document = await self.repository.upsert_all(
            path=str(path),
            filename=path.name,
            hash_value=document_hash,
            chunks=chunks,
            embeddings=embeddings,
        )
        return {
            "path": str(path),
            "filename": path.name,
            "hash": document_hash,
            "chunks": len(chunks),
            "document_id": document.id,
        }

    async def search_documents(self, query: str, limit: int = 5) -> dict[str, Any]:
        embedding = await self.embedding_provider.embed(query)
        results = await self.repository.search(query, embedding, limit=limit)
        return {"query": query, "results": results}