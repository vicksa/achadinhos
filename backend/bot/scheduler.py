"""Agendador de tarefas do Bot de Achadinhos."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from affiliate.engine import SUPPORTED_MARKETPLACES, enrich_affiliate_data
from core.config import get_settings
from core.database import AsyncSessionLocal
from core.models import Deal

from bot.dedup import ja_foi_postado, marcar_heartbeat, marcar_postado
from bot.card_generator import generate_deal_card
from bot.telegram_publisher import publicar_no_telegram
from bot.twitter_publisher import init_twitter, publicar_no_twitter, fechar_twitter
from scrapers.base import DealScraper
from scrapers.pelando_scraper import PelandoScraper
from scrapers.promobit_scraper import PromobitScraper

logger = logging.getLogger(__name__)
_scheduler: AsyncIOScheduler | None = None
SCRAPERS: list[DealScraper] = [PelandoScraper(), PromobitScraper()]


def _tracking_url(deal_id: Any, source: str) -> str:
    settings = get_settings()
    base = settings.public_base_url.rstrip("/")
    return f"{base}/go/{deal_id}?src={source}"


async def _filtrar_ofertas_novas(
    ofertas: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Filtra duplicatas, desconto mínimo e ofertas sem monetização quando exigido."""
    settings = get_settings()
    novas: list[dict[str, Any]] = []

    for oferta in ofertas:
        url = oferta.get("url", "")
        titulo = oferta.get("title", "")

        if not url or not titulo:
            logger.debug("Oferta ignorada (sem URL ou título): %s", titulo[:50])
            continue

        if await ja_foi_postado(url):
            logger.debug("Oferta já postada (dedup): %s", titulo[:50])
            continue

        desconto = oferta.get("discount_pct")
        if desconto is not None and desconto < settings.deal_min_discount_pct:
            logger.debug(
                "Oferta ignorada (desconto %.1f%% < %.1f%%): %s",
                desconto,
                settings.deal_min_discount_pct,
                titulo[:50],
            )
            continue

        affiliate = enrich_affiliate_data(oferta)
        if affiliate.affiliate_url:
            oferta["affiliate_url"] = affiliate.affiliate_url

        if (
            settings.affiliate_require_monetizable
            and affiliate.marketplace in SUPPORTED_MARKETPLACES
            and not affiliate.monetizable
        ):
            logger.warning(
                "Oferta segurada: %s detectada como %s, mas sem link afiliado (%s)",
                titulo[:60],
                affiliate.marketplace,
                affiliate.reason,
            )
            continue

        novas.append(oferta)

    logger.info(
        "Filtragem: %d ofertas recebidas → %d novas após dedup/filtros/monetização.",
        len(ofertas),
        len(novas),
    )
    return novas


async def _salvar_deal_no_banco(deal_data: dict[str, Any]) -> Deal | None:
    try:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                deal = Deal(
                    source=deal_data.get("source"),
                    title=deal_data.get("title"),
                    description=deal_data.get("description"),
                    price=deal_data.get("price"),
                    price_original=deal_data.get("price_original"),
                    discount_pct=deal_data.get("discount_pct"),
                    url=deal_data.get("url"),
                    affiliate_url=deal_data.get("affiliate_url"),
                    image_url=deal_data.get("image_url"),
                    store=deal_data.get("store"),
                    quality_score=deal_data.get("quality_score"),
                    status="pending",
                )
                session.add(deal)

            logger.debug(
                "Deal salvo no banco: id=%s, título=%s",
                deal.id,
                deal.title[:50] if deal.title else "???",
            )
            return deal
    except Exception as exc:
        logger.error(
            "Erro ao salvar deal no banco: %s — %s",
            deal_data.get("title", "???")[:50],
            exc,
            exc_info=True,
        )
        return None


async def _atualizar_status_publicacao(
    deal_id: Any,
    tg_message_id: int | None,
    twitter_ok: bool = False,
) -> None:
    try:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                result = await session.execute(select(Deal).where(Deal.id == deal_id))
                deal = result.scalar_one_or_none()
                if deal:
                    if tg_message_id:
                        deal.published_tg = True
                        deal.tg_message_id = tg_message_id
                    if twitter_ok:
                        deal.published_twitter = True
                    deal.status = "published" if (tg_message_id or twitter_ok) else "pending"
    except Exception as exc:
        logger.error("Erro ao atualizar status: deal_id=%s — %s", deal_id, exc)


