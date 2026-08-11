"""
Agendador de tarefas do Bot de Achadinhos.

Usa APScheduler (AsyncIOScheduler) para executar o pipeline
de coleta e publicação de ofertas em intervalos configuráveis.

Pipeline completo:
1. Coleta ofertas (Pelando + Promobit, em paralelo)
2. Filtra duplicatas (Redis dedup)
3. Filtra por desconto mínimo
4. Salva no banco de dados
5. Gera card visual (Pillow)
6. Publica no Telegram
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from core.config import get_settings
from core.database import AsyncSessionLocal
from core.models import Deal

from bot.dedup import ja_foi_postado, marcar_postado
from bot.card_generator import generate_deal_card
from bot.telegram_publisher import publicar_no_telegram
from scrapers.pelando_scraper import coletar_ofertas_pelando
from scrapers.promobit_scraper import coletar_ofertas_promobit

logger = logging.getLogger(__name__)

# Scheduler global
_scheduler: AsyncIOScheduler | None = None


async def _filtrar_ofertas_novas(
    ofertas: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Filtra ofertas removendo duplicatas e aplicando critérios mínimos.

    Critérios de filtragem:
    1. URL não pode ser vazia
    2. Título não pode ser vazio
    3. Não pode ter sido postada antes (dedup Redis)
    4. Desconto mínimo (se configurado e se tiver informação de desconto)

    Args:
        ofertas: Lista de dicts com dados das ofertas.

    Returns:
        Lista filtrada de ofertas novas e válidas.
    """
    settings = get_settings()
    novas: list[dict[str, Any]] = []

    for oferta in ofertas:
        url = oferta.get("url", "")
        titulo = oferta.get("title", "")

        # Validação básica
        if not url or not titulo:
            logger.debug("Oferta ignorada (sem URL ou título): %s", titulo[:50])
            continue

        # Verificar deduplicação
        if await ja_foi_postado(url):
            logger.debug("Oferta já postada (dedup): %s", titulo[:50])
            continue

        # Filtrar por desconto mínimo (se houver info de desconto)
        desconto = oferta.get("discount_pct")
        if desconto is not None and desconto < settings.deal_min_discount_pct:
            logger.debug(
                "Oferta ignorada (desconto %.1f%% < %.1f%%): %s",
                desconto,
                settings.deal_min_discount_pct,
                titulo[:50],
            )
            continue

        novas.append(oferta)

    logger.info(
        "Filtragem: %d ofertas recebidas → %d novas após dedup e filtros.",
        len(ofertas),
        len(novas),
    )
    return novas


async def _salvar_deal_no_banco(deal_data: dict[str, Any]) -> Deal | None:
    """
    Salva uma oferta no banco de dados PostgreSQL.

    Args:
        deal_data: Dicionário com dados da oferta.

    Returns:
        Instância do modelo Deal salvo, ou None em caso de erro.
    """
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
            # commit automático ao sair do begin()

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
) -> None:
    """
    Atualiza o status de publicação de um deal no banco.

    Args:
        deal_id: UUID do deal.
        tg_message_id: ID da mensagem no Telegram (ou None se falhou).
    """
    try:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                result = await session.execute(
                    select(Deal).where(Deal.id == deal_id)
                )
                deal = result.scalar_one_or_none()
                if deal:
                    if tg_message_id:
                        deal.published_tg = True
                        deal.tg_message_id = tg_message_id
                        deal.status = "published"
                    else:
                        deal.status = "pending"  # Mantém pendente para retry

    except Exception as exc:
        logger.error(
            "Erro ao atualizar status de publicação: deal_id=%s — %s",
            deal_id,
            exc,
        )


