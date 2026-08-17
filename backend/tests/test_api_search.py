"""Testes para api/search.py — busca com cache Redis e agregação de marketplaces."""

import json

import httpx
import pytest
import pytest_asyncio
import redis.asyncio as aioredis

import api.search as search_module
from api.main import app
from api.schemas import ProductOffer, SortOption
from api.search import _filtrar_resultados, _normalizar_cache_key, _ordenar_resultados


def _offer(**overrides) -> ProductOffer:
    base = dict(
        name="Echo Dot 5ª Geração",
        price=279.0,
        price_old=399.0,
        image_url=None,
        marketplace="mercadolivre",
        url="https://www.mercadolivre.com.br/echo-dot",
        affiliate_url=None,
        rating=4.7,
        rating_count=1000,
        in_stock=True,
        discount_pct=30.08,
    )
    base.update(overrides)
    return ProductOffer(**base)


class TestNormalizarCacheKey:
    def test_remove_acentos_e_minusculo(self):
        assert _normalizar_cache_key("Iphone 15 PRÓ") == "search:iphone 15 pro"

    def test_colapsa_espacos(self):
        assert _normalizar_cache_key("  echo   dot  ") == "search:echo dot"


class TestOrdenarResultados:
    def test_price_asc(self):
        ofertas = [_offer(price=100), _offer(price=10), _offer(price=50)]
        resultado = _ordenar_resultados(ofertas, SortOption.PRICE_ASC)
        assert [o.price for o in resultado] == [10, 50, 100]

    def test_price_desc(self):
        ofertas = [_offer(price=100), _offer(price=10), _offer(price=50)]
        resultado = _ordenar_resultados(ofertas, SortOption.PRICE_DESC)
        assert [o.price for o in resultado] == [100, 50, 10]

    def test_discount(self):
        ofertas = [_offer(discount_pct=10), _offer(discount_pct=90), _offer(discount_pct=None)]
        resultado = _ordenar_resultados(ofertas, SortOption.DISCOUNT)
        assert resultado[0].discount_pct == 90

    def test_rating(self):
        ofertas = [_offer(rating=3.0), _offer(rating=5.0), _offer(rating=None)]
        resultado = _ordenar_resultados(ofertas, SortOption.RATING)
        assert resultado[0].rating == 5.0

    def test_name(self):
        ofertas = [_offer(name="Zebra"), _offer(name="abacate")]
        resultado = _ordenar_resultados(ofertas, SortOption.NAME)
        assert [o.name for o in resultado] == ["abacate", "Zebra"]


class TestFiltrarResultados:
    def test_min_price(self):
        ofertas = [_offer(price=10), _offer(price=100)]
        assert len(_filtrar_resultados(ofertas, min_price=50)) == 1

    def test_max_price(self):
        ofertas = [_offer(price=10), _offer(price=100)]
        assert len(_filtrar_resultados(ofertas, max_price=50)) == 1

    def test_marketplace_case_insensitive(self):
        ofertas = [_offer(marketplace="MercadoLivre"), _offer(marketplace="amazon")]
        resultado = _filtrar_resultados(ofertas, marketplace="mercadolivre")
        assert len(resultado) == 1
        assert resultado[0].marketplace == "MercadoLivre"


@pytest_asyncio.fixture
async def redis_client():
    client = aioredis.from_url("redis://localhost:6379/1", decode_responses=True)
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


@pytest.fixture
def client_com_redis(monkeypatch, redis_client):
    async def _fake_get_redis():
        return redis_client

    monkeypatch.setattr(search_module, "_get_redis", _fake_get_redis)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _mockar_busca_ml(monkeypatch, resultado=None, excecao=None):
    chamadas = []

    async def _fake(query, limit=20):
        chamadas.append(query)
        if excecao:
            raise excecao
        return resultado or []

    monkeypatch.setattr(search_module, "buscar_mercadolivre", _fake)
    return chamadas


