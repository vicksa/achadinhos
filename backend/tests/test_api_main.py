"""Testes para api/main.py — lifespan (startup/shutdown) e endpoints raiz."""

import httpx
import pytest

import api.main as main_module
from api.main import app, lifespan


@pytest.fixture(autouse=True)
def _sem_pool_residual():
    """Evita que o `_redis_pool` global vaze de um teste para o outro."""
    main_module._redis_pool = None
    yield
    main_module._redis_pool = None


class TestLifespan:
    async def test_startup_conecta_redis_e_shutdown_fecha(self):
        async with lifespan(app):
            assert main_module._redis_pool is not None
            assert await main_module._redis_pool.ping() is True

        # Depois do shutdown, a referência global é limpa
        assert main_module._redis_pool is None

    async def test_redis_indisponivel_nao_impede_startup(self, monkeypatch):
        class FakeSettings:
            redis_url = "redis://host-que-nao-existe:6379/0"
            environment = "development"

        monkeypatch.setattr(main_module, "get_settings", lambda: FakeSettings())

        async with lifespan(app):
            assert main_module._redis_pool is None

    async def test_falha_ao_inicializar_banco_nao_impede_startup(self, monkeypatch):
        async def _init_db_falho():
            raise ConnectionError("banco fora do ar")

        monkeypatch.setattr(main_module, "init_db", _init_db_falho)

        async with lifespan(app):
            pass  # não deve lançar


@pytest.fixture
def client():
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


class TestEndpointsRaiz:
    async def test_raiz_retorna_metadados(self, client):
        async with client as c:
            resp = await c.get("/")

        corpo = resp.json()
        assert resp.status_code == 200
        assert corpo["api"] == "Price Aggregator — Achadinhos"
        assert "/api/deals" in corpo["endpoints"]["achadinhos"]

    async def test_health_sem_redis_configurado(self, client):
        async with client as c:
            resp = await c.get("/health")

        corpo = resp.json()
        assert corpo["services"]["redis"] == "not_configured"
        assert corpo["status"] == "degraded"

    async def test_health_com_redis_conectado(self, client):
        async with lifespan(app):
            async with client as c:
                resp = await c.get("/health")

        corpo = resp.json()
        assert corpo["services"]["redis"] == "connected"
        assert corpo["status"] == "healthy"

    async def test_health_com_redis_indisponivel_fica_degraded(self, client, monkeypatch):
        class FakePool:
            async def ping(self):
                raise ConnectionError("caiu")

        monkeypatch.setattr(main_module, "_redis_pool", FakePool())

        async with client as c:
            resp = await c.get("/health")

        corpo = resp.json()
        assert corpo["services"]["redis"] == "disconnected"
        assert corpo["status"] == "degraded"
