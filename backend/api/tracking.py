"""Rastreamento de cliques em ofertas afiliadas.

O endpoint /go/{deal_id} registra a origem do clique e redireciona para o
link afiliado da oferta. Se não houver affiliate_url, usa a URL original
somente como fallback para não quebrar links existentes.
"""

import logging
import uuid

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select

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

        click = DealClick(
            deal_id=deal.id,
            source=src.strip().lower() or "direct",
            campaign=campaign.strip() if campaign else None,
            referrer=request.headers.get("referer"),
            user_agent=request.headers.get("user-agent"),
        )
        session.add(click)
        await session.commit()

    logger.info("Clique registrado deal=%s src=%s", deal_id, src)
    return RedirectResponse(url=destino, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
