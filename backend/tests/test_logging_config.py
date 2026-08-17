"""Testes para core/logging_config.py — formatação de logs (texto e JSON)."""

import json
import logging

from core.logging_config import JsonFormatter, configurar_logging


def _criar_record(**overrides) -> logging.LogRecord:
    base = dict(
        name="scrapers.pelando_scraper",
        level=logging.INFO,
        pathname="pelando_scraper.py",
        lineno=42,
        msg="Coleta finalizada",
        args=(),
        exc_info=None,
    )
    base.update(overrides)
    return logging.LogRecord(**base)


class TestJsonFormatter:
    def test_produz_json_valido_com_campos_basicos(self):
        record = _criar_record()
        saida = JsonFormatter().format(record)
        dados = json.loads(saida)

        assert dados["level"] == "INFO"
        assert dados["service"] == "scrapers.pelando_scraper"
        assert dados["message"] == "Coleta finalizada"
        assert "timestamp" in dados

    def test_preserva_campos_extras(self):
        record = _criar_record()
        record.source = "pelando"
        record.event = "fetch_failed"
        record.duration_ms = 421

        dados = json.loads(JsonFormatter().format(record))

        assert dados["source"] == "pelando"
        assert dados["event"] == "fetch_failed"
        assert dados["duration_ms"] == 421

    def test_inclui_exception_quando_presente(self):
        try:
            raise ValueError("erro de teste")
        except ValueError:
            import sys

            record = _criar_record(exc_info=sys.exc_info())

        dados = json.loads(JsonFormatter().format(record))
        assert "ValueError" in dados["exception"]
        assert "erro de teste" in dados["exception"]

    def test_mensagem_com_placeholders_e_formatada(self):
        record = _criar_record(msg="Encontradas %d ofertas em %s", args=(5, "pelando"))
        dados = json.loads(JsonFormatter().format(record))
        assert dados["message"] == "Encontradas 5 ofertas em pelando"

    def test_saida_e_uma_linha_unica(self):
        record = _criar_record(msg="Mensagem\ncom quebra de linha")
        saida = JsonFormatter().format(record)
        assert "\n" not in saida.strip("\n")


class TestConfigurarLogging:
    def test_formato_texto_nao_lanca(self):
        configurar_logging(nivel="DEBUG", formato="texto")
        logging.getLogger("teste").info("linha de teste")

    def test_formato_json_produz_saida_json(self, capsys):
        configurar_logging(nivel="INFO", formato="json")
        logging.getLogger("teste.json").warning("aviso de teste")

        saida = capsys.readouterr().out.strip()
        dados = json.loads(saida.splitlines()[-1])
        assert dados["level"] == "WARNING"
        assert dados["message"] == "aviso de teste"

    def test_nivel_invalido_cai_para_info(self):
        configurar_logging(nivel="NIVEL_INEXISTENTE", formato="texto")
        assert logging.getLogger().level == logging.INFO

    def test_reduz_verbosidade_de_libs_externas(self):
        configurar_logging(nivel="DEBUG", formato="texto")
        assert logging.getLogger("httpx").level == logging.WARNING
        assert logging.getLogger("telegram").level == logging.WARNING
