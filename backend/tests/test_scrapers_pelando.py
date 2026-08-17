"""Testes para scrapers/pelando_scraper.py — listagem + detalhe de ofertas."""

import json

import httpx
import pytest
import respx

from scrapers import pelando_scraper
from scrapers.pelando_scraper import LISTAGEM_URL, coletar_ofertas_pelando


@pytest.fixture(autouse=True)
def _sem_delay_entre_requests(monkeypatch):
    """Evita esperar o delay real (0.5s) entre requisições de detalhe nos testes."""

    async def _sleep_instantaneo(*_args, **_kwargs):
        return None

    monkeypatch.setattr(pelando_scraper.asyncio, "sleep", _sleep_instantaneo)


def _wrap(valor):
    """Serializa um valor no formato [tag, valor] usado pelo Astro (ver _unwrap)."""
    if isinstance(valor, dict):
        return [0, {chave: _wrap(v) for chave, v in valor.items()}]
    return [0, valor]


def _listagem_html(links: list[str]) -> str:
    cards = "".join(
        '<li><div data-inactive="false" data-show-author="false" '
        f'data-show-comment="false" class="_deal-card_x"><a href="{link}?recommendationId=abc">'
        "produto</a></div></li>"
        for link in links
    )
    return f"<html><body><ul>{cards}</ul></body></html>"


def _detalhe_html(deal: dict) -> str:
    props = {"deal": _wrap(deal)}
    json_escapado = json.dumps(props, ensure_ascii=False).replace('"', "&quot;")
    return (
        "<html><body>"
        '<astro-island component-export="DealAlertAction" '
        f'renderer-url="x" props="{json_escapado}" ssr client="idle" '
        'opts="...">'
        "</astro-island></body></html>"
    )


def _deal_base(**overrides) -> dict:
    base = {
        "title": "Notebook ASUS TUF Gamer A16",
        "shortDescription": "<p>Ótimo custo-benefício</p>",
        "price": 5427,
        "discountPercentage": 0,
        "discountFixed": 0,
        "store": {"name": "Casas Bahia"},
        "sourceUrl": "https://www.casasbahia.com.br/notebook-exemplo/p/123",
        "imageUrl": "https://media.pelando.com.br/exemplo.jpg",
        "temperature": 398,
    }
    base.update(overrides)
    return base


