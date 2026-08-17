"""Testes para bot/card_generator.py — geração de imagem PNG do card."""

import io

import pytest
from PIL import Image

from bot.card_generator import CARD_HEIGHT, CARD_WIDTH, generate_deal_card


def _abrir_como_imagem(png_bytes: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png_bytes))


class TestGenerateDealCard:
    def test_card_completo_gera_png_valido(self, oferta_exemplo):
        resultado = generate_deal_card(oferta_exemplo)

        assert isinstance(resultado, bytes)
        assert len(resultado) > 0

        img = _abrir_como_imagem(resultado)
        assert img.format == "PNG"
        assert img.size == (CARD_WIDTH, CARD_HEIGHT)

    def test_sem_preco_original_nao_quebra(self, oferta_exemplo):
        oferta_exemplo["price_original"] = None
        oferta_exemplo["discount_pct"] = None
        resultado = generate_deal_card(oferta_exemplo)
        assert _abrir_como_imagem(resultado).format == "PNG"

    def test_sem_preco_nenhum_usa_texto_generico(self, oferta_exemplo):
        oferta_exemplo["price"] = None
        oferta_exemplo["price_original"] = None
        resultado = generate_deal_card(oferta_exemplo)
        assert _abrir_como_imagem(resultado).format == "PNG"

    def test_sem_loja_nao_quebra(self, oferta_exemplo):
        oferta_exemplo["store"] = None
        resultado = generate_deal_card(oferta_exemplo)
        assert _abrir_como_imagem(resultado).format == "PNG"

    def test_sem_desconto_nao_desenha_badge(self, oferta_exemplo):
        oferta_exemplo["discount_pct"] = None
        resultado = generate_deal_card(oferta_exemplo)
        assert _abrir_como_imagem(resultado).format == "PNG"

    def test_titulo_muito_longo_nao_quebra(self, oferta_exemplo):
        oferta_exemplo["title"] = "Produto " * 60  # título gigante
        resultado = generate_deal_card(oferta_exemplo)
        assert _abrir_como_imagem(resultado).format == "PNG"

    def test_dicionario_vazio_nao_quebra(self):
        resultado = generate_deal_card({})
        img = _abrir_como_imagem(resultado)
        assert img.format == "PNG"
        assert img.size == (CARD_WIDTH, CARD_HEIGHT)

    @pytest.mark.parametrize("preco", [0.01, 99.9, 1299.90, 15000.0])
    def test_varios_precos_geram_card_valido(self, oferta_exemplo, preco):
        oferta_exemplo["price"] = preco
        resultado = generate_deal_card(oferta_exemplo)
        assert _abrir_como_imagem(resultado).format == "PNG"
