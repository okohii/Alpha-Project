from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.memory.embeddings import LocalEmbeddingProvider
from app.memory.repository import SqliteMemoryRepository


class _Scalars:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return _Scalars(self.rows)


class FakeSession:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, stmt):
        return _Result(self.rows)


@pytest.mark.anyio
async def test_retrieval_prefers_recent_important_contextual_memory():
    provider = LocalEmbeddingProvider()
    now = datetime.now(UTC)
    rows = []
    for content, importance, created_at in (
        ("ALPHA usa SQLite no projeto", 1.0, now),
        ("ALPHA usa SQLite em uma nota antiga", 1.0, now - timedelta(days=180)),
        ("ALPHA usa PostgreSQL para testes", 0.2, now),
    ):
        rows.append(
            SimpleNamespace(
                id=content,
                content=content,
                memory_type="semantic",
                source="test",
                importance=importance,
                confidence=1.0,
                embedding=await provider.embed(content),
                metadata_={},
                created_at=created_at,
                updated_at=created_at,
                expiration=None,
            )
        )

    repository = SqliteMemoryRepository(FakeSession(rows))
    results = await repository.search(
        "ALPHA SQLite",
        await provider.embed("ALPHA SQLite"),
        limit=3,
        min_score=0.0,
        context={"project": "SQLite"},
    )

    assert results[0].content == "ALPHA usa SQLite no projeto"