class TestColetarOfertasPelando:
    async def test_parseia_oferta_valida_com_desconto_percentual(self):
        link = "https://www.pelando.com.br/d/notebook-exemplo"
        deal = _deal_base(discountPercentage=25.5)

        with respx.mock:
            respx.get(LISTAGEM_URL).mock(
                return_value=httpx.Response(200, text=_listagem_html([link]))
            )
            respx.get(link).mock(return_value=httpx.Response(200, text=_detalhe_html(deal)))

            ofertas = await coletar_ofertas_pelando()

        assert len(ofertas) == 1
        oferta = ofertas[0]
        assert oferta["source"] == "pelando"
        assert oferta["title"] == "Notebook ASUS TUF Gamer A16"
        assert oferta["description"] == "Ótimo custo-benefício"
        assert oferta["price"] == 5427.0
        assert oferta["discount_pct"] == pytest.approx(25.5)
        assert oferta["price_original"] == pytest.approx(5427 / (1 - 0.255), rel=1e-3)
        assert oferta["url"] == "https://www.casasbahia.com.br/notebook-exemplo/p/123"
        assert oferta["store"] == "Casas Bahia"
        assert oferta["image_url"] == "https://media.pelando.com.br/exemplo.jpg"

    async def test_desconto_fixo_quando_sem_percentual(self):
        link = "https://www.pelando.com.br/d/produto-desconto-fixo"
        deal = _deal_base(discountPercentage=0, discountFixed=100.0, price=400)

        with respx.mock:
            respx.get(LISTAGEM_URL).mock(
                return_value=httpx.Response(200, text=_listagem_html([link]))
            )
            respx.get(link).mock(return_value=httpx.Response(200, text=_detalhe_html(deal)))

            ofertas = await coletar_ofertas_pelando()

        assert ofertas[0]["price_original"] == pytest.approx(500.0)
        assert ofertas[0]["discount_pct"] == pytest.approx(20.0)

    async def test_sem_info_de_desconto_fica_none(self):
        link = "https://www.pelando.com.br/d/produto-sem-desconto"
        deal = _deal_base(discountPercentage=0, discountFixed=0)

        with respx.mock:
            respx.get(LISTAGEM_URL).mock(
                return_value=httpx.Response(200, text=_listagem_html([link]))
            )
            respx.get(link).mock(return_value=httpx.Response(200, text=_detalhe_html(deal)))

            ofertas = await coletar_ofertas_pelando()

        assert ofertas[0]["price_original"] is None
        assert ofertas[0]["discount_pct"] is None

    async def test_sem_source_url_e_descartada(self):
        link = "https://www.pelando.com.br/d/produto-sem-link"
        deal = _deal_base(sourceUrl=None)

        with respx.mock:
            respx.get(LISTAGEM_URL).mock(
                return_value=httpx.Response(200, text=_listagem_html([link]))
            )
            respx.get(link).mock(return_value=httpx.Response(200, text=_detalhe_html(deal)))

            ofertas = await coletar_ofertas_pelando()

        assert ofertas == []

    async def test_preco_zero_e_descartada(self):
        link = "https://www.pelando.com.br/d/produto-gratis"
        deal = _deal_base(price=0)

        with respx.mock:
            respx.get(LISTAGEM_URL).mock(
                return_value=httpx.Response(200, text=_listagem_html([link]))
            )
            respx.get(link).mock(return_value=httpx.Response(200, text=_detalhe_html(deal)))

            ofertas = await coletar_ofertas_pelando()

        assert ofertas == []

    async def test_falha_em_um_detalhe_nao_impede_os_outros(self):
        link_ok1 = "https://www.pelando.com.br/d/produto-ok-1"
        link_erro = "https://www.pelando.com.br/d/produto-erro"
        link_ok2 = "https://www.pelando.com.br/d/produto-ok-2"

        with respx.mock:
            respx.get(LISTAGEM_URL).mock(
                return_value=httpx.Response(
                    200, text=_listagem_html([link_ok1, link_erro, link_ok2])
                )
            )
            respx.get(link_ok1).mock(
                return_value=httpx.Response(200, text=_detalhe_html(_deal_base()))
            )
            respx.get(link_erro).mock(return_value=httpx.Response(500))
            respx.get(link_ok2).mock(
                return_value=httpx.Response(200, text=_detalhe_html(_deal_base()))
            )

            ofertas = await coletar_ofertas_pelando()

        assert len(ofertas) == 2

    async def test_listagem_com_erro_retorna_vazio_sem_buscar_detalhes(self):
        with respx.mock:
            rota_listagem = respx.get(LISTAGEM_URL).mock(return_value=httpx.Response(503))
            ofertas = await coletar_ofertas_pelando()

        assert ofertas == []
        assert rota_listagem.called

    async def test_listagem_sem_cards_retorna_vazio(self):
        with respx.mock:
            respx.get(LISTAGEM_URL).mock(
                return_value=httpx.Response(200, text="<html><body>vazio</body></html>")
            )
            ofertas = await coletar_ofertas_pelando()

        assert ofertas == []

    async def test_detalhe_sem_bloco_de_dados_e_ignorada(self):
        link = "https://www.pelando.com.br/d/produto-sem-dados"
        with respx.mock:
            respx.get(LISTAGEM_URL).mock(
                return_value=httpx.Response(200, text=_listagem_html([link]))
            )
            respx.get(link).mock(
                return_value=httpx.Response(200, text="<html><body>mudou</body></html>")
            )
            ofertas = await coletar_ofertas_pelando()

        assert ofertas == []

    async def test_respeita_limit_na_listagem(self):
        links = [f"https://www.pelando.com.br/d/produto-{i}" for i in range(5)]

        with respx.mock:
            respx.get(LISTAGEM_URL).mock(
                return_value=httpx.Response(200, text=_listagem_html(links))
            )
            for link in links[:2]:
                respx.get(link).mock(
                    return_value=httpx.Response(200, text=_detalhe_html(_deal_base()))
                )

            ofertas = await coletar_ofertas_pelando(limit=2)

        assert len(ofertas) == 2

    async def test_links_duplicados_na_listagem_sao_unicos(self):
        link = "https://www.pelando.com.br/d/produto-repetido"

        with respx.mock:
            respx.get(LISTAGEM_URL).mock(
                return_value=httpx.Response(200, text=_listagem_html([link, link, link]))
            )
            respx.get(link).mock(
                return_value=httpx.Response(200, text=_detalhe_html(_deal_base()))
            )

            ofertas = await coletar_ofertas_pelando(limit=10)

        assert len(ofertas) == 1
