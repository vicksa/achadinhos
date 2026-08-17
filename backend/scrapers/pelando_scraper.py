"""
Scraper do Pelando (pelando.com.br).

O Pelando não oferece mais feed RSS público (os antigos endpoints
retornam 404). Em vez disso, este módulo lê o HTML renderizado no
servidor (Astro SSR) diretamente via HTTP simples — sem necessidade
de navegador headless:

1. A página de listagem (/mais-quentes) já traz os cards com título,
   preço aproximado, loja e link permanente da oferta.
2. A página de cada oferta (/d/<slug>) embute um bloco JSON completo
   (props de um componente Astro) com todos os dados normalizados,
   incluindo o link direto pro produto na loja de origem (sourceUrl).

Como o card da listagem nem sempre traz a loja/desconto de forma
confiável, este scraper sempre busca a página de detalhe de cada
oferta nova para extrair os dados definitivos.
"""

import asyncio
import html as html_lib
import json
import logging
import re
from typing import Any

import httpx

from scrapers.base import DealScraper
from scrapers.resiliencia import circuit_breaker, retry_async
from scrapers.utils import calcular_quality_score, limpar_html

logger = logging.getLogger(__name__)

# ── Configuração ─────────────────────────────────────────────────────
FONTE = "pelando"
LISTAGEM_URL = "https://www.pelando.com.br/mais-quentes"
LIMITE_PADRAO = 12
_HTTP_TIMEOUT = 15.0
_DELAY_ENTRE_DETALHES = 0.5  # segundos — educado com o servidor deles

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept-Language": "pt-BR,pt;q=0.9",
}

# Marca cada card na listagem — atributos semânticos, mais estáveis
# do que as classes CSS com hash de build.
_PADRAO_CARD_INICIO = re.compile(r'data-show-author="false" data-show-comment="false"')
_PADRAO_LINK_OFERTA = re.compile(r'href="(https://www\.pelando\.com\.br/d/[^"?]+)')

# No detalhe: localiza o bloco de props do componente que carrega o
# objeto "deal" completo (título, preço, loja, sourceUrl, etc.)
_PADRAO_PROPS_DEAL = re.compile(
    r'component-export="DealAlertAction".*?props="(.*?)"',
    re.DOTALL,
)


def _unwrap(valor: Any) -> Any:
    """
    "Desembrulha" a serialização usada pelo Astro para os props
    (formato [tag, valor], onde tag=0 é valor direto e tag=1 é lista).

    Args:
        valor: Estrutura serializada (dict, list ou primitivo).

    Returns:
        Estrutura equivalente em Python "normal".
    """
    if isinstance(valor, list) and len(valor) == 2 and isinstance(valor[0], int):
        tag, interno = valor
        if tag == 0:
            return _unwrap(interno)
        if tag == 1 and isinstance(interno, list):
            return [_unwrap(item) for item in interno]
        return interno
    if isinstance(valor, dict):
        return {chave: _unwrap(v) for chave, v in valor.items()}
    if isinstance(valor, list):
        return [_unwrap(item) for item in valor]
    return valor


async def _listar_links_ofertas(
    client: httpx.AsyncClient, limit: int
) -> list[str] | None:
    """
    Busca a página de ofertas "mais quentes" e extrai os links
    permanentes de cada card (https://www.pelando.com.br/d/...).

    Args:
        client: Cliente HTTP assíncrono já configurado.
        limit: Número máximo de links a retornar.

    Returns:
        Lista de URLs de ofertas (sem duplicatas, na ordem da página), ou
        None especificamente se a requisição falhou (distinto de uma
        lista vazia, que significa "carregou mas não achou nenhum card").
    """
    try:
        async def _buscar() -> httpx.Response:
            resp = await client.get(LISTAGEM_URL)
            resp.raise_for_status()
            return resp

        resp = await retry_async(_buscar, nome="Pelando: buscar listagem")
    except httpx.HTTPError as exc:
        logger.error("Pelando: falha ao buscar listagem (%s): %s", LISTAGEM_URL, exc)
        return None

    html = resp.text
    links: list[str] = []
    vistos: set[str] = set()

    for match_card in _PADRAO_CARD_INICIO.finditer(html):
        bloco = html[match_card.start(): match_card.start() + 2000]
        match_link = _PADRAO_LINK_OFERTA.search(bloco)
        if not match_link:
            continue
        link = match_link.group(1)
        if link not in vistos:
            vistos.add(link)
            links.append(link)
        if len(links) >= limit:
            break

    logger.info("Pelando: %d links de ofertas encontrados na listagem.", len(links))
    return links