async def executar_pipeline() -> None:
    settings = get_settings()
    logger.info("🔍 Iniciando pipeline de coleta de ofertas...")
    inicio = datetime.now(timezone.utc)

    await marcar_heartbeat(ttl_segundos=settings.deal_check_interval_minutes * 60 * 3)

    resultados = await asyncio.gather(
        *(scraper.fetch() for scraper in SCRAPERS),
        return_exceptions=True,
    )

    ofertas: list[dict[str, Any]] = []
    for scraper, resultado in zip(SCRAPERS, resultados):
        if isinstance(resultado, Exception):
            logger.error("Falha crítica na coleta de %s: %s", scraper.nome, resultado, exc_info=True)
            continue
        ofertas.extend(resultado)

    if not ofertas:
        logger.info("Nenhuma oferta encontrada nas fontes configuradas.")
        return

    ofertas.sort(key=lambda o: o.get("quality_score") or 0, reverse=True)
    ofertas_novas = await _filtrar_ofertas_novas(ofertas)
    if not ofertas_novas:
        logger.info("Nenhuma oferta nova após filtragem.")
        return

    twitter_pronto = await init_twitter()
    if settings.twitter_enabled and not twitter_pronto:
        logger.warning("Twitter habilitado mas sessão não pôde ser iniciada.")

    try:
        publicadas, erros = await _processar_ofertas(ofertas_novas, twitter_pronto, settings)
    finally:
        if twitter_pronto:
            await fechar_twitter()

    duracao = (datetime.now(timezone.utc) - inicio).total_seconds()
    logger.info(
        "Pipeline finalizado em %.1fs | coletadas=%d | novas=%d | publicadas=%d | erros=%d",
        duracao,
        len(ofertas),
        len(ofertas_novas),
        publicadas,
        erros,
    )


async def _processar_ofertas(
    ofertas_novas: list[dict[str, Any]],
    twitter_pronto: bool,
    settings: Any,
) -> tuple[int, int]:
    publicadas = 0
    erros = 0

    for i, oferta in enumerate(ofertas_novas, start=1):
        titulo = oferta.get("title", "???")[:60]
        logger.info("Processando oferta %d/%d: %s", i, len(ofertas_novas), titulo)

        try:
            deal = await _salvar_deal_no_banco(oferta)
            deal_id = deal.id if deal else None

            try:
                card_bytes = generate_deal_card(oferta)
            except Exception as exc:
                logger.error("Erro ao gerar card para '%s': %s", titulo, exc, exc_info=True)
                erros += 1
                continue

            telegram_oferta = dict(oferta)
            if deal_id:
                telegram_oferta["affiliate_url"] = _tracking_url(deal_id, "telegram")
            tg_msg_id = await publicar_no_telegram(telegram_oferta, card_bytes)

            twitter_ok = False
            if twitter_pronto:
                twitter_oferta = dict(oferta)
                if deal_id:
                    twitter_oferta["affiliate_url"] = _tracking_url(deal_id, "twitter")
                twitter_ok = await publicar_no_twitter(twitter_oferta, card_bytes)

            if tg_msg_id or twitter_ok:
                await marcar_postado(oferta["url"])
                if deal_id:
                    await _atualizar_status_publicacao(deal_id, tg_msg_id, twitter_ok)

                publicadas += 1
                logger.info(
                    "✅ Oferta publicada (telegram=%s, twitter=%s): %s",
                    bool(tg_msg_id),
                    twitter_ok,
                    titulo,
                )

                if i < len(ofertas_novas):
                    await asyncio.sleep(settings.telegram_post_cooldown_seconds)
            else:
                erros += 1
                logger.warning("❌ Falha ao publicar: %s", titulo)
                if deal_id:
                    await _atualizar_status_publicacao(deal_id, None)

        except Exception as exc:
            erros += 1
            logger.error("Erro inesperado ao processar '%s': %s", titulo, exc, exc_info=True)

    return publicadas, erros


def criar_scheduler() -> AsyncIOScheduler:
    global _scheduler
    settings = get_settings()
    scheduler = AsyncIOScheduler(
        timezone="America/Sao_Paulo",
        job_defaults={
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": 300,
        },
    )
    scheduler.add_job(
        executar_pipeline,
        trigger=IntervalTrigger(minutes=settings.deal_check_interval_minutes),
        id="pipeline_ofertas",
        name="Pipeline de Coleta de Ofertas",
        replace_existing=True,
    )
    logger.info("Scheduler configurado: pipeline a cada %d minutos.", settings.deal_check_interval_minutes)
    _scheduler = scheduler
    return scheduler


async def executar_pipeline_agora() -> None:
    await executar_pipeline()


def parar_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler parado.")
    _scheduler = None
