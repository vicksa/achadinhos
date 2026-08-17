"""
Configuração do banco de dados com SQLAlchemy async.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from core.config import get_settings

settings = get_settings()

# Engine async — pool de conexões para PostgreSQL
engine = create_async_engine(
    settings.database_url,
    echo=settings.environment == "development",
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

# Fábrica de sessões async
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Classe base para todos os modelos ORM."""
    pass


async def init_db():
    """Cria todas as tabelas no banco (usar apenas em dev/testes)."""
    async with engine.begin() as conn:
        # Necessária para busca sem acento (ex: "tenis" encontrar "Tênis")
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS unaccent"))
        await conn.run_sync(Base.metadata.create_all)
        # Colunas adicionadas depois da primeira instalação — como não usamos
        # Alembic, garantimos aqui que bancos já existentes sejam atualizados.
        await conn.execute(
            text(
                "ALTER TABLE IF EXISTS deals "
                "ADD COLUMN IF NOT EXISTS published_twitter BOOLEAN DEFAULT false"
            )
        )
