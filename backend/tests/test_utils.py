"""Testes para scrapers/utils.py — funções puras de parsing e scoring."""

import pytest

from scrapers.utils import calcular_quality_score, converter_preco_br, limpar_html


class TestConverterPrecoBr:
    @pytest.mark.parametrize(
        "entrada, esperado",
        [
            ("1.299,90", 1299.90),
            ("270", 270.0),
            ("5.427", 5427.0),
            ("29,00", 29.0),
            ("7,88", 7.88),
            ("1.916", 1916.0),
            (270, 270.0),
            (189.9, 189.9),
        ],
    )
    def test_formatos_validos(self, entrada, esperado):
        assert converter_preco_br(entrada) == pytest.approx(esperado)

    @pytest.mark.parametrize("entrada", [None, "", "grátis", "abc", 0, -10, "0"])
    def test_valores_invalidos_retornam_none(self, entrada):
        assert converter_preco_br(entrada) is None


class TestLimparHtml:
    def test_remove_tags(self):
        assert limpar_html("<p>Olá <b>mundo</b></p>") == "Olá mundo"

    def test_decodifica_entidades(self):
        assert limpar_html("Pé&nbsp;de&nbsp;moleque &amp; cia") == "Pé de moleque & cia"

    def test_colapsa_espacos(self):
        assert limpar_html("muito   espaço\n\naqui") == "muito espaço aqui"

    def test_string_vazia_ou_none(self):
        assert limpar_html("") == ""
        assert limpar_html(None) == ""


class TestCalcularQualityScore:
    def test_sem_desconto_nem_popularidade(self):
        assert calcular_quality_score(None) == 0.0

    def test_so_desconto(self):
        # score = desconto * 0.8 (sem sinal de popularidade)
        assert calcular_quality_score(50.0) == pytest.approx(40.0)

    def test_desconto_e_popularidade(self):
        score = calcular_quality_score(50.0, sinal_popularidade=100.0)
        assert score == pytest.approx(50.0 * 0.8 + 100.0 * 0.2)

    def test_nunca_ultrapassa_100(self):
        assert calcular_quality_score(500.0, sinal_popularidade=500.0) == 100.0

    def test_nunca_fica_negativo(self):
        assert calcular_quality_score(0.0, sinal_popularidade=0.0) == 0.0
