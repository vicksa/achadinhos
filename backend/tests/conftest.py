"""
Configuração compartilhada dos testes (pytest).

IMPORTANTE: a variável DATABASE_URL é sobrescrita para apontar para um
banco de testes ANTES de qualquer módulo da aplicação ser importado —
`core.database` cria a engine na hora do import, então a ordem importa.

Requer um Postgres acessível (o mesmo `achadinhos-db` do docker-compose
serve) com um banco `achadinhos_test` já criado:

    docker exec achadinhos-db psql -U root -d postgres -c "CREATE DATABASE achadinhos_test;"

Pode ser sobrescrito via variável de ambiente TEST_DATABASE_URL.
"""

import os

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://root:password@localhost:5432/achadinhos_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")  # DB 1 = isolado dos dados reais (DB 0)

import pytest
import pytest_asyncio
from sqlalchemy import text

import core.models  # noqa: F401 — registra os models no Base.metadata
from core.database import AsyncSessionLocal, engine, init_db


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _preparar_banco_de_testes():
    """Cria extensões/tabelas uma vez no início da sessão de testes."""
    await init_db()
    yield
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _limpar_tabelas():
    """Garante que cada teste começa com as tabelas vazias."""
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE TABLE deals, products, offers, price_alerts "
                "RESTART IDENTITY CASCADE"
            )
        )
    yield


@pytest_asyncio.fixture
async def db_session():
    """Sessão de banco pronta para uso direto nos testes."""
    async with AsyncSessionLocal() as session:
        yield session


@pytest.fixture
def oferta_exemplo() -> dict:
    """Dicionário de oferta normalizada, no formato que os scrapers retornam."""
    return {
        "source": "pelando",
        "title": "Fone de Ouvido Bluetooth JBL Tune 520BT",
        "description": "Ótimo custo-benefício, bateria de longa duração.",
        "price": 189.90,
        "price_original": 299.90,
        "discount_pct": 36.68,
        "url": "https://www.amazon.com.br/fone-jbl-tune-520bt/dp/B0EXEMPLO",
        "affiliate_url": None,
        "image_url": "https://media.pelando.com.br/exemplo.jpg",
        "store": "Amazon",
        "quality_score": 45.5,
        "status": "pending",
    }
