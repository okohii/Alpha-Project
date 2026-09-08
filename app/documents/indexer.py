from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.documents.chunker import DocumentChunker
from app.documents.parser import DocumentParser
from app.memory.embeddings import EmbeddingProvider
from app.memory.service import MemoryService
from app.tools.files import FileManager


@dataclass(slots=True)
class IndexedDocument:
    path: str
    hash: str
    chunks: int


class DocumentIndexer:
    def __init__(self, file_manager: FileManager, memory_service: MemoryService, parser: DocumentParser | None = None, chunker: DocumentChunker | None = None, embedding_provider: EmbeddingProvider | None = None) -> None:
        self.file_manager = file_manager
        self.memory_service = memory_service
        self.parser = parser or DocumentParser()
        self.chunker = chunker or DocumentChunker()
        self.embedding_provider = embedding_provider or memory_service.embedding_provider

    async def index_allowed_directories(self) -> dict[str, Any]:
        indexed: list[dict[str, Any]] = []
        for allowed in self.file_manager.allowed_directories:
            for path in allowed.rglob("*"):
                if path.is_file() and path.suffix.lower() in {".txt", ".md", ".json", ".csv", ".py", ".js", ".ts", ".html", ".css", ".yaml", ".yml", ".xml"}:
                    indexed.append(await self.index_document(path))
        return {"indexed": indexed}

    async def index_document(self, path: Path) -> dict[str, Any]:
        text = self.parser.extract_text(path)
        document_hash = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
        chunks = self.chunker.chunk(text)
        saved_chunks = []
        for chunk_index, chunk in enumerate(chunks):
            embedding = await self.embedding_provider.embed(chunk)
            saved_chunks.append({"chunk_index": chunk_index, "length": len(chunk), "embedding_dim": len(embedding)})
        return {"path": str(path), "hash": document_hash, "chunks": saved_chunks}
