"""
Testes para bot/scheduler.py — orquestração do pipeline de coleta e publicação.

Os scrapers e os publishers (Telegram/Twitter) são sempre mockados aqui —
já têm suíte própria (test_scrapers_*.py, test_telegram_publisher.py,
test_twitter_publisher.py). O que se testa neste arquivo é a orquestração:
dedup, filtros, persistência, contabilização e resiliência a falhas.
"""

import asyncio
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select

import bot.scheduler as scheduler
from bot import dedup
from core.database import AsyncSessionLocal
from core.models import Deal

# Referência real, capturada antes de qualquer monkeypatch de asyncio.sleep
# (usada só para dar um "yield" de verdade ao loop em testes que precisam).
_sleep_real = asyncio.sleep


class FakeSettings:
    """Settings controláveis por teste, sem depender do .env real."""

    def __init__(self, **overrides):
        self.deal_min_discount_pct = 15.0
        self.telegram_post_cooldown_seconds = 120
        self.twitter_enabled = False
        self.deal_check_interval_minutes = 5
        self.__dict__.update(overrides)


@pytest.fixture(autouse=True)
def _sem_cooldown_real(monkeypatch):
    """Evita esperar o cooldown de verdade (120s) durante os testes."""

    async def _sleep_instantaneo(*_args, **_kwargs):
        return None

    monkeypatch.setattr(scheduler.asyncio, "sleep", _sleep_instantaneo)


@pytest_asyncio.fixture(autouse=True)
async def _redis_dedup():
    """Redis real (DB de testes) para o dedup — limpo antes/depois de cada teste."""
    client = await dedup.init_redis()
    await client.flushdb()
    yield client
    await client.flushdb()
    await dedup.fechar_redis()


def _oferta(**overrides) -> dict[str, Any]:
    base = {
        "source": "pelando",
        "title": "Notebook Gamer Exemplo",
        "description": None,
        "price": 100.0,
        "price_original": 200.0,
        "discount_pct": 50.0,
        "url": "https://exemplo.com/produto-unico",
        "affiliate_url": None,
        "image_url": None,
        "store": "Amazon",
        "quality_score": 40.0,
        "status": "pending",
    }
    base.update(overrides)
    return base


async def _buscar_deal_por_url(url: str) -> Deal | None:
    async with AsyncSessionLocal() as session:
        resultado = await session.execute(select(Deal).where(Deal.url == url))
        return resultado.scalar_one_or_none()


class TestFiltrarOfertasNovas:
    async def test_mantem_oferta_valida(self, monkeypatch):
        monkeypatch.setattr(scheduler, "get_settings", lambda: FakeSettings())
        resultado = await scheduler._filtrar_ofertas_novas([_oferta()])
        assert len(resultado) == 1

    async def test_remove_sem_url(self, monkeypatch):
        monkeypatch.setattr(scheduler, "get_settings", lambda: FakeSettings())
        resultado = await scheduler._filtrar_ofertas_novas([_oferta(url="")])
        assert resultado == []

    async def test_remove_sem_titulo(self, monkeypatch):
        monkeypatch.setattr(scheduler, "get_settings", lambda: FakeSettings())
        resultado = await scheduler._filtrar_ofertas_novas([_oferta(title="")])
        assert resultado == []

    async def test_remove_ja_postada(self, monkeypatch):
        monkeypatch.setattr(scheduler, "get_settings", lambda: FakeSettings())
        oferta = _oferta()
        await dedup.marcar_postado(oferta["url"])
        resultado = await scheduler._filtrar_ofertas_novas([oferta])
        assert resultado == []

    async def test_remove_desconto_abaixo_do_minimo(self, monkeypatch):
        monkeypatch.setattr(
            scheduler, "get_settings", lambda: FakeSettings(deal_min_discount_pct=60.0)
        )
        resultado = await scheduler._filtrar_ofertas_novas([_oferta(discount_pct=50.0)])
        assert resultado == []

    async def test_mantem_sem_info_de_desconto(self, monkeypatch):
        monkeypatch.setattr(
            scheduler, "get_settings", lambda: FakeSettings(deal_min_discount_pct=60.0)
        )
        resultado = await scheduler._filtrar_ofertas_novas([_oferta(discount_pct=None)])
        assert len(resultado) == 1


