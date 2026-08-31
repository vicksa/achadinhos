"""Router público de achadinhos."""

import logging

from fastapi import APIRouter, Query
from sqlalchemy import func, or_, select

from api.schemas import DealListResponse, DealOut, DealSortOption
from core.database import AsyncSessionLocal
from core.models import Deal

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/deals", tags=["Achadinhos"])
MAX_LIMIT = 100


def _para_deal_out(deal: Deal) -> DealOut:
    """Converte Deal ORM para a representação pública rastreável."""
    return DealOut(
        id=str(deal.id),
        title=deal.title or "Achadinho",
        description=deal.description,
        price=float(deal.price) if deal.price is not None else None,
        price_original=float(deal.price_original) if deal.price_original is not None else None,
        discount_pct=float(deal.discount_pct) if deal.discount_pct is not None else None,
        # O frontend não recebe mais diretamente a URL do marketplace.
        # Assim, cliques no site passam pelo tracking antes do redirecionamento.
        url=f"/go/{deal.id}?src=site",
        image_url=deal.image_url,
        store=deal.store,
        source=deal.source,
        quality_score=float(deal.quality_score) if deal.quality_score is not None else None,
        created_at=deal.created_at.isoformat(),
    )


@router.get("", response_model=DealListResponse, summary="Listar achadinhos")
async def listar_deals(
    q: str | None = Query(default=None, max_length=200),
    store: str | None = Query(default=None),
    min_discount: float | None = Query(default=None, ge=0, le=100),
    sort_by: DealSortOption = Query(default=DealSortOption.NEWEST),
    limit: int = Query(default=24, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> DealListResponse:
    async with AsyncSessionLocal() as session:
        condicoes = [Deal.price.is_not(None), Deal.price > 0]

        if q:
            termo = func.unaccent(f"%{q.strip()}%")
            condicoes.append(
                or_(
                    func.unaccent(Deal.title).ilike(termo),
                    func.unaccent(Deal.store).ilike(termo),
                )
            )

        if store:
            condicoes.append(func.unaccent(Deal.store).ilike(func.unaccent(store.strip())))

        if min_discount is not None:
            condicoes.append(Deal.discount_pct.is_not(None))
            condicoes.append(Deal.discount_pct >= min_discount)

        stmt_total = select(func.count()).select_from(Deal).where(*condicoes)
        total = (await session.execute(stmt_total)).scalar_one()

        stmt = select(Deal).where(*condicoes)
        match sort_by:
            case DealSortOption.DISCOUNT:
                stmt = stmt.order_by(Deal.discount_pct.desc().nulls_last())
            case DealSortOption.PRICE_ASC:
                stmt = stmt.order_by(Deal.price.asc())
            case DealSortOption.PRICE_DESC:
                stmt = stmt.order_by(Deal.price.desc())
            case _:
                stmt = stmt.order_by(Deal.created_at.desc())

        stmt = stmt.limit(limit).offset(offset)
        deals = (await session.execute(stmt)).scalars().all()

    return DealListResponse(
        total=total,
        results=[_para_deal_out(d) for d in deals],
        limit=limit,
        offset=offset,
    )
