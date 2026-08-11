"""
Router de busca da API de Agregação de Preços.

Gerencia endpoints de busca, cache Redis e agregação de resultados
de múltiplos marketplaces em paralelo via asyncio.gather().

Endpoints:
    GET /api/search            — Busca de produtos com cache
    GET /api/search/suggestions — Sugestões baseadas em buscas recentes
"""

import asyncio
import json
import logging
import time
import unicodedata
import re

from fastapi import APIRouter, Depends, HTTPException, Query, status
import redis.asyncio as aioredis

from api.schemas import (
    ProductOffer,
    SearchQuery,
    SearchResponse,
    SortOption,
    SuggestionResponse,
)
from core.config import get_settings, Settings
from scrapers.mercadolivre import buscar_mercadolivre

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/search", tags=["Busca"])

# ---- Constantes ----
CACHE_KEY_PREFIX = "search:"
SUGGESTIONS_KEY = "search:recent_queries"
MAX_SUGGESTIONS = 10
MAX_RECENT_QUERIES = 100


def _normalizar_cache_key(query: str) -> str:
    """
    Normaliza a query para usar como chave de cache Redis.

    Remove acentos, converte para minúsculas, remove caracteres especiais
    e colapsa espaços múltiplos para garantir cache hits consistentes.

    Args:
        query: Termo de busca original.

    Returns:
        Chave normalizada no formato 'search:termo_normalizado'.
    """
    # Remover acentos
    texto = unicodedata.normalize("NFKD", query)
    texto = texto.encode("ascii", "ignore").decode("ascii")
    # Minúsculas e limpar espaços
    texto = texto.lower().strip()
    texto = re.sub(r"\s+", " ", texto)
    return f"{CACHE_KEY_PREFIX}{texto}"


async def _get_redis() -> aioredis.Redis | None:
    """
    Obtém conexão Redis do estado global da app.

    Returns:
        Instância Redis ou None se indisponível.
    """
    # A conexão Redis é armazenada no app.state pelo lifespan handler.
    # Em contexto de roteador, usamos a variável de módulo definida no main.
    try:
        from api.main import _redis_pool
        return _redis_pool
    except (ImportError, AttributeError):
        logger.warning("Conexão Redis indisponível.")
        return None


def _ordenar_resultados(
    ofertas: list[ProductOffer],
    sort_by: SortOption,
) -> list[ProductOffer]:
    """
    Ordena a lista de ofertas conforme o critério selecionado.

    Args:
        ofertas: Lista de ProductOffer para ordenar.
        sort_by: Critério de ordenação.

    Returns:
        Lista ordenada de ProductOffer.
    """
    match sort_by:
        case SortOption.PRICE_ASC:
            return sorted(ofertas, key=lambda o: o.price)
        case SortOption.PRICE_DESC:
            return sorted(ofertas, key=lambda o: o.price, reverse=True)
        case SortOption.DISCOUNT:
            return sorted(
                ofertas,
                key=lambda o: o.discount_pct or 0,
                reverse=True,
            )
        case SortOption.RATING:
            return sorted(
                ofertas,
                key=lambda o: (o.rating or 0, o.rating_count or 0),
                reverse=True,
            )
        case SortOption.NAME:
            return sorted(ofertas, key=lambda o: o.name.lower())
        case _:
            return sorted(ofertas, key=lambda o: o.price)


def _filtrar_resultados(
    ofertas: list[ProductOffer],
    min_price: float | None = None,
    max_price: float | None = None,
    marketplace: str | None = None,
) -> list[ProductOffer]:
    """
    Filtra ofertas por faixa de preço e/ou marketplace.

    Args:
        ofertas: Lista completa de ProductOffer.
        min_price: Preço mínimo (inclusivo).
        max_price: Preço máximo (inclusivo).
        marketplace: Filtrar por marketplace específico.

    Returns:
        Lista filtrada de ProductOffer.
    """
    resultado = ofertas

    if min_price is not None:
        resultado = [o for o in resultado if o.price >= min_price]

    if max_price is not None:
        resultado = [o for o in resultado if o.price <= max_price]

    if marketplace is not None:
        mp = marketplace.lower().strip()
        resultado = [o for o in resultado if o.marketplace.lower() == mp]

    return resultado