class TestSalvarDealNoBanco:
    async def test_salva_com_todos_os_campos(self):
        oferta = _oferta(store="Kabum", affiliate_url="https://exemplo.com/afiliado")
        deal = await scheduler._salvar_deal_no_banco(oferta)

        assert deal is not None
        assert deal.title == oferta["title"]
        assert deal.store == "Kabum"
        assert deal.affiliate_url == "https://exemplo.com/afiliado"
        assert deal.status == "pending"


class TestAtualizarStatusPublicacao:
    async def test_sucesso_no_telegram(self):
        deal = await scheduler._salvar_deal_no_banco(_oferta())
        await scheduler._atualizar_status_publicacao(deal.id, tg_message_id=42)

        async with AsyncSessionLocal() as session:
            atualizado = await session.get(Deal, deal.id)
            assert atualizado.published_tg is True
            assert atualizado.tg_message_id == 42
            assert atualizado.status == "published"
            assert atualizado.published_twitter is False

    async def test_sucesso_no_twitter(self):
        deal = await scheduler._salvar_deal_no_banco(_oferta())
        await scheduler._atualizar_status_publicacao(deal.id, tg_message_id=None, twitter_ok=True)

        async with AsyncSessionLocal() as session:
            atualizado = await session.get(Deal, deal.id)
            assert atualizado.published_twitter is True
            assert atualizado.status == "published"

    async def test_falha_em_ambos_mantem_pendente(self):
        deal = await scheduler._salvar_deal_no_banco(_oferta())
        await scheduler._atualizar_status_publicacao(deal.id, tg_message_id=None, twitter_ok=False)

        async with AsyncSessionLocal() as session:
            atualizado = await session.get(Deal, deal.id)
            assert atualizado.status == "pending"
            assert atualizado.published_tg is False
            assert atualizado.published_twitter is False


@pytest.fixture
def mocks_publicacao(monkeypatch):
    """Mocka scrapers e publishers, retornando os fakes pra inspeção nos testes."""

    class Mocks:
        pelando: list[dict] = []
        promobit: list[dict] = []
        telegram_resultado: dict[str, int | None] = {}
        twitter_resultado: dict[str, bool] = {}
        chamadas_telegram: list[str] = []
        chamadas_twitter: list[str] = []

    m = Mocks()

    class _FakeScraper:
        def __init__(self, nome, obter_ofertas):
            self.nome = nome
            self._obter_ofertas = obter_ofertas

        async def fetch(self, limit=12):
            return self._obter_ofertas()

    monkeypatch.setattr(
        scheduler,
        "SCRAPERS",
        [
            _FakeScraper("pelando", lambda: m.pelando),
            _FakeScraper("promobit", lambda: m.promobit),
        ],
    )

    async def _fake_telegram(oferta, _card):
        m.chamadas_telegram.append(oferta["url"])
        return m.telegram_resultado.get(oferta["url"], 1)  # sucesso por padrão

    async def _fake_twitter(oferta, _card):
        m.chamadas_twitter.append(oferta["url"])
        return m.twitter_resultado.get(oferta["url"], True)

    async def _fake_init_twitter():
        return scheduler_settings_atual.twitter_enabled

    monkeypatch.setattr(scheduler, "publicar_no_telegram", _fake_telegram)
    monkeypatch.setattr(scheduler, "publicar_no_twitter", _fake_twitter)
    monkeypatch.setattr(scheduler, "init_twitter", _fake_init_twitter)

    fechar_chamado = {"vezes": 0}

    async def _fake_fechar_twitter():
        fechar_chamado["vezes"] += 1

    monkeypatch.setattr(scheduler, "fechar_twitter", _fake_fechar_twitter)
    m.fechar_chamado = fechar_chamado

    scheduler_settings_atual = FakeSettings()
    monkeypatch.setattr(scheduler, "get_settings", lambda: scheduler_settings_atual)
    m.settings = scheduler_settings_atual

    return m