async def _buscar_detalhe_oferta(
    client: httpx.AsyncClient, url: str
) -> dict[str, Any] | None:
    """
    Busca a página de uma oferta específica e extrai os dados completos
    (título, preço, desconto, loja, link direto pro produto, imagem).

    Args:
        client: Cliente HTTP assíncrono já configurado.
        url: URL permanente da oferta no Pelando (/d/<slug>).

    Returns:
        Dicionário normalizado compatível com o modelo Deal, ou None
        se a oferta não puder ser processada.
    """
    try:
        async def _buscar() -> httpx.Response:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp

        # Retry mais enxuto que o da listagem — é uma página individual,
        # não vale a pena gastar muito tempo numa oferta só.
        resp = await retry_async(_buscar, tentativas=2, nome=f"Pelando: buscar detalhe de {url}")
    except httpx.HTTPError as exc:
        logger.warning("Pelando: falha ao buscar detalhe de %s: %s", url, exc)
        return None

    match = _PADRAO_PROPS_DEAL.search(resp.text)
    if not match:
        logger.debug("Pelando: bloco de dados não encontrado em %s", url)
        return None

    try:
        bruto = html_lib.unescape(match.group(1))
        props = json.loads(bruto)
        deal = _unwrap(props.get("deal"))
    except (json.JSONDecodeError, AttributeError, TypeError) as exc:
        logger.warning("Pelando: erro ao parsear dados de %s: %s", url, exc)
        return None

    if not deal or not deal.get("title") or not deal.get("sourceUrl"):
        logger.debug("Pelando: oferta incompleta, ignorando: %s", url)
        return None

    preco = deal.get("price")
    if not preco or preco <= 0:
        return None
    preco = float(preco)

    desconto_pct = deal.get("discountPercentage") or 0
    desconto_fixo = deal.get("discountFixed") or 0
    preco_original: float | None = None
    discount_pct: float | None = None

    if desconto_pct and desconto_pct > 0:
        discount_pct = round(float(desconto_pct), 2)
        preco_original = round(preco / (1 - discount_pct / 100), 2)
    elif desconto_fixo and desconto_fixo > 0:
        preco_original = round(preco + float(desconto_fixo), 2)
        discount_pct = round((float(desconto_fixo) / preco_original) * 100, 2)

    loja = (deal.get("store") or {}).get("name")
    temperatura = deal.get("temperature") or 0
    # Normaliza temperatura (tipicamente 0–1000+) para escala 0-100
    sinal_popularidade = min(temperatura / 10, 100)

    return {
        "source": "pelando",
        "title": str(deal["title"])[:500],
        "description": limpar_html(deal.get("shortDescription"))[:2000] or None,
        "price": preco,
        "price_original": preco_original,
        "discount_pct": discount_pct,
        "url": deal["sourceUrl"],
        "affiliate_url": None,
        "image_url": deal.get("imageUrl"),
        "store": loja,
        "quality_score": calcular_quality_score(discount_pct, sinal_popularidade),
        "status": "pending",
    }


async def coletar_ofertas_pelando(limit: int = LIMITE_PADRAO) -> list[dict[str, Any]]:
    """
    Coleta ofertas do Pelando (listagem "mais quentes" + detalhe de cada uma).

    É resiliente: se a listagem falhar, retorna lista vazia; se o
    detalhe de uma oferta específica falhar, ela é simplesmente pulada.

    Args:
        limit: Número máximo de ofertas a coletar nesta execução.

    Returns:
        Lista de dicionários de ofertas normalizadas.
    """
    if not circuit_breaker.permite_chamada(FONTE):
        logger.warning(
            "Pelando: circuit breaker aberto (falhas recentes) — pulando esta coleta."
        )
        return []

    ofertas: list[dict[str, Any]] = []

    async with httpx.AsyncClient(
        timeout=_HTTP_TIMEOUT,
        follow_redirects=True,
        headers=_HEADERS,
    ) as client:
        links = await _listar_links_ofertas(client, limit)
        if links is None:
            circuit_breaker.registrar_falha(FONTE)
            return []

        circuit_breaker.registrar_sucesso(FONTE)
        if not links:
            return []

        for i, link in enumerate(links):
            try:
                deal = await _buscar_detalhe_oferta(client, link)
                if deal:
                    ofertas.append(deal)
            except Exception as exc:
                logger.error(
                    "Pelando: erro inesperado ao processar %s: %s",
                    link,
                    exc,
                    exc_info=True,
                )

            if i < len(links) - 1:
                await asyncio.sleep(_DELAY_ENTRE_DETALHES)

    logger.info("Pelando: %d ofertas coletadas com sucesso.", len(ofertas))
    return ofertas


class PelandoScraper(DealScraper):
    """Implementação de `DealScraper` para o Pelando (ver `scrapers/base.py`)."""

    nome = FONTE

    async def fetch(self, limit: int = LIMITE_PADRAO) -> list[dict[str, Any]]:
        return await coletar_ofertas_pelando(limit=limit)
