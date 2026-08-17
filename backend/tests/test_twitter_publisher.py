"""
Testes para bot/twitter_publisher.py.

Cobre apenas as funções puras (formatação de texto). A automação via
navegador (login, publicação) não é testada aqui de propósito — exigiria
um Chromium real e simular o DOM do X, o que pertenceria a um suite de
testes end-to-end separado, não a testes unitários. `init_twitter()` com
TWITTER_ENABLED=false (padrão) é coberto indiretamente pelos testes do
scheduler.
"""

from bot.twitter_publisher import TWEET_MAX_LEN, _formatar_preco_br, _montar_texto


class TestFormatarPrecoBr:
    def test_valor_none(self):
        assert _formatar_preco_br(None) == ""

    def test_valor_com_milhar(self):
        assert _formatar_preco_br(5427.0) == "R$ 5.427,00"


class TestMontarTexto:
    def test_texto_completo(self, oferta_exemplo):
        texto = _montar_texto(oferta_exemplo)
        assert oferta_exemplo["title"] in texto
        assert "R$ 189,90" in texto  # só o preço atual — twitter não mostra "de/por"
        assert "-36% OFF" in texto
        assert oferta_exemplo["url"] in texto

    def test_usa_affiliate_url_quando_disponivel(self, oferta_exemplo):
        oferta_exemplo["affiliate_url"] = "https://loja.com/produto?tag=meuid"
        texto = _montar_texto(oferta_exemplo)
        assert "https://loja.com/produto?tag=meuid" in texto
        assert oferta_exemplo["url"] not in texto

    def test_sem_preco_nem_desconto(self):
        texto = _montar_texto({"title": "Produto", "url": "https://x.com/produto"})
        assert "💰" not in texto
        assert "📉" not in texto

    def test_nunca_ultrapassa_280_caracteres(self):
        deal = {
            "title": "Produto " * 60,
            "price": 5427.0,
            "discount_pct": 37.0,
            "url": "https://www.casasbahia.com.br/notebook-exemplo-com-slug-bem-grande/p/123",
        }
        texto = _montar_texto(deal)
        assert len(texto) <= TWEET_MAX_LEN

    def test_titulo_truncado_preserva_preco_e_link(self):
        deal = {
            "title": "X" * 400,
            "price": 100.0,
            "url": "https://exemplo.com/produto",
        }
        texto = _montar_texto(deal)
        assert "R$ 100,00" in texto
        assert "https://exemplo.com/produto" in texto
        assert "…" in texto
        assert len(texto) <= TWEET_MAX_LEN

    def test_titulo_curto_nao_e_truncado(self, oferta_exemplo):
        texto = _montar_texto(oferta_exemplo)
        assert "…" not in texto
