"""Testes para bot/telegram_publisher.py — formatação de mensagens e teclado."""

import pytest
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError, TimedOut

import bot.telegram_publisher as mod
from bot.telegram_publisher import (
    _TOKEN_PLACEHOLDER,
    _escapar_html,
    _formatar_preco_br,
    _montar_caption,
    _montar_teclado,
    publicar_no_telegram,
)


class FakeMensagem:
    def __init__(self, message_id: int):
        self.message_id = message_id


class FakeBot:
    """Substitui telegram.Bot — cada teste define as respostas/erros em sequência."""

    respostas: list = []

    def __init__(self, token):
        self.token = token

    async def send_photo(self, **_kwargs):
        item = FakeBot.respostas.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture(autouse=True)
def _sem_espera_real(monkeypatch):
    async def _sleep_instantaneo(*_a, **_kw):
        return None

    monkeypatch.setattr(mod.asyncio, "sleep", _sleep_instantaneo)


@pytest.fixture
def settings_validas(monkeypatch):
    class FakeSettings:
        telegram_bot_token = "token-valido"
        telegram_channel_id = "@canal"

    monkeypatch.setattr(mod, "get_settings", lambda: FakeSettings())
    monkeypatch.setattr(mod, "Bot", FakeBot)


class TestFormatarPrecoBr:
    def test_valor_none(self):
        assert _formatar_preco_br(None) == ""

    def test_valor_com_milhar(self):
        assert _formatar_preco_br(1299.90) == "R$ 1.299,90"

    def test_valor_pequeno(self):
        assert _formatar_preco_br(7.5) == "R$ 7,50"

    def test_valor_inteiro(self):
        assert _formatar_preco_br(100) == "R$ 100,00"


class TestEscaparHtml:
    def test_escapa_caracteres_especiais(self):
        assert _escapar_html("<b>Título & cia</b>") == "&lt;b&gt;Título &amp; cia&lt;/b&gt;"

    def test_texto_sem_especiais_fica_igual(self):
        assert _escapar_html("Notebook Gamer") == "Notebook Gamer"


class TestMontarCaption:
    def test_caption_completo(self, oferta_exemplo):
        caption = _montar_caption(oferta_exemplo)
        assert "🔥" in caption
        assert oferta_exemplo["title"] in caption
        assert "R$ 189,90" in caption
        assert "R$ 299,90" in caption
        assert "Amazon" in caption
        assert "-36%" in caption  # int(36.68) trunca para 36

    def test_sem_preco_original_nao_mostra_de(self):
        deal = {"title": "Produto", "price": 50.0}
        caption = _montar_caption(deal)
        assert "De:" not in caption

    def test_sem_desconto_nao_mostra_percentual(self):
        deal = {"title": "Produto", "price": 50.0}
        caption = _montar_caption(deal)
        assert "Desconto" not in caption

    def test_titulo_e_escapado(self):
        deal = {"title": "Fone <Premium> & Cia", "price": 50.0}
        caption = _montar_caption(deal)
        assert "<Premium>" not in caption
        assert "&lt;Premium&gt;" in caption

    def test_descricao_longa_e_truncada(self):
        deal = {"title": "Produto", "price": 10.0, "description": "x" * 300}
        caption = _montar_caption(deal)
        assert "x" * 200 + "..." in caption

    def test_dicionario_vazio_nao_quebra(self):
        caption = _montar_caption({})
        assert "Oferta Especial" in caption


class TestMontarTeclado:
    def test_usa_affiliate_url_quando_disponivel(self):
        deal = {"url": "https://loja.com/produto", "affiliate_url": "https://loja.com/produto?tag=x"}
        teclado = _montar_teclado(deal)
        assert teclado.inline_keyboard[0][0].url == "https://loja.com/produto?tag=x"

    def test_usa_url_direta_quando_sem_afiliado(self):
        deal = {"url": "https://loja.com/produto"}
        teclado = _montar_teclado(deal)
        assert teclado.inline_keyboard[0][0].url == "https://loja.com/produto"

    def test_texto_do_botao(self):
        teclado = _montar_teclado({"url": "https://loja.com/produto"})
        assert teclado.inline_keyboard[0][0].text == "🛒 Comprar agora"


class TestPublicarNoTelegram:
    async def test_token_placeholder_nao_publica(self, monkeypatch, oferta_exemplo):
        class FakeSettings:
            telegram_bot_token = _TOKEN_PLACEHOLDER
            telegram_channel_id = "@canal"

        monkeypatch.setattr(mod, "get_settings", lambda: FakeSettings())

        resultado = await publicar_no_telegram(oferta_exemplo, b"fake-png-bytes")
        assert resultado is None

    async def test_sucesso_na_primeira_tentativa(self, settings_validas, oferta_exemplo):
        FakeBot.respostas = [FakeMensagem(42)]
        resultado = await publicar_no_telegram(oferta_exemplo, b"fake-png")
        assert resultado == 42

    async def test_retry_after_tenta_de_novo_e_funciona(self, settings_validas, oferta_exemplo):
        FakeBot.respostas = [RetryAfter(retry_after=1), FakeMensagem(7)]
        resultado = await publicar_no_telegram(oferta_exemplo, b"fake-png")
        assert resultado == 7

    async def test_timeout_tenta_de_novo_e_funciona(self, settings_validas, oferta_exemplo):
        FakeBot.respostas = [TimedOut(), FakeMensagem(8)]
        resultado = await publicar_no_telegram(oferta_exemplo, b"fake-png")
        assert resultado == 8

    async def test_network_error_tenta_de_novo_e_funciona(self, settings_validas, oferta_exemplo):
        FakeBot.respostas = [NetworkError("conexão caiu"), FakeMensagem(9)]
        resultado = await publicar_no_telegram(oferta_exemplo, b"fake-png")
        assert resultado == 9

    async def test_bad_request_nao_tenta_de_novo(self, settings_validas, oferta_exemplo):
        FakeBot.respostas = [BadRequest("legenda inválida")]
        resultado = await publicar_no_telegram(oferta_exemplo, b"fake-png")
        assert resultado is None
        assert FakeBot.respostas == []  # só consumiu 1 — não tentou de novo

    async def test_forbidden_nao_tenta_de_novo(self, settings_validas, oferta_exemplo):
        FakeBot.respostas = [Forbidden("bot removido do canal")]
        resultado = await publicar_no_telegram(oferta_exemplo, b"fake-png")
        assert resultado is None
        assert FakeBot.respostas == []

    async def test_erro_generico_do_telegram_esgota_tentativas(
        self, settings_validas, oferta_exemplo
    ):
        FakeBot.respostas = [
            TelegramError("erro 1"),
            TelegramError("erro 2"),
            TelegramError("erro 3"),
        ]
        resultado = await publicar_no_telegram(oferta_exemplo, b"fake-png")
        assert resultado is None

    async def test_excecao_inesperada_nao_tenta_de_novo(self, settings_validas, oferta_exemplo):
        FakeBot.respostas = [ValueError("bug inesperado")]
        resultado = await publicar_no_telegram(oferta_exemplo, b"fake-png")
        assert resultado is None
        assert FakeBot.respostas == []
