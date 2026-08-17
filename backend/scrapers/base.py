"""
Interface comum a todo scraper de ofertas consumido pelo pipeline do bot
(ver bot/scheduler.py).

Padronizar essa interface é o que permite adicionar uma nova fonte
(Amazon, Magalu, Kabum, Pichau...) sem alterar o pipeline — basta
implementar `DealScraper` e adicionar a instância à lista `SCRAPERS`
em bot/scheduler.py.
"""

from abc import ABC, abstractmethod
from typing import Any


class DealScraper(ABC):
    """
    Interface que todo scraper de ofertas do pipeline do bot implementa.

    `nome` identifica a fonte nos logs, no circuit breaker
    (`scrapers/resiliencia.py`) e no campo `source` do modelo `Deal`.
    """

    nome: str

    @abstractmethod
    async def fetch(self, limit: int) -> list[dict[str, Any]]:
        """
        Coleta ofertas da fonte.

        Deve ser resiliente: nunca lançar por falha de rede/parsing —
        retornar lista vazia nesses casos (o próprio scraper já deve
        aplicar retry/circuit breaker internamente).

        Args:
            limit: Número máximo de ofertas a coletar.

        Returns:
            Lista de dicionários normalizados, no formato aceito por
            `bot/scheduler.py` (mesmas chaves do modelo `Deal`: title,
            price, url, store, discount_pct, quality_score etc.).
        """
        raise NotImplementedError
