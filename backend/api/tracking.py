"""Rastreamento e analytics básicos de cliques em ofertas afiliadas."""

import logging
import uuid

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select

from core.database import AsyncSessionLocal
from core.models import Deal, DealClick

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Tracking"])


@router.get(
    "/go/{deal_id}",
    summary="Registrar clique e abrir oferta",
    response_class=RedirectResponse,
)
async def abrir_oferta(
    deal_id: uuid.UUID,
    request: Request,
    src: str = Query(default="direct", max_length=50),
    campaign: str | None = Query(default=None, max_length=100),
) -> RedirectResponse:
    """Registra um clique e redireciona para a URL monetizável da oferta."""
    async with AsyncSessionLocal() as session:
        deal = (
            await session.execute(select(Deal).where(Deal.id == deal_id))
        ).scalar_one_or_none()

        if deal is None:
            raise HTTPException(status_code=404, detail="Oferta não encontrada")

        destino = deal.affiliate_url or deal.url
        if not destino:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="Oferta sem link disponível",
            )

        source = src.strip().lower() or "direct"
        click = DealClick(
            deal_id=deal.id,
            source=source,
            campaign=campaign.strip() if campaign else None,
            referrer=request.headers.get("referer"),
            user_agent=request.headers.get("user-agent"),
        )
        session.add(click)
        await session.commit()

    logger.info("Clique registrado deal=%s src=%s", deal_id, source)
    return RedirectResponse(url=destino, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.get("/api/analytics/clicks", summary="Resumo de cliques por origem")
async def resumo_cliques() -> dict:
    """Retorna somente métricas agregadas, sem expor user-agent/referrer."""
    async with AsyncSessionLocal() as session:
        total = (
            await session.execute(select(func.count()).select_from(DealClick))
        ).scalar_one()

        por_origem_rows = (
            await session.execute(
                select(DealClick.source, func.count(DealClick.id))
                .group_by(DealClick.source)
                .order_by(func.count(DealClick.id).desc())
            )
        ).all()

        top_deals_rows = (
            await session.execute(
                select(
                    DealClick.deal_id,
                    Deal.title,
                    Deal.store,
                    func.count(DealClick.id).label("clicks"),
                )
                .join(Deal, Deal.id == DealClick.deal_id)
                .group_by(DealClick.deal_id, Deal.title, Deal.store)
                .order_by(func.count(DealClick.id).desc())
                .limit(10)
            )
        ).all()

    return {
        "total_clicks": total,
        "by_source": [
            {"source": source, "clicks": count}
            for source, count in por_origem_rows
        ],
        "top_deals": [
            {
                "deal_id": str(deal_id),
                "title": title,
                "store": store,
                "clicks": clicks,
            }
            for deal_id, title, store, clicks in top_deals_rows
        ],
    }