async def executar_pipeline() -> None:
    """
    Executa o pipeline completo de coleta e publicação de ofertas.

    Etapas:
    1. Coleta ofertas de todas as fontes configuradas (Pelando, Promobit)
    2. Filtra ofertas novas (dedup + critérios)
    3. Para cada oferta nova:
       a. Salva no banco de dados
       b. Gera card visual
       c. Publica no Telegram
       d. Marca como postada no Redis
       e. Atualiza status no banco
       f. Aguarda cooldown entre posts

    É resiliente: se uma oferta falhar, as demais continuam
    sendo processadas.
    """
    settings = get_settings()

    logger.info(
        "═══════════════════════════════════════════════════════\n"
        "  🔍 Iniciando pipeline de coleta de ofertas...\n"
        "═══════════════════════════════════════════════════════"
    )
    inicio = datetime.now(timezone.utc)

    # ── Etapa 1: Coletar ofertas de todas as fontes em paralelo ──────
    resultados = await asyncio.gather(
        coletar_ofertas_pelando(),
        coletar_ofertas_promobit(),
        return_exceptions=True,
    )

    ofertas: list[dict[str, Any]] = []
    for fonte, resultado in zip(("pelando", "promobit"), resultados):
        if isinstance(resultado, Exception):
            logger.error(
                "Falha crítica na coleta de %s: %s", fonte, resultado, exc_info=True
            )
            continue
        ofertas.extend(resultado)

    if not ofertas:
        logger.info("Nenhuma oferta encontrada nas fontes configuradas.")
        return

    # Prioriza as melhores ofertas (maior desconto/popularidade) primeiro
    ofertas.sort(key=lambda o: o.get("quality_score") or 0, reverse=True)

    # ── Etapa 2: Filtrar ofertas novas ───────────────────────────────
    ofertas_novas = await _filtrar_ofertas_novas(ofertas)
    if not ofertas_novas:
        logger.info("Nenhuma oferta nova após filtragem.")
        return

    # ── Etapa 3: Processar cada oferta ───────────────────────────────
    publicadas = 0
    erros = 0

    for i, oferta in enumerate(ofertas_novas, start=1):
        titulo = oferta.get("title", "???")[:60]
        logger.info(
            "Processando oferta %d/%d: %s",
            i,
            len(ofertas_novas),
            titulo,
        )

        try:
            # 3a. Salvar no banco
            deal = await _salvar_deal_no_banco(oferta)
            deal_id = deal.id if deal else None

            # 3b. Gerar card visual
            try:
                card_bytes = generate_deal_card(oferta)
            except Exception as exc:
                logger.error(
                    "Erro ao gerar card para '%s': %s",
                    titulo,
                    exc,
                    exc_info=True,
                )
                erros += 1
                continue

            # 3c. Publicar no Telegram
            tg_msg_id = await publicar_no_telegram(oferta, card_bytes)

            if tg_msg_id:
                # 3d. Marcar como postada no Redis
                await marcar_postado(oferta["url"])

                # 3e. Atualizar status no banco
                if deal_id:
                    await _atualizar_status_publicacao(deal_id, tg_msg_id)

                publicadas += 1
                logger.info("✅ Oferta publicada com sucesso: %s", titulo)

                # 3f. Cooldown entre posts (evitar rate limit)
                if i < len(ofertas_novas):
                    logger.debug(
                        "Aguardando cooldown de %ds...",
                        settings.telegram_post_cooldown_seconds,
                    )
                    await asyncio.sleep(settings.telegram_post_cooldown_seconds)
            else:
                erros += 1
                logger.warning("❌ Falha ao publicar: %s", titulo)
                if deal_id:
                    await _atualizar_status_publicacao(deal_id, None)

        except Exception as exc:
            erros += 1
            logger.error(
                "Erro inesperado ao processar oferta '%s': %s",
                titulo,
                exc,
                exc_info=True,
            )
            continue

    # ── Resumo ───────────────────────────────────────────────────────
    duracao = (datetime.now(timezone.utc) - inicio).total_seconds()
    logger.info(
        "═══════════════════════════════════════════════════════\n"
        "  📊 Pipeline finalizado em %.1fs\n"
        "     Total coletadas: %d\n"
        "     Novas (após filtro): %d\n"
        "     Publicadas: %d\n"
        "     Erros: %d\n"
        "═══════════════════════════════════════════════════════",
        duracao,
        len(ofertas),
        len(ofertas_novas),
        publicadas,
        erros,
    )


def criar_scheduler() -> AsyncIOScheduler:
    """
    Cria e configura o scheduler APScheduler.

    Configura o job de coleta de ofertas com o intervalo
    definido em deal_check_interval_minutes.

    Returns:
        Instância do AsyncIOScheduler configurado (não iniciado).
    """
    global _scheduler

    settings = get_settings()
    scheduler = AsyncIOScheduler(
        timezone="America/Sao_Paulo",
        job_defaults={
            "coalesce": True,           # Se perdeu execuções, roda só 1x
            "max_instances": 1,          # Não roda em paralelo
            "misfire_grace_time": 300,   # 5 min de tolerância
        },
    )

    scheduler.add_job(
        executar_pipeline,
        trigger=IntervalTrigger(
            minutes=settings.deal_check_interval_minutes,
        ),
        id="pipeline_ofertas",
        name="Pipeline de Coleta de Ofertas",
        replace_existing=True,
    )

    logger.info(
        "Scheduler configurado: pipeline a cada %d minutos.",
        settings.deal_check_interval_minutes,
    )

    _scheduler = scheduler
    return scheduler


async def executar_pipeline_agora() -> None:
    """
    Executa o pipeline imediatamente (fora do scheduler).

    Útil para testes e execução manual.
    """
    await executar_pipeline()


def parar_scheduler() -> None:
    """Para o scheduler de forma limpa."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler parado.")
    _scheduler = None
