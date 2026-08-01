from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from app.config import settings

_SQLITE_CONNECT_ARGS = {"check_same_thread": False, "timeout": 30}

def _set_sqlite_pragmas(dbapi_conn, _):
    # Don't set journal_mode — changing it requires an exclusive lock which fails
    # when backend and worker both open the same file simultaneously on Docker+Windows.
    # SQLite defaults to DELETE mode which works fine here.
    dbapi_conn.execute("PRAGMA synchronous=NORMAL")
    dbapi_conn.execute("PRAGMA busy_timeout=10000")

# Async engine — used by FastAPI
engine = create_async_engine(
    settings.DATABASE_URL, echo=False,
    connect_args=_SQLITE_CONNECT_ARGS if "sqlite" in settings.DATABASE_URL else {},
)

@event.listens_for(engine.sync_engine, "connect")
def _async_engine_connect(dbapi_conn, _):
    if "sqlite" in settings.DATABASE_URL:
        _set_sqlite_pragmas(dbapi_conn, _)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

# Sync engine — used by Celery workers (swap aiosqlite → standard sqlite3 driver)
_sync_url = settings.DATABASE_URL.replace("sqlite+aiosqlite", "sqlite").replace("+asyncpg", "")
sync_engine = create_engine(
    _sync_url, echo=False,
    connect_args=_SQLITE_CONNECT_ARGS if "sqlite" in _sync_url else {},
)

if "sqlite" in _sync_url:
    event.listen(sync_engine, "connect", _set_sqlite_pragmas)

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
        platform, campaign, creator, post, comment, metric, report, influencer, user
    )
    Base.metadata.create_all(sync_engine)

    # Lightweight migrations for columns added after initial deploy
    with sync_engine.connect() as conn:
        for stmt in [
            "ALTER TABLE posts ADD COLUMN tags TEXT DEFAULT '[]'",
            "ALTER TABLE posts ADD COLUMN media_type INTEGER DEFAULT 1",
            "ALTER TABLE posts ADD COLUMN is_collab INTEGER DEFAULT 0",
            "ALTER TABLE posts ADD COLUMN counts_disabled INTEGER DEFAULT 0",
            "ALTER TABLE posts ADD COLUMN thumbnail_url TEXT DEFAULT ''",
        ]:
            try:
                conn.execute(__import__("sqlalchemy").text(stmt))
                conn.commit()
            except Exception:
                pass  # column already exists
