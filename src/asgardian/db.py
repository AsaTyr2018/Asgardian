from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .config import Settings, get_settings
from .models import Base


def normalize_async_url(url: str) -> str:
    return url


def create_engine(settings: Settings | None = None) -> AsyncEngine:
    settings = settings or get_settings()
    return create_async_engine(normalize_async_url(settings.database_url), pool_pre_ping=True)


engine = create_engine()
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def session_dependency() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def create_schema(target_engine: AsyncEngine | None = None) -> None:
    target_engine = target_engine or engine
    async with target_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
