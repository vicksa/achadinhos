"""Detecção e validação de monetização por marketplace.

Este módulo não inventa parâmetros de afiliado. Ele identifica o marketplace,
preserva links afiliados já gerados pelas plataformas oficiais e expõe um
resultado padronizado para o pipeline decidir se a oferta pode ser publicada.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

SUPPORTED_MARKETPLACES = {"shopee", "magalu", "temu"}

_DOMAIN_MAP = {
    "shopee": ("shopee.com.br", "shope.ee"),
    "magalu": ("magazineluiza.com.br", "magalu.com", "magazinevoce.com.br"),
    "temu": ("temu.com",),
}

_STORE_ALIASES = {
    "shopee": "shopee",
    "shoppe": "shopee",
    "magalu": "magalu",
    "magazine luiza": "magalu",
    "magazineluiza": "magalu",
    "temu": "temu",
}


@dataclass(slots=True)
class AffiliateResult:
    marketplace: str | None
    affiliate_url: str | None
    monetizable: bool
    reason: str


def _host(url: str | None) -> str:
    if not url:
        return ""
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def identify_marketplace(url: str | None = None, store: str | None = None) -> str | None:
    """Identifica Shopee, Magalu ou Temu a partir da loja e/ou URL."""
    normalized_store = (store or "").strip().lower()
    if normalized_store in _STORE_ALIASES:
        return _STORE_ALIASES[normalized_store]

    host = _host(url)
    for marketplace, domains in _DOMAIN_MAP.items():
        if any(host == domain or host.endswith(f".{domain}") for domain in domains):
            return marketplace
    return None


def enrich_affiliate_data(deal: dict) -> AffiliateResult:
    """Normaliza dados de afiliado sem fabricar links.

    Para marketplaces suportados, uma oferta só é marcada como monetizável
    quando já possui ``affiliate_url``. Isso evita publicar tráfego de graça
    enquanto a integração oficial de geração de links não estiver configurada.
    Outros marketplaces continuam permitidos pelo pipeline legado.
    """
    affiliate_url = (deal.get("affiliate_url") or "").strip() or None
    marketplace = identify_marketplace(
        url=affiliate_url or deal.get("url"),
        store=deal.get("store"),
    )

    if marketplace in SUPPORTED_MARKETPLACES:
        if affiliate_url:
            return AffiliateResult(
                marketplace=marketplace,
                affiliate_url=affiliate_url,
                monetizable=True,
                reason="affiliate_url presente",
            )
        return AffiliateResult(
            marketplace=marketplace,
            affiliate_url=None,
            monetizable=False,
            reason=f"{marketplace} sem affiliate_url",
        )

    return AffiliateResult(
        marketplace=marketplace,
        affiliate_url=affiliate_url,
        monetizable=bool(affiliate_url),
        reason="marketplace fora do escopo principal" if marketplace is None else "affiliate_url ausente",
    )