class TestBuscarProdutosEndpoint:
    async def test_query_curta_e_rejeitada(self, client_com_redis):
        async with client_com_redis as client:
            resp = await client.get("/api/search", params={"q": "a"})
        assert resp.status_code == 422

    async def test_cache_miss_busca_no_mercadolivre_e_cacheia(
        self, monkeypatch, client_com_redis, redis_client
    ):
        chamadas = _mockar_busca_ml(monkeypatch, resultado=[_offer()])

        async with client_com_redis as client:
            resp = await client.get("/api/search", params={"q": "echo dot"})

        corpo = resp.json()
        assert resp.status_code == 200
        assert corpo["cached"] is False
        assert corpo["total_results"] == 1
        assert len(chamadas) == 1

        cacheado = await redis_client.get(_normalizar_cache_key("echo dot"))
        assert cacheado is not None
        assert json.loads(cacheado)[0]["name"] == "Echo Dot 5ª Geração"

    async def test_cache_hit_nao_chama_mercadolivre(
        self, monkeypatch, client_com_redis, redis_client
    ):
        chamadas = _mockar_busca_ml(monkeypatch)
        chave = _normalizar_cache_key("echo dot")
        await redis_client.set(
            chave, json.dumps([_offer().model_dump()], ensure_ascii=False)
        )

        async with client_com_redis as client:
            resp = await client.get("/api/search", params={"q": "echo dot"})

        corpo = resp.json()
        assert corpo["cached"] is True
        assert corpo["total_results"] == 1
        assert chamadas == []  # não deveria ter ido buscar de novo

    async def test_filtros_aplicados_mesmo_em_cache_hit(
        self, monkeypatch, client_com_redis, redis_client
    ):
        _mockar_busca_ml(monkeypatch)
        chave = _normalizar_cache_key("produto")
        ofertas = [_offer(price=10).model_dump(), _offer(price=1000).model_dump()]
        await redis_client.set(chave, json.dumps(ofertas, ensure_ascii=False))

        async with client_com_redis as client:
            resp = await client.get(
                "/api/search", params={"q": "produto", "min_price": 500}
            )

        assert resp.json()["total_results"] == 1

    async def test_marketplace_com_erro_nao_derruba_a_busca(
        self, monkeypatch, client_com_redis
    ):
        _mockar_busca_ml(monkeypatch, excecao=RuntimeError("marketplace fora do ar"))

        async with client_com_redis as client:
            resp = await client.get("/api/search", params={"q": "produto"})

        assert resp.status_code == 200
        assert resp.json()["total_results"] == 0

    async def test_ordenacao_por_desconto_via_endpoint(
        self, monkeypatch, client_com_redis
    ):
        _mockar_busca_ml(
            monkeypatch,
            resultado=[_offer(discount_pct=10, name="A"), _offer(discount_pct=90, name="B")],
        )

        async with client_com_redis as client:
            resp = await client.get(
                "/api/search", params={"q": "produto", "sort_by": "discount"}
            )

        nomes = [r["name"] for r in resp.json()["results"]]
        assert nomes == ["B", "A"]


class TestSugestoesEndpoint:
    async def test_sem_redis_retorna_vazio(self, monkeypatch):
        async def _sem_redis():
            return None

        monkeypatch.setattr(search_module, "_get_redis", _sem_redis)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/search/suggestions")

        assert resp.status_code == 200
        assert resp.json()["suggestions"] == []

    async def test_retorna_buscas_recentes_mais_novas_primeiro(
        self, monkeypatch, client_com_redis
    ):
        _mockar_busca_ml(monkeypatch, resultado=[_offer()])

        async with client_com_redis as client:
            await client.get("/api/search", params={"q": "iphone"})
            await client.get("/api/search", params={"q": "notebook"})
            resp = await client.get("/api/search/suggestions")

        assert resp.json()["suggestions"] == ["notebook", "iphone"]

    async def test_filtra_por_prefixo(self, monkeypatch, client_com_redis):
        _mockar_busca_ml(monkeypatch, resultado=[_offer()])

        async with client_com_redis as client:
            await client.get("/api/search", params={"q": "iphone 15"})
            await client.get("/api/search", params={"q": "notebook gamer"})
            resp = await client.get("/api/search/suggestions", params={"q": "iph"})

        assert resp.json()["suggestions"] == ["iphone 15"]
