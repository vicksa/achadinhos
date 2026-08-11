"""
Cliente assíncrono para a API do Mercado Livre (MLB — Brasil).

Suporta dois modos de operação:
1. Autenticado (OAuth2): requer client_id/client_secret configurados no .env
2. Público: usa headers de navegador como fallback quando sem credenciais

Endpoint base: https://api.mercadolibre.com/sites/MLB/search
Documentação: https://developers.mercadolibre.com/
"""

import logging
import time
from typing import Any

import httpx

from api.schemas import ProductOffer
from core.config import get_settings

logger = logging.getLogger(__name__)

# ---- Constantes ----
ML_SEARCH_URL = "https://api.mercadolibre.com/sites/MLB/search"
ML_TOKEN_URL = "https://api.mercadolibre.com/oauth/token"
ML_TIMEOUT = 15.0
ML_MAX_RESULTS = 50

# ---- Cache do token OAuth2 em memória ----
_token_cache: dict[str, Any] = {"access_token": None, "expires_at": 0}

# Headers que simulam um navegador para o fallback público
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}


async def _obter_token() -> str | None:
    """
    Obtém access_token via OAuth2 client_credentials.

    Faz cache em memória e renova automaticamente antes de expirar.

    Returns:
        Access token string ou None se credenciais não configuradas.
    """
    global _token_cache
    settings = get_settings()

    # Sem credenciais configuradas → retorna None (usará fallback)
    if not settings.ml_client_id or not settings.ml_client_secret:
        return None

    # Token ainda válido?
    if _token_cache["access_token"] and time.time() < _token_cache["expires_at"] - 60:
        return _token_cache["access_token"]

    # Renovar token
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                ML_TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": settings.ml_client_id,
                    "client_secret": settings.ml_client_secret,
                },
            )
            resp.raise_for_status()

        dados = resp.json()
        _token_cache["access_token"] = dados["access_token"]
        _token_cache["expires_at"] = time.time() + dados.get("expires_in", 21600)
        logger.info("Mercado Livre: token OAuth2 renovado com sucesso.")
        return _token_cache["access_token"]

    except Exception as exc:
        logger.warning("Mercado Livre: falha ao obter token OAuth2 — %s", exc)
        return None


async def buscar_mercadolivre(
    query: str,
    limit: int = 20,
    offset: int = 0,
) -> list[ProductOffer]:
    """
    Busca produtos no Mercado Livre.

    Tenta primeiro com autenticação OAuth2 (se credenciais disponíveis),
    depois faz fallback para busca com headers de navegador.

    Args:
        query: Termo de busca (ex: "iphone 15 pro").
        limit: Quantidade máxima de resultados (1-50).
        offset: Deslocamento para paginação.

    Returns:
        Lista de ProductOffer normalizados. Lista vazia em caso de erro.
    """
    limit = min(max(1, limit), ML_MAX_RESULTS)

    params: dict[str, Any] = {
        "q": query,
        "limit": limit,
        "offset": offset,
    }

    # Tentar com token OAuth2
    token = await _obter_token()

    try:
        headers = dict(_BROWSER_HEADERS)
        if token:
            headers["Authorization"] = f"Bearer {token}"

        async with httpx.AsyncClient(timeout=ML_TIMEOUT, headers=headers) as client:
            response = await client.get(ML_SEARCH_URL, params=params)

            # Se 403 com token, tentar sem (fallback público)
            if response.status_code == 403 and token:
                logger.info("ML: token rejeitado, tentando fallback público...")
                headers.pop("Authorization", None)
                response = await client.get(
                    ML_SEARCH_URL, params=params, headers=headers
                )

            response.raise_for_status()

        dados = response.json()
        resultados = dados.get("results", [])

        logger.info(
            "Mercado Livre: %d resultados para '%s' (total: %s)",
            len(resultados),
            query,
            dados.get("paging", {}).get("total", "?"),
        )

        ofertas: list[ProductOffer] = []
        for item in resultados:
            oferta = _normalizar_item(item)
            if oferta is not None:
                ofertas.append(oferta)

        return ofertas

    except httpx.TimeoutException:
        logger.warning(
            "Mercado Livre: timeout ao buscar '%s' (limite: %.1fs)",
            query,
            ML_TIMEOUT,
        )
        return []

    except httpx.HTTPStatusError as exc:
        logger.error(
            "Mercado Livre: HTTP %d ao buscar '%s' — %s",
            exc.response.status_code,
            query,
            exc.response.text[:200],
        )
        return []

    except httpx.RequestError as exc:
        logger.error(
            "Mercado Livre: erro de rede ao buscar '%s' — %s",
            query,
            str(exc),
        )
        return []

    except Exception:
        logger.exception("Mercado Livre: erro inesperado ao buscar '%s'", query)
        return []


