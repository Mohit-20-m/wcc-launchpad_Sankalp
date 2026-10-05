"""
Database engine and session setup.

This is real and working from Step 1 onward, because our health check
uses it to prove the backend can actually reach Postgres — not just
that the backend process itself is alive.

Tables are created from the models in app/models on startup
(Base.metadata.create_all); see ARCHITECTURE.md for that tradeoff.
"""

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    """Every model inherits from this. Shared registry across all tables."""
    pass


engine = create_async_engine(settings.database_url, pool_pre_ping=True)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db():
    """FastAPI dependency that yields a DB session per request."""
    async with AsyncSessionLocal() as session:
        yield session
