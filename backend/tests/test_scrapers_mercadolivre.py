"""Testes para scrapers/mercadolivre.py — API pública/OAuth2 do Mercado Livre."""

import httpx
import pytest
import respx

from scrapers import mercadolivre, resiliencia
from scrapers.mercadolivre import (
    FONTE,
    ML_SEARCH_URL,
    ML_TOKEN_URL,
    _normalizar_item,
    buscar_mercadolivre,
)


@pytest.fixture(autouse=True)
def _resetar_cache_de_token():
    """O cache de token OAuth2 é global no módulo — evita vazar entre testes."""
    mercadolivre._token_cache = {"access_token": None, "expires_at": 0}
    yield
    mercadolivre._token_cache = {"access_token": None, "expires_at": 0}


@pytest.fixture(autouse=True)
def _resiliencia_sem_atrito(monkeypatch):
    """Sem sleep real no retry, e circuit breaker limpo antes/depois de cada teste."""
    resiliencia.circuit_breaker.resetar()

    async def _sleep_instantaneo(*_a, **_kw):
        return None

    monkeypatch.setattr(resiliencia.asyncio, "sleep", _sleep_instantaneo)
    yield
    resiliencia.circuit_breaker.resetar()


def _item_ml(**overrides) -> dict:
    base = {
        "id": "MLB123",
        "title": "Echo Dot 5ª Geração",
        "price": 279.0,
        "original_price": 399.0,
        "permalink": "https://www.mercadolivre.com.br/echo-dot/p/MLB12345",
        "thumbnail": "http://http2.mlstatic.com/D_NQ_NP_exemplo-I.jpg",
        "available_quantity": 10,
        "condition": "new",
        "shipping": {"free_shipping": False},
        "reviews": {"rating_average": 4.7, "total": 12340},
    }
    base.update(overrides)
    return base


class TestNormalizarItem:
    def test_item_valido(self):
        oferta = _normalizar_item(_item_ml())
        assert oferta is not None
        assert oferta.name == "Echo Dot 5ª Geração"
        assert oferta.price == 279.0
        assert oferta.price_old == 399.0
        assert oferta.discount_pct == pytest.approx(30.08, abs=0.01)
        assert oferta.rating == 4.7
        assert oferta.rating_count == 12340
        assert oferta.in_stock is True

    @pytest.mark.parametrize("campo", ["title", "price", "permalink"])
    def test_sem_campo_obrigatorio_retorna_none(self, campo):
        item = _item_ml()
        item[campo] = None
        assert _normalizar_item(item) is None

    def test_preco_zero_retorna_none(self):
        assert _normalizar_item(_item_ml(price=0)) is None

    def test_preco_original_menor_ou_igual_nao_e_desconto(self):
        oferta = _normalizar_item(_item_ml(original_price=100.0, price=279.0))
        assert oferta.price_old is None
        assert oferta.discount_pct is None

    def test_imagem_convertida_para_https_e_tamanho_maior(self):
        oferta = _normalizar_item(_item_ml())
        assert oferta.image_url == "https://http2.mlstatic.com/D_NQ_NP_exemplo-W.jpg"

    def test_produto_usado_adiciona_sufixo(self):
        oferta = _normalizar_item(_item_ml(condition="used"))
        assert oferta.name.endswith("(Usado)")

    def test_frete_gratis_adiciona_sufixo(self):
        oferta = _normalizar_item(_item_ml(shipping={"free_shipping": True}))
        assert "[Frete Grátis]" in oferta.name

    def test_sem_estoque(self):
        oferta = _normalizar_item(_item_ml(available_quantity=0))
        assert oferta.in_stock is False

    def test_sem_reviews_fica_sem_rating(self):
        item = _item_ml()
        item.pop("reviews")
        oferta = _normalizar_item(item)
        assert oferta.rating is None
        assert oferta.rating_count is None


