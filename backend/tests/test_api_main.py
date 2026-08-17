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

    async def test_em_producao_nao_chama_init_db(self, monkeypatch):
        chamado = {"vezes": 0}

        async def _init_db_espiao():
            chamado["vezes"] += 1

        class FakeSettings:
            redis_url = "redis://localhost:6379/1"
            environment = "production"

        monkeypatch.setattr(main_module, "get_settings", lambda: FakeSettings())
        monkeypatch.setattr(main_module, "init_db", _init_db_espiao)

        async with lifespan(app):
            pass

        assert chamado["vezes"] == 0


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

    async def test_health_inclui_status_do_banco(self, client):
        async with client as c:
            resp = await c.get("/health")

        assert resp.json()["services"]["database"] == "connected"

    async def test_checar_banco_real_reporta_disconnected_numa_falha_real(self, monkeypatch):
        class EngineQuebrada:
            def connect(self):
                raise ConnectionError("banco fora do ar")

        monkeypatch.setattr(main_module, "engine", EngineQuebrada())
        assert await main_module._checar_banco() == "disconnected"

    async def test_health_banco_indisponivel_fica_degraded(self, client, monkeypatch):
        async def _checar_banco_falho():
            return "disconnected"

        monkeypatch.setattr(main_module, "_checar_banco", _checar_banco_falho)

        async with client as c:
            resp = await c.get("/health")

        corpo = resp.json()
        assert corpo["services"]["database"] == "disconnected"
        assert corpo["status"] == "degraded"

    async def test_health_bot_sem_heartbeat_fica_unknown(self, client):
        async with client as c:
            resp = await c.get("/health")

        # sem Redis conectado (lifespan não rodou), heartbeat não dá pra checar
        assert resp.json()["services"]["bot"] == "unknown"

    async def test_health_bot_com_heartbeat_fica_ok(self, client):
        from bot import dedup

        async with lifespan(app):
            redis_bot = await dedup.init_redis()
            await dedup.marcar_heartbeat(ttl_segundos=60)
            async with client as c:
                resp = await c.get("/health")
            await redis_bot.delete(dedup.HEARTBEAT_KEY)
            await dedup.fechar_redis()

        assert resp.json()["services"]["bot"] == "ok"


class TestReady:
    async def test_pronto_quando_banco_disponivel(self, client):
        async with client as c:
            resp = await c.get("/ready")

        corpo = resp.json()
        assert resp.status_code == 200
        assert corpo["ready"] is True
        assert corpo["database"] == "connected"

    async def test_nao_pronto_quando_banco_indisponivel(self, client, monkeypatch):
        async def _checar_banco_falho():
            return "disconnected"

        monkeypatch.setattr(main_module, "_checar_banco", _checar_banco_falho)

        async with client as c:
            resp = await c.get("/ready")

        corpo = resp.json()
        assert resp.status_code == 503
        assert corpo["ready"] is False

    async def test_nao_pronto_ignora_redis_indisponivel(self, client, monkeypatch):
        """Redis é opcional (só cache) — não deve tirar a API de circulação."""

        class FakePool:
            async def ping(self):
                raise ConnectionError("caiu")

        monkeypatch.setattr(main_module, "_redis_pool", FakePool())

        async with client as c:
            resp = await c.get("/ready")

        assert resp.status_code == 200
        assert resp.json()["ready"] is True
