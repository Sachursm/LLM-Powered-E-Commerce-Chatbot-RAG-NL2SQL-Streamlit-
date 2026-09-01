from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


DATABASE_URL = settings.DATABASE_URL

if DATABASE_URL.startswith("sqlite:///"):
    DATABASE_URL = DATABASE_URL.replace(
        "sqlite:///",
        "sqlite+aiosqlite:///",
        
    )

engine = create_async_engine(
    DATABASE_URL,
    echo=False
)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)


class Base(DeclarativeBase):
    pass