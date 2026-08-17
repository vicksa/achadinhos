"""Testes para api/deals.py — endpoint GET /api/deals."""

import httpx
import pytest_asyncio

from api.main import app
from core.database import AsyncSessionLocal
from core.models import Deal


@pytest_asyncio.fixture
async def client():
    """
    Cliente HTTP assíncrono ligado diretamente à app (via ASGITransport),
    rodando no mesmo event loop do teste — evita conflitos com a conexão
    assíncrona do Postgres (que fica presa ao loop em que foi criada).
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _criar_deal(**overrides) -> Deal:
    base = {
        "source": "pelando",
        "title": "Tênis Olympikus Corre 4",
        "description": None,
        "price": 199.90,
        "price_original": 299.90,
        "discount_pct": 33.34,
        "url": "https://www.exemplo.com/produto",
        "store": "Netshoes",
        "quality_score": 40.0,
        "status": "pending",
    }
    base.update(overrides)

    async with AsyncSessionLocal() as session:
        async with session.begin():
            deal = Deal(**base)
            session.add(deal)
        return deal


class TestListarDeals:
    async def test_lista_vazia_quando_nao_ha_ofertas(self, client):
        resp = await client.get("/api/deals")

        assert resp.status_code == 200
        corpo = resp.json()
        assert corpo["total"] == 0
        assert corpo["results"] == []

    async def test_lista_ofertas_existentes(self, client):
        await _criar_deal(title="Produto A")
        await _criar_deal(title="Produto B")

        resp = await client.get("/api/deals")

        corpo = resp.json()
        assert resp.status_code == 200
        assert corpo["total"] == 2
        assert len(corpo["results"]) == 2

    async def test_busca_por_texto_encontra_titulo(self, client):
        await _criar_deal(title="Tênis Adidas Running")
        await _criar_deal(title="Notebook Gamer")

        resp = await client.get("/api/deals", params={"q": "adidas"})

        corpo = resp.json()
        assert corpo["total"] == 1
        assert corpo["results"][0]["title"] == "Tênis Adidas Running"

    async def test_busca_ignora_acento(self, client):
        await _criar_deal(title="Tênis Nike Revolution")

        resp = await client.get("/api/deals", params={"q": "tenis"})

        assert resp.json()["total"] == 1

    async def test_busca_por_texto_tambem_bate_na_loja(self, client):
        await _criar_deal(title="Produto qualquer", store="Kabum")

        resp = await client.get("/api/deals", params={"q": "kabum"})

        assert resp.json()["total"] == 1

    async def test_filtro_por_loja(self, client):
        await _criar_deal(title="Produto A", store="Amazon")
        await _criar_deal(title="Produto B", store="Magalu")

        resp = await client.get("/api/deals", params={"store": "Amazon"})

        corpo = resp.json()
        assert corpo["total"] == 1
        assert corpo["results"][0]["store"] == "Amazon"

    async def test_filtro_min_discount_exclui_sem_desconto_conhecido(self, client):
        await _criar_deal(title="Com desconto", discount_pct=50.0, price_original=100)
        await _criar_deal(title="Sem desconto", discount_pct=None, price_original=None)

        resp = await client.get("/api/deals", params={"min_discount": 10})

        corpo = resp.json()
        assert corpo["total"] == 1
        assert corpo["results"][0]["title"] == "Com desconto"

    async def test_ordenacao_por_desconto(self, client):
        await _criar_deal(title="Desconto baixo", discount_pct=10.0)
        await _criar_deal(title="Desconto alto", discount_pct=80.0)

        resp = await client.get("/api/deals", params={"sort_by": "discount"})

        titulos = [d["title"] for d in resp.json()["results"]]
        assert titulos == ["Desconto alto", "Desconto baixo"]

    async def test_ordenacao_por_preco_crescente(self, client):
        await _criar_deal(title="Caro", price=999.0)
        await _criar_deal(title="Barato", price=10.0)

        resp = await client.get("/api/deals", params={"sort_by": "price_asc"})

        titulos = [d["title"] for d in resp.json()["results"]]
        assert titulos == ["Barato", "Caro"]

    async def test_ordenacao_por_preco_decrescente(self, client):
        await _criar_deal(title="Caro", price=999.0)
        await _criar_deal(title="Barato", price=10.0)

        resp = await client.get("/api/deals", params={"sort_by": "price_desc"})

        titulos = [d["title"] for d in resp.json()["results"]]
        assert titulos == ["Caro", "Barato"]

    async def test_paginacao_respeita_limit_e_offset(self, client):
        for i in range(5):
            await _criar_deal(title=f"Produto {i}")

        pagina1 = (await client.get("/api/deals", params={"limit": 2, "offset": 0})).json()
        pagina2 = (await client.get("/api/deals", params={"limit": 2, "offset": 2})).json()

        assert pagina1["total"] == 5
        assert len(pagina1["results"]) == 2
        assert len(pagina2["results"]) == 2
        assert pagina1["results"] != pagina2["results"]

    async def test_ofertas_sem_preco_valido_nao_aparecem(self, client):
        await _criar_deal(title="Sem preço", price=None)
        await _criar_deal(title="Preço zero", price=0)
        await _criar_deal(title="Preço válido", price=50.0)

        resp = await client.get("/api/deals")

        corpo = resp.json()
        assert corpo["total"] == 1
        assert corpo["results"][0]["title"] == "Preço válido"

    async def test_usa_affiliate_url_quando_disponivel(self, client):
        await _criar_deal(
            title="Com afiliado",
            url="https://loja.com/produto",
            affiliate_url="https://loja.com/produto?tag=meuid",
        )

        resp = await client.get("/api/deals")

        assert resp.json()["results"][0]["url"] == "https://loja.com/produto?tag=meuid"

    async def test_limit_acima_do_maximo_e_rejeitado(self, client):
        resp = await client.get("/api/deals", params={"limit": 1000})

        assert resp.status_code == 422


class TestHealthCheck:
    async def test_health_retorna_200(self, client):
        resp = await client.get("/health")

        assert resp.status_code == 200
        assert resp.json()["status"] in ("healthy", "degraded")
