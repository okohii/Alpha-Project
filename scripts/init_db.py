from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.database.models import Base


async def main() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
