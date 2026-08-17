"""
Utilitários de resiliência compartilhados pelos scrapers: retry com
backoff exponencial e circuit breaker por fonte.

Motivação: os scrapers dependem de sites de terceiros que podem cair,
ficar lentos ou mudar de estrutura a qualquer momento. Sem isso, uma
falha transiente (timeout pontual, 502 momentâneo) descartava a coleta
inteira daquele ciclo; e uma fonte fora do ar por horas seria martelada
a cada execução do pipeline (a cada 5 min, por padrão) sem necessidade.
"""

import asyncio
import logging
import time
from typing import Awaitable, Callable, TypeVar

import httpx

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Erros de rede considerados transientes — vale a pena tentar de novo.
EXCECOES_RETRYAVEIS: tuple[type[Exception], ...] = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.RemoteProtocolError,
)


async def retry_async(
    func: Callable[[], Awaitable[T]],
    *,
    tentativas: int = 3,
    delay_inicial: float = 1.0,
    fator_backoff: float = 2.0,
    nome: str = "operação",
) -> T:
    """
    Executa `func` com retry e backoff exponencial para falhas transientes.

    Erros HTTP 5xx (`httpx.HTTPStatusError` com status >= 500) também são
    tratados como transientes — problema do servidor, tentar de novo pode
    ajudar. Erros 4xx são re-lançados imediatamente, sem retry — indicam
    um problema na requisição em si, que repetir não resolve.

    Args:
        func: Função assíncrona sem argumentos a executar (ex: uma lambda
            fechando sobre os argumentos reais).
        tentativas: Número máximo de tentativas (padrão: 3).
        delay_inicial: Espera antes da 1ª retentativa, em segundos.
        fator_backoff: Multiplicador do delay a cada nova tentativa.
        nome: Nome descritivo da operação, usado nos logs.

    Returns:
        O resultado de `func()` na primeira tentativa bem-sucedida.

    Raises:
        A última exceção capturada, se todas as tentativas falharem, ou
        imediatamente para erros não-transientes (ex: HTTP 4xx).
    """
    delay = delay_inicial
    ultima_excecao: Exception | None = None

    for tentativa in range(1, tentativas + 1):
        try:
            return await func()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code < 500:
                raise
            ultima_excecao = exc
        except EXCECOES_RETRYAVEIS as exc:
            ultima_excecao = exc

        if tentativa < tentativas:
            logger.warning(
                "%s falhou (tentativa %d/%d): %s — tentando de novo em %.1fs",
                nome,
                tentativa,
                tentativas,
                ultima_excecao,
                delay,
            )
            await asyncio.sleep(delay)
            delay *= fator_backoff

    logger.error("%s falhou após %d tentativas: %s", nome, tentativas, ultima_excecao)
    raise ultima_excecao


class CircuitBreaker:
    """
    Circuit breaker simples em memória, com estado por fonte.

    Depois de `limite_falhas` falhas consecutivas de uma fonte, o circuito
    "abre" e passa a recusar chamadas por `cooldown_segundos` — evita
    martelar repetidamente um site fora do ar a cada ciclo do pipeline.
    Depois do cooldown, permite uma nova tentativa (half-open): sucesso
    fecha o circuito de novo, falha reabre e reinicia o cooldown.
    """

    def __init__(self, limite_falhas: int = 3, cooldown_segundos: float = 900):
        self.limite_falhas = limite_falhas
        self.cooldown_segundos = cooldown_segundos
        self._falhas: dict[str, int] = {}
        self._aberto_desde: dict[str, float] = {}

    def permite_chamada(self, fonte: str) -> bool:
        """Retorna False se o circuito estiver aberto (ainda em cooldown) para a fonte."""
        aberto_desde = self._aberto_desde.get(fonte)
        if aberto_desde is None:
            return True
        if time.monotonic() - aberto_desde >= self.cooldown_segundos:
            return True  # cooldown terminou — permite 1 tentativa (half-open)
        return False

    def registrar_sucesso(self, fonte: str) -> None:
        """Zera o contador de falhas e fecha o circuito da fonte."""
        self._falhas[fonte] = 0
        self._aberto_desde.pop(fonte, None)

    def registrar_falha(self, fonte: str) -> None:
        """Incrementa o contador de falhas; abre o circuito se atingir o limite."""
        self._falhas[fonte] = self._falhas.get(fonte, 0) + 1
        if self._falhas[fonte] >= self.limite_falhas:
            if fonte not in self._aberto_desde:
                logger.error(
                    "Circuit breaker ABERTO para '%s' após %d falhas consecutivas "
                    "— pausando coletas desta fonte por %.0fs.",
                    fonte,
                    self._falhas[fonte],
                    self.cooldown_segundos,
                )
            self._aberto_desde[fonte] = time.monotonic()

    def resetar(self, fonte: str | None = None) -> None:
        """Reseta o estado (de uma fonte específica, ou de todas)."""
        if fonte is None:
            self._falhas.clear()
            self._aberto_desde.clear()
        else:
            self._falhas.pop(fonte, None)
            self._aberto_desde.pop(fonte, None)


# Instância compartilhada entre todos os scrapers — um circuito por fonte
# ("pelando", "promobit", "mercadolivre"), isolados entre si.
circuit_breaker = CircuitBreaker()