class TestExecutarPipeline:
    async def test_pipeline_completo_publica_e_marca_dedup(self, mocks_publicacao):
        mocks_publicacao.pelando = [_oferta(url="https://exemplo.com/produto-1")]
        mocks_publicacao.promobit = [_oferta(url="https://exemplo.com/produto-2", title="Outro")]

        await scheduler.executar_pipeline()

        deal1 = await _buscar_deal_por_url("https://exemplo.com/produto-1")
        deal2 = await _buscar_deal_por_url("https://exemplo.com/produto-2")
        assert deal1.status == "published"
        assert deal2.status == "published"
        assert await dedup.ja_foi_postado("https://exemplo.com/produto-1") is True
        assert await dedup.ja_foi_postado("https://exemplo.com/produto-2") is True

    async def test_sem_ofertas_nao_processa_nada(self, mocks_publicacao):
        mocks_publicacao.pelando = []
        mocks_publicacao.promobit = []

        await scheduler.executar_pipeline()  # não deve lançar

    async def test_todas_ofertas_filtradas_nao_processa_nada(self, mocks_publicacao):
        # coletadas, porém todas abaixo do desconto mínimo — filtradas antes de processar
        mocks_publicacao.pelando = [_oferta(discount_pct=1.0)]

        await scheduler.executar_pipeline()  # não deve lançar

        assert mocks_publicacao.chamadas_telegram == []

    async def test_uma_fonte_falhando_nao_impede_a_outra(self, mocks_publicacao, monkeypatch):
        class _ScraperComErro:
            nome = "pelando"

            async def fetch(self, limit=12):
                raise RuntimeError("Pelando fora do ar")

        scheduler.SCRAPERS[0] = _ScraperComErro()
        mocks_publicacao.promobit = [_oferta(url="https://exemplo.com/produto-resiliente")]

        await scheduler.executar_pipeline()

        deal = await _buscar_deal_por_url("https://exemplo.com/produto-resiliente")
        assert deal is not None
        assert deal.status == "published"

    async def test_falha_no_telegram_mas_sucesso_no_card_nao_publica_sem_twitter(
        self, mocks_publicacao
    ):
        url = "https://exemplo.com/produto-falha-telegram"
        mocks_publicacao.pelando = [_oferta(url=url)]
        mocks_publicacao.telegram_resultado = {url: None}  # falha

        await scheduler.executar_pipeline()

        deal = await _buscar_deal_por_url(url)
        assert deal.status == "pending"
        assert await dedup.ja_foi_postado(url) is False

    async def test_twitter_desabilitado_nao_e_chamado(self, mocks_publicacao):
        mocks_publicacao.settings.twitter_enabled = False
        mocks_publicacao.pelando = [_oferta(url="https://exemplo.com/produto-sem-twitter")]

        await scheduler.executar_pipeline()

        assert mocks_publicacao.chamadas_twitter == []
        assert mocks_publicacao.fechar_chamado["vezes"] == 0

    async def test_twitter_habilitado_e_chamado_e_fechado(self, mocks_publicacao):
        mocks_publicacao.settings.twitter_enabled = True
        url = "https://exemplo.com/produto-com-twitter"
        mocks_publicacao.pelando = [_oferta(url=url)]

        await scheduler.executar_pipeline()

        assert mocks_publicacao.chamadas_twitter == [url]
        assert mocks_publicacao.fechar_chamado["vezes"] == 1

        deal = await _buscar_deal_por_url(url)
        assert deal.published_twitter is True

    async def test_twitter_falha_mas_telegram_ok_ainda_publica(self, mocks_publicacao):
        mocks_publicacao.settings.twitter_enabled = True
        url = "https://exemplo.com/produto-twitter-falha"
        mocks_publicacao.pelando = [_oferta(url=url)]
        mocks_publicacao.twitter_resultado = {url: False}

        await scheduler.executar_pipeline()

        deal = await _buscar_deal_por_url(url)
        assert deal.status == "published"
        assert deal.published_tg is True
        assert deal.published_twitter is False

    async def test_erro_ao_gerar_card_nao_derruba_as_outras_ofertas(
        self, mocks_publicacao, monkeypatch
    ):
        url_com_erro = "https://exemplo.com/produto-card-quebrado"
        url_ok = "https://exemplo.com/produto-card-ok"
        mocks_publicacao.pelando = [
            _oferta(url=url_com_erro, title="Quebrado"),
            _oferta(url=url_ok, title="OK"),
        ]

        def _card_generator_falho(deal):
            if deal["url"] == url_com_erro:
                raise ValueError("falha simulada no Pillow")
            return b"fake-png"

        monkeypatch.setattr(scheduler, "generate_deal_card", _card_generator_falho)

        await scheduler.executar_pipeline()

        assert await _buscar_deal_por_url(url_ok) is not None
        assert (await _buscar_deal_por_url(url_ok)).status == "published"
        # a oferta com erro foi salva no banco (etapa anterior à geração do card)
        # mas nunca chegou a ser publicada
        assert url_com_erro not in mocks_publicacao.chamadas_telegram

    async def test_ofertas_ordenadas_por_quality_score_antes_de_publicar(
        self, mocks_publicacao
    ):
        mocks_publicacao.pelando = [
            _oferta(url="https://exemplo.com/baixo", quality_score=10.0),
            _oferta(url="https://exemplo.com/alto", quality_score=90.0),
        ]

        await scheduler.executar_pipeline()

        assert mocks_publicacao.chamadas_telegram == [
            "https://exemplo.com/alto",
            "https://exemplo.com/baixo",
        ]

    async def test_twitter_habilitado_mas_sessao_falha_avisa_e_segue_so_telegram(
        self, mocks_publicacao, monkeypatch
    ):
        mocks_publicacao.settings.twitter_enabled = True
        url = "https://exemplo.com/produto-twitter-indisponivel"
        mocks_publicacao.pelando = [_oferta(url=url)]

        async def _init_twitter_falha():
            return False

        monkeypatch.setattr(scheduler, "init_twitter", _init_twitter_falha)

        await scheduler.executar_pipeline()

        assert mocks_publicacao.chamadas_twitter == []
        deal = await _buscar_deal_por_url(url)
        assert deal.status == "published"  # continua indo pro Telegram normalmente

    async def test_erro_inesperado_no_publisher_e_contabilizado_sem_derrubar_pipeline(
        self, mocks_publicacao, monkeypatch
    ):
        url_com_bug = "https://exemplo.com/produto-bug"
        url_ok = "https://exemplo.com/produto-normal"
        mocks_publicacao.pelando = [
            _oferta(url=url_com_bug, title="Com bug"),
            _oferta(url=url_ok, title="Normal"),
        ]

        async def _telegram_com_bug(oferta, _card):
            if oferta["url"] == url_com_bug:
                raise RuntimeError("bug inesperado no publisher")
            return 1

        monkeypatch.setattr(scheduler, "publicar_no_telegram", _telegram_com_bug)

        publicadas, erros = await scheduler._processar_ofertas(
            await scheduler._filtrar_ofertas_novas(mocks_publicacao.pelando),
            twitter_pronto=False,
            settings=mocks_publicacao.settings,
        )

        assert publicadas == 1
        assert erros == 1
        assert (await _buscar_deal_por_url(url_ok)).status == "published"


