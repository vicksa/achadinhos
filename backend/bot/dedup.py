"""
Módulo de deduplicação baseado em Redis.

Usa hash MD5 da URL (sem query params) para evitar republicação
de ofertas já postadas dentro do período de TTL configurável.
"""

import hashlib
import logging
from urllib.parse import urlparse, urlunparse

import redis.asyncio as redis

from core.config import get_settings

logger = logging.getLogger(__name__)

# Prefixo para as chaves no Redis
_REDIS_PREFIX = "achadinhos:dedup:"

# Conexão global (inicializada via init_redis)
_redis_client: redis.Redis | None = None


async def init_redis() -> redis.Redis:
    """
    Inicializa e retorna o cliente Redis assíncrono.

    Reutiliza a conexão se já estiver aberta, garantindo
    um único pool de conexões por processo.

    Returns:
        Cliente Redis configurado e conectado.
    """
    global _redis_client
    if _redis_client is not None:
        return _redis_client

    settings = get_settings()
    _redis_client = redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=5,
        retry_on_timeout=True,
    )
    # Verifica conectividade
    try:
        await _redis_client.ping()
        logger.info("Conexão com Redis estabelecida com sucesso.")
    except redis.ConnectionError as exc:
        logger.error("Falha ao conectar no Redis: %s", exc)
        _redis_client = None
        raise

    return _redis_client


async def fechar_redis() -> None:
    """Fecha a conexão com o Redis de forma limpa."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
        logger.info("Conexão com Redis encerrada.")


def _normalizar_url(url: str) -> str:
    """
    Normaliza a URL removendo query params e fragmentos
    para gerar uma chave de deduplicação consistente.

    Args:
        url: URL original da oferta.

    Returns:
        URL normalizada (scheme + netloc + path).
    """
    parsed = urlparse(url.strip().lower())
    # Reconstrói sem query string e fragmento
    normalizada = urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path.rstrip("/"),
        "",  # params
        "",  # query
        "",  # fragment
    ))
    return normalizada


def _gerar_hash(url: str) -> str:
    """
    Gera um hash MD5 da URL normalizada para usar como chave Redis.

    Args:
        url: URL original da oferta.

    Returns:
        String com o hash MD5 hexadecimal.
    """
    url_normalizada = _normalizar_url(url)
    return hashlib.md5(url_normalizada.encode("utf-8")).hexdigest()


async def ja_foi_postado(url: str) -> bool:
    """
    Verifica se uma URL já foi postada anteriormente.

    Consulta o Redis para ver se o hash da URL existe,
    indicando que a oferta já foi publicada dentro do
    período de TTL.

    Args:
        url: URL da oferta a verificar.

    Returns:
        True se a oferta já foi postada, False caso contrário.
    """
    if _redis_client is None:
        logger.warning("Redis não inicializado. Tratando como não-duplicado.")
        return False

    chave = _REDIS_PREFIX + _gerar_hash(url)

    try:
        resultado = await _redis_client.exists(chave)
        if resultado:
            logger.debug("URL já postada (dedup hit): %s", url[:80])
        return bool(resultado)
    except redis.RedisError as exc:
        logger.error("Erro ao consultar Redis para dedup: %s", exc)
        # Em caso de falha, permite a publicação (fail-open)
        return False


async def marcar_postado(url: str) -> None:
    """
    Marca uma URL como postada no Redis com TTL configurável.

    Usa SETEX para armazenar o hash com expiração automática,
    baseada na configuração deal_dedup_ttl_days.

    Args:
        url: URL da oferta a marcar como postada.
    """
    if _redis_client is None:
        logger.warning("Redis não inicializado. Ignorando marcação de dedup.")
        return

    settings = get_settings()
    chave = _REDIS_PREFIX + _gerar_hash(url)
    ttl_segundos = settings.deal_dedup_ttl_days * 86400  # dias → segundos

    try:
        await _redis_client.set(name=chave, value="1", ex=ttl_segundos)
        logger.debug(
            "URL marcada como postada (TTL=%dd): %s",
            settings.deal_dedup_ttl_days,
            url[:80],
        )
    except redis.RedisError as exc:
        logger.error("Erro ao marcar URL como postada no Redis: %s", exc)
