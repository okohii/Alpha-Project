from __future__ import annotations

import pytest

from app.db.models import JsonListText


def test_json_list_text_binds_list_to_text():
    bind = JsonListText()

    encoded = bind.process_bind_param([0.5, 0.25], None)

    assert isinstance(encoded, str)
    assert bind.process_result_value(encoded, None) == [0.5, 0.25]


def test_json_list_text_handles_none():
    bind = JsonListText()

    assert bind.process_bind_param(None, None) is None
    assert bind.process_result_value(None, None) is None


@pytest.mark.anyio
async def test_memory_persists_embedding_in_sqlite():
    from uuid import uuid4

    from sqlalchemy import delete, select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.db.models import Base, Memory

    engine = create_async_engine("sqlite+aiosqlite://")
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with Session() as session:
        memory = Memory(
            id=str(uuid4()),
            content="teste persistência",
            memory_type="semantic",
            source="test",
            importance=0.9,
            embedding=[0.1, 0.2, 0.3],
        )
        session.add(memory)
        await session.commit()

        result = await session.execute(select(Memory))
        stored = result.scalar_one()

        assert stored.embedding == [0.1, 0.2, 0.3]

        await session.execute(delete(Memory))
        await session.commit()
    await engine.dispose()
