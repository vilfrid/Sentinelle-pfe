from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from app.config import settings

# Async engine — used by FastAPI
engine = create_async_engine(settings.DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

# Sync engine — used by Celery workers (swap aiosqlite → standard sqlite3 driver)
_sync_url = settings.DATABASE_URL.replace("sqlite+aiosqlite", "sqlite").replace("+asyncpg", "")
sync_engine = create_engine(_sync_url, echo=False)
SyncSessionLocal = sessionmaker(sync_engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


def get_sync_db() -> Session:
    """Sync session for use in Celery tasks."""
    return SyncSessionLocal()


async def init_db():
    async with engine.begin() as conn:
        from app.models import (  # noqa: F401
            platform, campaign, creator, post, comment, metric, report, influencer
        )
        await conn.run_sync(Base.metadata.create_all)

    # Also create tables on the sync engine (same file, just ensures both see it)
    from app.models import (  # noqa: F401
        platform, campaign, creator, post, comment, metric, report, influencer
    )
    Base.metadata.create_all(sync_engine)
