"""
Testes para bot/main_bot.py.

Cobre as funções de inicialização isoladas (`_configurar_logging`,
`_inicializar_redis`, `_inicializar_banco`, `_executar_pipeline_inicial`).

`_main()`/`main()` não são testados aqui de propósito: são um laço
"aguarda sinal de SO e encerra" que orquestra funções já testadas em outro
lugar — o valor de simular SIGINT/SIGTERM num teste automatizado é baixo
frente ao esforço de mockar tudo (scheduler, sinais, loop infinito).
"""

import logging

import pytest

import bot.main_bot as main_bot
from bot import dedup


class FakeSettings:
    def __init__(self, **overrides):
        self.log_level = "INFO"
        self.log_format = "texto"
        self.__dict__.update(overrides)


class TestConfigurarLogging:
    def test_configura_nivel_a_partir_das_settings(self, monkeypatch):
        monkeypatch.setattr(main_bot, "get_settings", lambda: FakeSettings(log_level="WARNING"))
        main_bot._configurar_logging()

        assert logging.getLogger("httpx").level == logging.WARNING
        assert logging.getLogger("telegram").level == logging.WARNING

    def test_nivel_invalido_cai_para_info(self, monkeypatch):
        monkeypatch.setattr(main_bot, "get_settings", lambda: FakeSettings(log_level="XPTO"))
        main_bot._configurar_logging()  # não deve lançar


class TestInicializarRedis:
    async def test_sucesso(self):
        await main_bot._inicializar_redis()
        assert dedup._redis_client is not None
        await dedup.fechar_redis()

    async def test_falha_nao_propaga_excecao(self, monkeypatch):
        async def _init_redis_falho():
            raise ConnectionError("redis fora do ar")

        monkeypatch.setattr(dedup, "init_redis", _init_redis_falho)
        await main_bot._inicializar_redis()  # não deve lançar


class TestInicializarBanco:
    async def test_sucesso(self):
        await main_bot._inicializar_banco()  # não deve lançar

    async def test_falha_propaga_excecao(self, monkeypatch):
        from core import database

        async def _init_db_falho():
            raise ConnectionError("banco fora do ar")

        monkeypatch.setattr(database, "init_db", _init_db_falho)

        with pytest.raises(ConnectionError):
            await main_bot._inicializar_banco()


class TestExecutarPipelineInicial:
    async def test_sucesso_chama_pipeline(self, monkeypatch):
        chamado = {"vezes": 0}

        async def _fake_pipeline():
            chamado["vezes"] += 1

        from bot import scheduler

        monkeypatch.setattr(scheduler, "executar_pipeline_agora", _fake_pipeline)
        await main_bot._executar_pipeline_inicial()

        assert chamado["vezes"] == 1

    async def test_falha_no_pipeline_nao_propaga(self, monkeypatch):
        from bot import scheduler

        async def _pipeline_com_erro():
            raise RuntimeError("erro no pipeline inicial")

        monkeypatch.setattr(scheduler, "executar_pipeline_agora", _pipeline_com_erro)
        await main_bot._executar_pipeline_inicial()  # não deve lançar