class TestBuscarMercadoLivre:
    async def test_busca_sem_credenciais_usa_fallback_publico(self):
        with respx.mock:
            rota = respx.get(ML_SEARCH_URL).mock(
                return_value=httpx.Response(
                    200, json={"results": [_item_ml()], "paging": {"total": 1}}
                )
            )
            ofertas = await buscar_mercadolivre("echo dot")

        assert len(ofertas) == 1
        assert "Authorization" not in rota.calls.last.request.headers

    async def test_limit_e_limitado_ao_maximo(self):
        with respx.mock:
            rota = respx.get(ML_SEARCH_URL).mock(
                return_value=httpx.Response(200, json={"results": []})
            )
            await buscar_mercadolivre("produto", limit=999)

        params = dict(httpx.QueryParams(rota.calls.last.request.url.params))
        assert params["limit"] == "50"

    async def test_limit_minimo_e_um(self):
        with respx.mock:
            rota = respx.get(ML_SEARCH_URL).mock(
                return_value=httpx.Response(200, json={"results": []})
            )
            await buscar_mercadolivre("produto", limit=-5)

        params = dict(httpx.QueryParams(rota.calls.last.request.url.params))
        assert params["limit"] == "1"

    async def test_itens_invalidos_sao_filtrados(self):
        with respx.mock:
            respx.get(ML_SEARCH_URL).mock(
                return_value=httpx.Response(
                    200,
                    json={"results": [_item_ml(), {"id": "sem-dados"}]},
                )
            )
            ofertas = await buscar_mercadolivre("produto")

        assert len(ofertas) == 1

    async def test_timeout_retorna_lista_vazia(self):
        with respx.mock:
            respx.get(ML_SEARCH_URL).mock(side_effect=httpx.TimeoutException("timeout"))
            ofertas = await buscar_mercadolivre("produto")

        assert ofertas == []

    async def test_erro_http_retorna_lista_vazia(self):
        with respx.mock:
            respx.get(ML_SEARCH_URL).mock(return_value=httpx.Response(500))
            ofertas = await buscar_mercadolivre("produto")

        assert ofertas == []

    async def test_erro_de_rede_retorna_lista_vazia(self):
        with respx.mock:
            respx.get(ML_SEARCH_URL).mock(
                side_effect=httpx.ConnectError("conexão recusada")
            )
            ofertas = await buscar_mercadolivre("produto")

        assert ofertas == []

    async def test_com_credenciais_usa_token_no_header(self, monkeypatch):
        class FakeSettings:
            ml_client_id = "id-fake"
            ml_client_secret = "secret-fake"

        monkeypatch.setattr(mercadolivre, "get_settings", lambda: FakeSettings())

        with respx.mock:
            respx.post(ML_TOKEN_URL).mock(
                return_value=httpx.Response(
                    200, json={"access_token": "token-123", "expires_in": 21600}
                )
            )
            rota_busca = respx.get(ML_SEARCH_URL).mock(
                return_value=httpx.Response(200, json={"results": []})
            )
            await buscar_mercadolivre("produto")

        assert rota_busca.calls.last.request.headers["Authorization"] == "Bearer token-123"

    async def test_token_rejeitado_com_403_refaz_sem_auth(self, monkeypatch):
        class FakeSettings:
            ml_client_id = "id-fake"
            ml_client_secret = "secret-fake"

        monkeypatch.setattr(mercadolivre, "get_settings", lambda: FakeSettings())

        with respx.mock:
            respx.post(ML_TOKEN_URL).mock(
                return_value=httpx.Response(
                    200, json={"access_token": "token-invalido", "expires_in": 21600}
                )
            )
            respx.get(ML_SEARCH_URL).mock(
                side_effect=[
                    httpx.Response(403),
                    httpx.Response(200, json={"results": [_item_ml()]}),
                ]
            )
            ofertas = await buscar_mercadolivre("produto")

        assert len(ofertas) == 1

    async def test_falha_ao_obter_token_cai_no_fallback_publico(self, monkeypatch):
        class FakeSettings:
            ml_client_id = "id-fake"
            ml_client_secret = "secret-fake"

        monkeypatch.setattr(mercadolivre, "get_settings", lambda: FakeSettings())

        with respx.mock:
            respx.post(ML_TOKEN_URL).mock(return_value=httpx.Response(500))
            rota_busca = respx.get(ML_SEARCH_URL).mock(
                return_value=httpx.Response(200, json={"results": []})
            )
            await buscar_mercadolivre("produto")

        assert "Authorization" not in rota_busca.calls.last.request.headers


class TestResiliencia:
    async def test_falha_transiente_seguida_de_sucesso_e_recuperada_pelo_retry(self):
        with respx.mock:
            respx.get(ML_SEARCH_URL).mock(
                side_effect=[
                    httpx.Response(503),
                    httpx.Response(200, json={"results": [_item_ml()]}),
                ]
            )
            ofertas = await buscar_mercadolivre("produto")

        assert len(ofertas) == 1

    async def test_falhas_consecutivas_abrem_o_circuit_breaker(self):
        with respx.mock:
            respx.get(ML_SEARCH_URL).mock(return_value=httpx.Response(500))
            for _ in range(resiliencia.circuit_breaker.limite_falhas):
                await buscar_mercadolivre("produto")

        assert resiliencia.circuit_breaker.permite_chamada(FONTE) is False

    async def test_circuit_breaker_aberto_pula_a_busca(self):
        resiliencia.circuit_breaker.registrar_falha(FONTE)
        resiliencia.circuit_breaker.registrar_falha(FONTE)
        resiliencia.circuit_breaker.registrar_falha(FONTE)

        with respx.mock:
            rota = respx.get(ML_SEARCH_URL).mock(return_value=httpx.Response(200))
            ofertas = await buscar_mercadolivre("produto")

        assert ofertas == []
        assert rota.called is False
