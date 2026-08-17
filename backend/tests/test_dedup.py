"""Testes para bot/dedup.py — normalização de URL, hash e dedup via Redis."""

import pytest
import pytest_asyncio
import redis.asyncio as redis

from bot import dedup


class TestNormalizarUrl:
    def test_remove_query_string(self):
        url = "https://exemplo.com/produto?utm_source=share&ref=123"
        assert dedup._normalizar_url(url) == "https://exemplo.com/produto"

    def test_remove_fragmento(self):
        url = "https://exemplo.com/produto#detalhes"
        assert dedup._normalizar_url(url) == "https://exemplo.com/produto"

    def test_remove_barra_final(self):
        assert dedup._normalizar_url("https://exemplo.com/produto/") == (
            dedup._normalizar_url("https://exemplo.com/produto")
        )

    def test_case_insensitive(self):
        assert dedup._normalizar_url("HTTPS://EXEMPLO.com/Produto") == (
            dedup._normalizar_url("https://exemplo.com/produto")
        )


class TestGerarHash:
    def test_mesmo_hash_para_urls_equivalentes(self):
        h1 = dedup._gerar_hash("https://exemplo.com/produto?utm_source=telegram")
        h2 = dedup._gerar_hash("https://exemplo.com/produto?ref=outro")
        assert h1 == h2

    def test_hash_diferente_para_produtos_diferentes(self):
        h1 = dedup._gerar_hash("https://exemplo.com/produto-a")
        h2 = dedup._gerar_hash("https://exemplo.com/produto-b")
        assert h1 != h2

    def test_hash_e_md5_hex(self):
        h = dedup._gerar_hash("https://exemplo.com/produto")
        assert len(h) == 32
        int(h, 16)  # não deve lançar ValueError


@pytest_asyncio.fixture
async def redis_de_teste():
    """Conecta no Redis (DB de testes) e limpa antes/depois de cada teste."""
    client = await dedup.init_redis()
    await client.flushdb()
    yield client
    await client.flushdb()
    await dedup.fechar_redis()


class TestDedupComRedis:
    async def test_url_nova_nao_e_duplicata(self, redis_de_teste):
        assert await dedup.ja_foi_postado("https://exemplo.com/produto-novo") is False

    async def test_url_marcada_vira_duplicata(self, redis_de_teste):
        url = "https://exemplo.com/produto-marcado"
        await dedup.marcar_postado(url)
        assert await dedup.ja_foi_postado(url) is True

    async def test_dedup_ignora_query_params_diferentes(self, redis_de_teste):
        await dedup.marcar_postado("https://exemplo.com/produto?utm_source=telegram")
        duplicata = await dedup.ja_foi_postado(
            "https://exemplo.com/produto?utm_source=twitter&ref=abc"
        )
        assert duplicata is True

    async def test_urls_diferentes_nao_conflitam(self, redis_de_teste):
        await dedup.marcar_postado("https://exemplo.com/produto-a")
        assert await dedup.ja_foi_postado("https://exemplo.com/produto-b") is False


class TestDedupSemRedisInicializado:
    async def test_ja_foi_postado_fail_open(self, monkeypatch):
        monkeypatch.setattr(dedup, "_redis_client", None)
        assert await dedup.ja_foi_postado("https://exemplo.com/produto") is False

    async def test_marcar_postado_nao_lanca_erro(self, monkeypatch):
        monkeypatch.setattr(dedup, "_redis_client", None)
        await dedup.marcar_postado("https://exemplo.com/produto")  # não deve lançar


class TestInitRedis:
    async def test_reutiliza_conexao_existente(self, redis_de_teste):
        outra_chamada = await dedup.init_redis()
        assert outra_chamada is redis_de_teste

    async def test_falha_de_conexao_propaga_e_limpa_cliente(self, monkeypatch):
        monkeypatch.setattr(dedup, "_redis_client", None)

        class FakeSettings:
            redis_url = "redis://host-que-nao-existe:6379/0"

        monkeypatch.setattr(dedup, "get_settings", lambda: FakeSettings())

        with pytest.raises(redis.ConnectionError):
            await dedup.init_redis()

        assert dedup._redis_client is None


class TestDedupComErroDeRedis:
    """Simula falhas do Redis em runtime (não na conexão) — devem ser fail-open/silenciosas."""

    class _ClienteQuebrado:
        async def exists(self, *_a, **_kw):
            raise redis.RedisError("conexão caiu no meio da operação")

        async def set(self, *_a, **_kw):
            raise redis.RedisError("conexão caiu no meio da operação")

    async def test_ja_foi_postado_com_erro_no_redis_e_fail_open(self, monkeypatch):
        monkeypatch.setattr(dedup, "_redis_client", self._ClienteQuebrado())
        assert await dedup.ja_foi_postado("https://exemplo.com/produto") is False

    async def test_marcar_postado_com_erro_no_redis_nao_lanca(self, monkeypatch):
        monkeypatch.setattr(dedup, "_redis_client", self._ClienteQuebrado())
        await dedup.marcar_postado("https://exemplo.com/produto")  # não deve lançar


class TestMarcarHeartbeat:
    async def test_grava_chave_com_ttl(self, redis_de_teste):
        await dedup.marcar_heartbeat(ttl_segundos=60)

        valor = await redis_de_teste.get(dedup.HEARTBEAT_KEY)
        assert valor is not None

        ttl = await redis_de_teste.ttl(dedup.HEARTBEAT_KEY)
        assert 0 < ttl <= 60

    async def test_sem_redis_inicializado_nao_lanca(self, monkeypatch):
        monkeypatch.setattr(dedup, "_redis_client", None)
        await dedup.marcar_heartbeat(ttl_segundos=60)  # não deve lançar

    async def test_erro_no_redis_nao_lanca(self, monkeypatch):
        class _ClienteQuebrado:
            async def set(self, *_a, **_kw):
                raise redis.RedisError("conexão caiu")

        monkeypatch.setattr(dedup, "_redis_client", _ClienteQuebrado())
        await dedup.marcar_heartbeat(ttl_segundos=60)  # não deve lançar