class TestSalvarDealComErroDeBanco:
    async def test_titulo_maior_que_a_coluna_retorna_none(self):
        oferta = _oferta(title="X" * 600)  # coluna é VARCHAR(500)
        resultado = await scheduler._salvar_deal_no_banco(oferta)
        assert resultado is None


class TestAtualizarStatusComErroDeBanco:
    async def test_deal_id_invalido_nao_lanca_excecao(self):
        # não é um UUID válido — dispara erro no banco, que deve ser
        # capturado internamente (a função não deve propagar a exceção)
        await scheduler._atualizar_status_publicacao("nao-e-um-uuid", tg_message_id=1)


class TestCicloDeVidaDoScheduler:
    def test_criar_scheduler_registra_o_job(self, monkeypatch):
        monkeypatch.setattr(scheduler, "get_settings", lambda: FakeSettings())
        sched = scheduler.criar_scheduler()

        job = sched.get_job("pipeline_ofertas")
        assert job is not None
        assert scheduler._scheduler is sched

        scheduler.parar_scheduler()

    def test_parar_scheduler_sem_scheduler_ativo_nao_lanca_erro(self):
        scheduler._scheduler = None
        scheduler.parar_scheduler()  # não deve lançar

    async def test_parar_scheduler_desliga_o_scheduler_rodando(self, monkeypatch):
        monkeypatch.setattr(scheduler, "get_settings", lambda: FakeSettings())
        sched = scheduler.criar_scheduler()
        sched.start()

        assert sched.running is True
        scheduler.parar_scheduler()
        # AsyncIOScheduler agenda o shutdown real via call_soon — precisa de
        # um "yield" real ao loop para a mudança de estado ser aplicada.
        await _sleep_real(0)
        assert sched.running is False
        assert scheduler._scheduler is None


class TestExecutarPipelineAgora:
    async def test_chama_executar_pipeline(self, monkeypatch):
        chamado = {"vezes": 0}

        async def _fake_executar_pipeline():
            chamado["vezes"] += 1

        monkeypatch.setattr(scheduler, "executar_pipeline", _fake_executar_pipeline)
        await scheduler.executar_pipeline_agora()

        assert chamado["vezes"] == 1
