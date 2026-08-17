"""
Scraper do Promobit (promobit.com.br).

Assim como o Pelando, o Promobit não mantém mais feed RSS público.
O site é uma aplicação Next.js que embute todos os dados da página
inicial em um bloco `<script id="__NEXT_DATA__">` já renderizado no
servidor — isso significa que uma única requisição HTTP simples (sem
navegador headless) já retorna título, preço, preço anterior, desconto
e loja de cada oferta, sem precisar visitar cada uma individualmente.

Limitação conhecida: o Promobit não expõe o link direto do produto na
loja de origem no HTML estático (o redirecionamento é feito via
JavaScript no clique, para preservar o link de afiliado deles). Por
isso, usamos aqui a própria página da oferta no Promobit como link —
ela mostra o produto e o botão de compra normalmente.
"""

import json
import logging
import re
from typing import Any

import httpx

from scrapers.base import DealScraper
from scrapers.resiliencia import circuit_breaker, retry_async
from scrapers.utils import calcular_quality_score

logger = logging.getLogger(__name__)

# ── Configuração ─────────────────────────────────────────────────────
FONTE = "promobit"
HOMEPAGE_URL = "https://www.promobit.com.br/"
LIMITE_PADRAO = 15
_HTTP_TIMEOUT = 15.0

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept-Language": "pt-BR,pt;q=0.9",
}

_PADRAO_NEXT_DATA = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)


def _processar_oferta(item: dict[str, Any]) -> dict[str, Any] | None:
    """
    Converte um item bruto de `serverOffers.offers` no formato
    normalizado compatível com o modelo Deal.

    Args:
        item: Dicionário de uma oferta, conforme retornado pelo Next.js.

    Returns:
        Dicionário normalizado ou None se dados essenciais faltarem.
    """
    titulo = item.get("offerTitle")
    slug = item.get("offerSlug")
    preco = item.get("offerPrice")

    if not titulo or not slug or preco is None or preco <= 0:
        return None

    preco = float(preco)
    preco_antigo = item.get("offerOldPrice") or 0
    desconto_pct_informado = item.get("offerDiscontPercentage") or 0

    preco_original: float | None = None
    discount_pct: float | None = None
    if preco_antigo and preco_antigo > preco:
        preco_original = round(float(preco_antigo), 2)
        discount_pct = round(
            float(desconto_pct_informado)
            if desconto_pct_informado > 0
            else (1 - preco / preco_original) * 100,
            2,
        )

    likes = item.get("offerLikes") or 0
    # Normaliza curtidas (tipicamente 0-100+) para escala 0-100
    sinal_popularidade = min(likes, 100)

    return {
        "source": "promobit",
        "title": str(titulo)[:500],
        "description": None,
        "price": preco,
        "price_original": preco_original,
        "discount_pct": discount_pct,
        # Link direto pro produto não é exposto no HTML estático (ver
        # docstring do módulo) — usamos a página da oferta no Promobit.
        "url": f"https://www.promobit.com.br/oferta/{slug}/",
        "affiliate_url": None,
        "image_url": None,
        "store": item.get("storeName"),
        "quality_score": calcular_quality_score(discount_pct, sinal_popularidade),
        "status": "pending",
    }


async def coletar_ofertas_promobit(limit: int = LIMITE_PADRAO) -> list[dict[str, Any]]:
    """
    Coleta ofertas da página inicial do Promobit.

    Faz uma única requisição HTTP e extrai o JSON já embutido pelo
    Next.js (`__NEXT_DATA__`), sem precisar de navegador headless nem
    de requisições adicionais por oferta.

    Args:
        limit: Número máximo de ofertas a retornar.

    Returns:
        Lista de dicionários de ofertas normalizadas. Lista vazia em
        caso de erro (rede, HTML alterado, etc.) — resiliente.
    """
    if not circuit_breaker.permite_chamada(FONTE):
        logger.warning(
            "Promobit: circuit breaker aberto (falhas recentes) — pulando esta coleta."
        )
        return []

    try:
        async with httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT,
            follow_redirects=True,
            headers=_HEADERS,
        ) as client:

            async def _buscar_homepage() -> httpx.Response:
                resp = await client.get(HOMEPAGE_URL)
                resp.raise_for_status()
                return resp

            resp = await retry_async(_buscar_homepage, nome="Promobit: buscar homepage")
    except httpx.HTTPError as exc:
        logger.error("Promobit: falha ao buscar homepage: %s", exc)
        circuit_breaker.registrar_falha(FONTE)
        return []

    circuit_breaker.registrar_sucesso(FONTE)

    match = _PADRAO_NEXT_DATA.search(resp.text)
    if not match:
        logger.warning(
            "Promobit: bloco __NEXT_DATA__ não encontrado — site pode ter mudado."
        )
        return []

    try:
        dados = json.loads(match.group(1))
        ofertas_brutas = (
            dados.get("props", {})
            .get("pageProps", {})
            .get("serverOffers", {})
            .get("offers", [])
        )
    except (json.JSONDecodeError, AttributeError) as exc:
        logger.error("Promobit: erro ao parsear __NEXT_DATA__: %s", exc)
        return []

    ofertas: list[dict[str, Any]] = []
    for item in ofertas_brutas[:limit]:
        try:
            oferta = _processar_oferta(item)
            if oferta:
                ofertas.append(oferta)
        except Exception as exc:
            logger.error(
                "Promobit: erro ao processar oferta '%s': %s",
                item.get("offerTitle", "???")[:50],
                exc,
                exc_info=True,
            )

    logger.info("Promobit: %d ofertas coletadas com sucesso.", len(ofertas))
    return ofertas


class PromobitScraper(DealScraper):
    """Implementação de `DealScraper` para o Promobit (ver `scrapers/base.py`)."""

    nome = FONTE

    async def fetch(self, limit: int = LIMITE_PADRAO) -> list[dict[str, Any]]:
        return await coletar_ofertas_promobit(limit=limit)
