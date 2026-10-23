"""Coleta para o catálogo do site, sem publicar em redes sociais."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text

from affiliate.engine import SUPPORTED_MARKETPLACES, enrich_affiliate_data
from core.config import get_settings
from core.database import AsyncSessionLocal
from core.models import Deal
from scrapers.pelando_scraper import PelandoScraper
from scrapers.promobit_scraper import PromobitScraper

logger = logging.getLogger(__name__)
SCRAPERS = [PelandoScraper(), PromobitScraper()]
_FIELDS = (
    "source", "title", "description", "price", "price_original",
    "discount_pct", "url", "affiliate_url", "image_url", "store", "quality_score",
)


async def collect_site_deals() -> int:
    """Atualiza preços sem duplicar URLs ou alterar o estado de publicação."""
    settings = get_settings()
    results = await asyncio.gather(
        *(scraper.fetch(limit=30) for scraper in SCRAPERS),
        return_exceptions=True,
    )
    offers = {}
    for scraper, result in zip(SCRAPERS, results):
        if isinstance(result, BaseException):
            logger.warning("Coleta do site: fonte %s indisponível", scraper.nome)
            continue
        for raw in result:
            if not raw.get("url") or not raw.get("title") or not raw.get("price") or raw["price"] <= 0:
                continue
            discount = raw.get("discount_pct")
            if discount is not None and discount < settings.deal_min_discount_pct:
                continue
            affiliate = enrich_affiliate_data(raw, fallback_urls={
                "temu": settings.temu_affiliate_url,
                "magalu": settings.magalu_affiliate_url,
            })
            if (settings.affiliate_require_monetizable
                    and affiliate.marketplace in SUPPORTED_MARKETPLACES
                    and not affiliate.monetizable):
                continue
            offer = {key: raw.get(key) for key in _FIELDS}
            offer["affiliate_url"] = affiliate.affiliate_url
            offers[offer["url"]] = offer

    if not offers:
        logger.info("Coleta do site: nenhuma oferta válida nesta consulta")
        return 0

    async with AsyncSessionLocal() as session, session.begin():
        # Evita duplicatas durante sobreposição de instâncias no deploy.
        locked = await session.scalar(text("SELECT pg_try_advisory_xact_lock(8174601)"))
        if not locked:
            return 0
        rows = (await session.scalars(select(Deal).where(Deal.url.in_(offers)))).all()
        existing = {deal.url: deal for deal in rows}
        expires = datetime.now(timezone.utc) + timedelta(hours=24)
        for url, offer in offers.items():
            deal = existing.get(url)
            if deal is None:
                deal = Deal(**offer, status="pending")
                session.add(deal)
            else:
                for key, value in offer.items():
                    if key == "affiliate_url" and not value:
                        continue  # Preserva links de produto cadastrados manualmente.
                    setattr(deal, key, value)
            deal.expires_at = expires
    logger.info("Coleta do site: %d ofertas salvas/atualizadas", len(offers))
    return len(offers)


async def run_site_collector() -> None:
    """Executa ao iniciar a API e periodicamente enquanto ela estiver ativa."""
    interval = max(60, get_settings().deal_check_interval_minutes * 60)
    while True:
        try:
            await collect_site_deals()
        except Exception:
            logger.exception("Coleta do site falhou; nova tentativa no próximo ciclo")
        await asyncio.sleep(interval)