def _normalizar_item(item: dict[str, Any]) -> ProductOffer | None:
    """
    Converte um item da API do Mercado Livre para o schema ProductOffer.

    Mapeamento principal:
        title        → name
        price        → price
        original_price → price_old
        thumbnail    → image_url (convertido para HTTPS e tamanho maior)
        permalink    → url
        seller.reputation → rating (normalizado para 0-5)

    Args:
        item: Dicionário de um resultado da API do ML.

    Returns:
        ProductOffer normalizado ou None se dados essenciais estiverem ausentes.
    """
    try:
        titulo = item.get("title")
        preco = item.get("price")
        permalink = item.get("permalink")

        # Campos obrigatórios
        if not titulo or preco is None or not permalink:
            logger.debug(
                "ML item ignorado (dados incompletos): id=%s",
                item.get("id", "?"),
            )
            return None

        preco = float(preco)
        if preco <= 0:
            return None

        # Preço original e desconto
        preco_old = item.get("original_price")
        desconto = None
        if preco_old is not None:
            preco_old = float(preco_old)
            if preco_old > preco:
                desconto = round((1 - preco / preco_old) * 100, 2)
            else:
                # original_price <= price → não é desconto real
                preco_old = None

        # Imagem — trocar HTTP por HTTPS e usar tamanho maior
        imagem = item.get("thumbnail") or item.get("secure_thumbnail")
        if imagem:
            imagem = imagem.replace("http://", "https://")
            # Trocar tamanho I (90x90) por W (500px width) para melhor qualidade
            imagem = imagem.replace("-I.jpg", "-W.jpg")

        # Avaliações — extrair do seller reputation
        rating = None
        rating_count = None
        seller = item.get("seller", {}) or {}
        reputacao = seller.get("seller_reputation", {}) or {}
        transactions = reputacao.get("transactions", {}) or {}

        # Usar ratings do item se disponíveis
        if "reviews" in item and item["reviews"]:
            reviews = item["reviews"]
            rating = reviews.get("rating_average")
            rating_count = reviews.get("total")

        # Disponibilidade
        quantidade = item.get("available_quantity", 0)
        em_estoque = quantidade > 0 if quantidade is not None else True

        # Condição
        condicao = item.get("condition", "")
        # Adicionar "(Usado)" ao nome se for produto usado
        if condicao == "used":
            titulo = f"{titulo} (Usado)"

        # Frete grátis
        shipping = item.get("shipping", {}) or {}
        frete_gratis = shipping.get("free_shipping", False)
        if frete_gratis:
            titulo = f"{titulo} [Frete Grátis]"

        return ProductOffer(
            name=titulo,
            price=preco,
            price_old=preco_old,
            image_url=imagem,
            marketplace="mercadolivre",
            url=permalink,
            affiliate_url=None,
            rating=rating,
            rating_count=rating_count,
            in_stock=em_estoque,
            discount_pct=desconto,
        )

    except (ValueError, TypeError, KeyError) as exc:
        logger.debug(
            "ML item ignorado (erro de conversão): id=%s — %s",
            item.get("id", "?"),
            exc,
        )
        return None
