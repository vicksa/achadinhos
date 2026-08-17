"""Testes para scrapers/resiliencia.py — retry com backoff e circuit breaker."""

import httpx
import pytest

from scrapers.resiliencia import CircuitBreaker, retry_async


@pytest.fixture(autouse=True)
def _sem_espera_real(monkeypatch):
    import scrapers.resiliencia as mod

    async def _sleep_instantaneo(*_a, **_kw):
        return None

    monkeypatch.setattr(mod.asyncio, "sleep", _sleep_instantaneo)


def _resposta_5xx() -> httpx.Response:
    request = httpx.Request("GET", "https://exemplo.com")
    response = httpx.Response(503, request=request)
    return response


def _resposta_4xx() -> httpx.Response:
    request = httpx.Request("GET", "https://exemplo.com")
    return httpx.Response(404, request=request)


class TestRetryAsync:
    async def test_sucesso_na_primeira_tentativa_nao_tenta_de_novo(self):
        chamadas = []

        async def _func():
            chamadas.append(1)
            return "ok"

        resultado = await retry_async(_func, tentativas=3)
        assert resultado == "ok"
        assert len(chamadas) == 1

    async def test_timeout_tenta_de_novo_e_depois_funciona(self):
        chamadas = []

        async def _func():
            chamadas.append(1)
            if len(chamadas) < 2:
                raise httpx.TimeoutException("timeout")
            return "ok"

        resultado = await retry_async(_func, tentativas=3)
        assert resultado == "ok"
        assert len(chamadas) == 2

    async def test_esgota_tentativas_e_relanca_ultima_excecao(self):
        async def _func():
            raise httpx.ConnectError("conexão recusada")

        with pytest.raises(httpx.ConnectError):
            await retry_async(_func, tentativas=3)

    async def test_http_5xx_e_retryavel(self):
        chamadas = []

        async def _func():
            chamadas.append(1)
            if len(chamadas) < 2:
                raise httpx.HTTPStatusError("erro", request=None, response=_resposta_5xx())
            return "ok"

        resultado = await retry_async(_func, tentativas=3)
        assert resultado == "ok"
        assert len(chamadas) == 2

    async def test_http_4xx_nao_e_retryavel(self):
        chamadas = []

        async def _func():
            chamadas.append(1)
            raise httpx.HTTPStatusError("erro", request=None, response=_resposta_4xx())

        with pytest.raises(httpx.HTTPStatusError):
            await retry_async(_func, tentativas=3)

        assert len(chamadas) == 1  # não tentou de novo

    async def test_excecao_nao_mapeada_propaga_na_hora(self):
        async def _func():
            raise ValueError("bug qualquer")

        with pytest.raises(ValueError):
            await retry_async(_func, tentativas=3)


class TestCircuitBreaker:
    def test_permite_chamada_por_padrao(self):
        cb = CircuitBreaker()
        assert cb.permite_chamada("pelando") is True

    def test_abre_apos_limite_de_falhas(self):
        cb = CircuitBreaker(limite_falhas=3, cooldown_segundos=900)
        for _ in range(3):
            cb.registrar_falha("pelando")

        assert cb.permite_chamada("pelando") is False

    def test_nao_abre_antes_do_limite(self):
        cb = CircuitBreaker(limite_falhas=3, cooldown_segundos=900)
        cb.registrar_falha("pelando")
        cb.registrar_falha("pelando")

        assert cb.permite_chamada("pelando") is True

    def test_sucesso_reseta_contador_de_falhas(self):
        cb = CircuitBreaker(limite_falhas=3, cooldown_segundos=900)
        cb.registrar_falha("pelando")
        cb.registrar_falha("pelando")
        cb.registrar_sucesso("pelando")
        cb.registrar_falha("pelando")

        assert cb.permite_chamada("pelando") is True  # só 1 falha desde o reset

    def test_fontes_diferentes_sao_independentes(self):
        cb = CircuitBreaker(limite_falhas=2, cooldown_segundos=900)
        cb.registrar_falha("pelando")
        cb.registrar_falha("pelando")

        assert cb.permite_chamada("pelando") is False
        assert cb.permite_chamada("promobit") is True

    def test_permite_novamente_apos_cooldown(self, monkeypatch):
        cb = CircuitBreaker(limite_falhas=2, cooldown_segundos=10)
        cb.registrar_falha("pelando")
        cb.registrar_falha("pelando")
        assert cb.permite_chamada("pelando") is False

        import scrapers.resiliencia as mod

        tempo_futuro = mod.time.monotonic() + 11
        monkeypatch.setattr(mod.time, "monotonic", lambda: tempo_futuro)

        assert cb.permite_chamada("pelando") is True

    def test_resetar_uma_fonte(self):
        cb = CircuitBreaker(limite_falhas=2, cooldown_segundos=900)
        cb.registrar_falha("pelando")
        cb.registrar_falha("pelando")
        cb.registrar_falha("promobit")

        cb.resetar("pelando")

        assert cb.permite_chamada("pelando") is True
        assert cb._falhas["promobit"] == 1

    def test_resetar_tudo(self):
        cb = CircuitBreaker(limite_falhas=1, cooldown_segundos=900)
        cb.registrar_falha("pelando")
        cb.registrar_falha("promobit")

        cb.resetar()

        assert cb.permite_chamada("pelando") is True
        assert cb.permite_chamada("promobit") is True
