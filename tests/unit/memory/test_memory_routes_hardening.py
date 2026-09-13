"""H5: rotas /memories usam a implementação concreta, não o Protocol.

Regressão: as rotas instanciavam ``MemoryRepository`` (Protocol), o que
lançava ``TypeError: Protocols cannot be instantiated``. Agora usam
``SqliteMemoryRepository`` e o fluxo save/list/delete funciona de ponta a
ponta com SQLite em memória.
"""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base  # noqa: F401 - registra mapeamentos
from app.memory.embeddings import LocalEmbeddingProvider
from app.memory.repository import MemoryRepositoryProtocol, SqliteMemoryRepository
from app.memory.service import MemoryService


@pytest.fixture
async def service() -> MemoryService:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(bind=engine, expire_on_commit=False)
    session = session_maker()
    return MemoryService(
        SqliteMemoryRepository(session),
        LocalEmbeddingProvider(),
    )


def test_memory_repository_is_interface_not_implementation():
    # Protocol não pode ser instanciado (contrato), a implementação concreta sim.
    with pytest.raises(TypeError):
        MemoryRepositoryProtocol(object())  # type: ignore[call-arg]


@pytest.mark.anyio
async def test_memory_routes_save_list_delete(service):
    saved = await service.save_memory(
        content="preferência: sempre usar tom formal",
        memory_type="semantic",
        source="manual",
        importance=1.0,
        persist_if_relevant=True,
    )
    assert saved is not None

    items = await service.list_memories()
    assert any("tom formal" in item.content for item in items)

    await service.delete_memory(saved.id)
    remaining = await service.list_memories()
    assert all(item.id != saved.id for item in remaining)


@pytest.mark.anyio
async def test_routes_memory_imports_concrete_repository():
    import app.api.routes_memory as routes

    assert routes.SqliteMemoryRepository is SqliteMemoryRepository
    assert "MemoryRepositoryProtocol" not in getattr(routes, "__dict__", {})