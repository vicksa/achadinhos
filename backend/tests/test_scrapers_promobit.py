"""Testes para scrapers/promobit_scraper.py — parsing do __NEXT_DATA__."""

import json

import httpx
import pytest
import respx

from scrapers.promobit_scraper import HOMEPAGE_URL, coletar_ofertas_promobit


def _html_com_ofertas(offers: list[dict]) -> str:
    """Monta um HTML mínimo com o bloco __NEXT_DATA__ que o Promobit embute."""
    payload = {
        "props": {
            "pageProps": {
                "serverOffers": {"offers": offers},
            }
        }
    }
    return (
        "<html><body>"
        f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
        "</body></html>"
    )


def _oferta_bruta(**overrides) -> dict:
    base = {
        "offerTitle": "Fritadeira Air Fryer Elgin 3,5L",
        "offerSlug": "fritadeira-air-fryer-elgin-35l-123",
        "offerPrice": 127.24,
        "offerOldPrice": 197.99,
        "offerDiscontPercentage": 35.74,
        "offerLikes": 42,
        "storeName": "Mercado Livre",
    }
    base.update(overrides)
    return base


class TestColetarOfertasPromobit:
    async def test_parseia_oferta_valida(self):
        html = _html_com_ofertas([_oferta_bruta()])
        with respx.mock:
            respx.get(HOMEPAGE_URL).mock(return_value=httpx.Response(200, text=html))
            ofertas = await coletar_ofertas_promobit()

        assert len(ofertas) == 1
        oferta = ofertas[0]
        assert oferta["source"] == "promobit"
        assert oferta["title"] == "Fritadeira Air Fryer Elgin 3,5L"
        assert oferta["price"] == 127.24
        assert oferta["price_original"] == 197.99
        assert oferta["discount_pct"] == pytest.approx(35.74)
        assert oferta["url"] == "https://www.promobit.com.br/oferta/fritadeira-air-fryer-elgin-35l-123/"
        assert oferta["store"] == "Mercado Livre"
        assert oferta["quality_score"] is not None

    async def test_desconto_calculado_quando_percentual_nao_informado(self):
        bruta = _oferta_bruta(offerDiscontPercentage=0, offerPrice=50.0, offerOldPrice=100.0)
        html = _html_com_ofertas([bruta])
        with respx.mock:
            respx.get(HOMEPAGE_URL).mock(return_value=httpx.Response(200, text=html))
            ofertas = await coletar_ofertas_promobit()

        assert ofertas[0]["discount_pct"] == pytest.approx(50.0)

    async def test_sem_preco_antigo_nao_calcula_desconto(self):
        bruta = _oferta_bruta(offerOldPrice=0, offerDiscontPercentage=0)
        html = _html_com_ofertas([bruta])
        with respx.mock:
            respx.get(HOMEPAGE_URL).mock(return_value=httpx.Response(200, text=html))
            ofertas = await coletar_ofertas_promobit()

        assert ofertas[0]["price_original"] is None
        assert ofertas[0]["discount_pct"] is None

    async def test_preco_antigo_menor_que_atual_ignorado(self):
        # oferOldPrice <= offerPrice não é um desconto real
        bruta = _oferta_bruta(offerOldPrice=0.01, offerDiscontPercentage=0)
        html = _html_com_ofertas([bruta])
        with respx.mock:
            respx.get(HOMEPAGE_URL).mock(return_value=httpx.Response(200, text=html))
            ofertas = await coletar_ofertas_promobit()

        assert ofertas[0]["price_original"] is None

    @pytest.mark.parametrize(
        "campo_removido", ["offerTitle", "offerSlug", "offerPrice"]
    )
    async def test_oferta_sem_campo_obrigatorio_e_descartada(self, campo_removido):
        bruta = _oferta_bruta()
        bruta[campo_removido] = None
        html = _html_com_ofertas([bruta])
        with respx.mock:
            respx.get(HOMEPAGE_URL).mock(return_value=httpx.Response(200, text=html))
            ofertas = await coletar_ofertas_promobit()

        assert ofertas == []

    async def test_preco_zero_e_descartado(self):
        bruta = _oferta_bruta(offerPrice=0)
        html = _html_com_ofertas([bruta])
        with respx.mock:
            respx.get(HOMEPAGE_URL).mock(return_value=httpx.Response(200, text=html))
            ofertas = await coletar_ofertas_promobit()

        assert ofertas == []

    async def test_respeita_limit(self):
        brutas = [_oferta_bruta(offerSlug=f"produto-{i}") for i in range(10)]
        html = _html_com_ofertas(brutas)
        with respx.mock:
            respx.get(HOMEPAGE_URL).mock(return_value=httpx.Response(200, text=html))
            ofertas = await coletar_ofertas_promobit(limit=3)

        assert len(ofertas) == 3

    async def test_sem_next_data_retorna_vazio(self):
        with respx.mock:
            respx.get(HOMEPAGE_URL).mock(
                return_value=httpx.Response(200, text="<html><body>site mudou</body></html>")
            )
            ofertas = await coletar_ofertas_promobit()

        assert ofertas == []

    async def test_json_malformado_retorna_vazio(self):
        html = (
            '<script id="__NEXT_DATA__" type="application/json">{quebrado</script>'
        )
        with respx.mock:
            respx.get(HOMEPAGE_URL).mock(return_value=httpx.Response(200, text=html))
            ofertas = await coletar_ofertas_promobit()

        assert ofertas == []

    async def test_erro_http_retorna_vazio(self):
        with respx.mock:
            respx.get(HOMEPAGE_URL).mock(return_value=httpx.Response(500))
            ofertas = await coletar_ofertas_promobit()

        assert ofertas == []

    async def test_timeout_retorna_vazio(self):
        with respx.mock:
            respx.get(HOMEPAGE_URL).mock(side_effect=httpx.TimeoutException("timeout"))
            ofertas = await coletar_ofertas_promobit()

        assert ofertas == []

    async def test_uma_oferta_invalida_nao_derruba_as_outras(self):
        brutas = [_oferta_bruta(offerSlug="ok-1"), {"offerTitle": None}, _oferta_bruta(offerSlug="ok-2")]
        html = _html_com_ofertas(brutas)
        with respx.mock:
            respx.get(HOMEPAGE_URL).mock(return_value=httpx.Response(200, text=html))
            ofertas = await coletar_ofertas_promobit()

        assert len(ofertas) == 2
