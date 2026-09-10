from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.models import Base

settings = get_settings()
engine = create_async_engine(settings.database_url, future=True, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def initialize_database() -> None:
    should_create = (
        settings.app_env.lower() != "production" and settings.database_url.startswith("sqlite")
    )
    if not should_create:
        return
    # Importa modelos de macros aqui para evitar import circular
    # e garantir que as tabelas sejam criadas pelo Base.metadata.create_all
    from app.macros.models import (  # noqa: F401
        MacroExecutionLogRecord,
        MacroRecord,
        MacroScheduleRecord,
        MacroStepRecord,
    )

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session