async def _registrar_busca_recente(
    redis_conn: aioredis.Redis | None,
    query: str,
) -> None:
    """
    Registra o termo de busca na lista de buscas recentes no Redis.

    Mantém no máximo MAX_RECENT_QUERIES termos recentes para sugestões.

    Args:
        redis_conn: Conexão Redis (ou None se indisponível).
        query: Termo de busca normalizado.
    """
    if redis_conn is None:
        return

    try:
        termo = query.strip().lower()
        # Remove duplicatas antes de adicionar
        await redis_conn.lrem(SUGGESTIONS_KEY, 0, termo)
        # Adiciona no início da lista
        await redis_conn.lpush(SUGGESTIONS_KEY, termo)
        # Mantém apenas os N termos mais recentes
        await redis_conn.ltrim(SUGGESTIONS_KEY, 0, MAX_RECENT_QUERIES - 1)
    except Exception:
        logger.debug("Falha ao registrar busca recente", exc_info=True)


@router.get(
    "",
    response_model=SearchResponse,
    summary="Buscar produtos",
    description=(
        "Busca produtos em múltiplos marketplaces, com cache Redis e "
        "ordenação por preço, desconto ou avaliação."
    ),
)
async def buscar_produtos(
    q: str = Query(
        ...,
        min_length=2,
        max_length=200,
        description="Termo de busca",
        examples=["iphone 15"],
    ),
    sort_by: SortOption = Query(
        default=SortOption.PRICE_ASC,
        description="Critério de ordenação",
    ),
    min_price: float | None = Query(
        default=None,
        gt=0,
        description="Preço mínimo (BRL)",
    ),
    max_price: float | None = Query(
        default=None,
        gt=0,
        description="Preço máximo (BRL)",
    ),
    marketplace: str | None = Query(
        default=None,
        description="Filtrar por marketplace (ex: mercadolivre)",
    ),
) -> SearchResponse:
    """
    Endpoint principal de busca de preços.

    Fluxo:
        1. Normaliza a query e verifica cache Redis.
        2. Em caso de cache miss, dispara buscas em paralelo nos marketplaces.
        3. Normaliza, filtra e ordena os resultados.
        4. Armazena no cache Redis com TTL configurável.
        5. Retorna SearchResponse com metadados de performance.

    Retorna resultados parciais se algum marketplace estiver indisponível.
    """
    inicio = time.perf_counter()
    settings = get_settings()
    redis_conn = await _get_redis()

    # Normalizar query
    query_normalizada = " ".join(q.strip().split())
    cache_key = _normalizar_cache_key(query_normalizada)

    # 1. Verificar cache Redis
    if redis_conn is not None:
        try:
            dados_cache = await redis_conn.get(cache_key)
            if dados_cache is not None:
                logger.info("Cache HIT para '%s'", query_normalizada)
                ofertas_cache = [
                    ProductOffer.model_validate(item)
                    for item in json.loads(dados_cache)
                ]

                # Aplicar filtros (podem mudar entre requests cacheados)
                ofertas_filtradas = _filtrar_resultados(
                    ofertas_cache, min_price, max_price, marketplace
                )
                ofertas_ordenadas = _ordenar_resultados(ofertas_filtradas, sort_by)

                tempo_ms = (time.perf_counter() - inicio) * 1000
                return SearchResponse(
                    query=query_normalizada,
                    total_results=len(ofertas_ordenadas),
                    results=ofertas_ordenadas,
                    cached=True,
                    search_time_ms=round(tempo_ms, 2),
                )
        except Exception:
            logger.warning("Falha ao ler cache Redis", exc_info=True)

    # 2. Cache miss — buscar em paralelo nos marketplaces
    logger.info("Cache MISS para '%s' — buscando nos marketplaces", query_normalizada)

    tarefas = [
        buscar_mercadolivre(query_normalizada, limit=20),
        # Futuros marketplaces serão adicionados aqui:
        # buscar_amazon(query_normalizada, limit=20),
        # buscar_magalu(query_normalizada, limit=20),
    ]

    resultados_por_marketplace = await asyncio.gather(
        *tarefas, return_exceptions=True
    )

    # 3. Consolidar resultados, tratando exceções individuais
    todas_ofertas: list[ProductOffer] = []
    for i, resultado in enumerate(resultados_por_marketplace):
        if isinstance(resultado, Exception):
            logger.error(
                "Marketplace #%d falhou: %s — %s",
                i,
                type(resultado).__name__,
                str(resultado),
            )
            continue
        if isinstance(resultado, list):
            todas_ofertas.extend(resultado)

    # 4. Cachear resultados brutos (sem filtros de preço/marketplace)
    if redis_conn is not None and todas_ofertas:
        try:
            dados_json = json.dumps(
                [oferta.model_dump() for oferta in todas_ofertas],
                ensure_ascii=False,
            )
            ttl = settings.cache_ttl_default
            await redis_conn.set(cache_key, dados_json, ex=ttl)
            logger.info(
                "Cache armazenado para '%s' (%d ofertas, TTL=%ds)",
                query_normalizada,
                len(todas_ofertas),
                ttl,
            )
        except Exception:
            logger.warning("Falha ao gravar cache Redis", exc_info=True)

    # Registrar busca recente para sugestões
    await _registrar_busca_recente(redis_conn, query_normalizada)

    # 5. Filtrar e ordenar
    ofertas_filtradas = _filtrar_resultados(
        todas_ofertas, min_price, max_price, marketplace
    )
    ofertas_ordenadas = _ordenar_resultados(ofertas_filtradas, sort_by)

    tempo_ms = (time.perf_counter() - inicio) * 1000
    return SearchResponse(
        query=query_normalizada,
        total_results=len(ofertas_ordenadas),
        results=ofertas_ordenadas,
        cached=False,
        search_time_ms=round(tempo_ms, 2),
    )


@router.get(
    "/suggestions",
    response_model=SuggestionResponse,
    summary="Sugestões de busca",
    description=(
        "Retorna sugestões de autocompletar baseadas nas buscas mais "
        "recentes registradas no sistema."
    ),
)
async def sugestoes_busca(
    q: str = Query(
        default="",
        max_length=200,
        description="Prefixo para filtrar sugestões",
    ),
) -> SuggestionResponse:
    """
    Endpoint de autocompletar baseado em buscas recentes.

    Retorna os termos de busca mais recentes que começam com o
    prefixo informado. Se nenhum prefixo for passado, retorna as
    buscas mais recentes.

    Args:
        q: Prefixo para filtrar sugestões.

    Returns:
        SuggestionResponse com até MAX_SUGGESTIONS termos.
    """
    redis_conn = await _get_redis()

    if redis_conn is None:
        return SuggestionResponse(suggestions=[])

    try:
        # Buscar termos recentes
        termos_recentes: list[bytes | str] = await redis_conn.lrange(
            SUGGESTIONS_KEY, 0, MAX_RECENT_QUERIES - 1
        )

        # Decodificar se necessário
        termos: list[str] = []
        for t in termos_recentes:
            if isinstance(t, bytes):
                termos.append(t.decode("utf-8"))
            else:
                termos.append(str(t))

        # Filtrar por prefixo (se informado)
        prefixo = q.strip().lower()
        if prefixo:
            termos = [t for t in termos if t.startswith(prefixo)]

        # Remover duplicatas mantendo ordem
        vistos: set[str] = set()
        unicos: list[str] = []
        for t in termos:
            if t not in vistos:
                vistos.add(t)
                unicos.append(t)

        return SuggestionResponse(suggestions=unicos[:MAX_SUGGESTIONS])

    except Exception:
        logger.warning("Falha ao buscar sugestões", exc_info=True)
        return SuggestionResponse(suggestions=[])
