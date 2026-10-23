"""Coleta real no banco de teste, com fontes HTTP substituídas."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import httpx
from sqlalchemy import select

from api.main import app, lifespan
from core import deal_collector as collector
from core.config import get_settings
from core.models import Deal


def source(offers):
    class Source:
        nome = "teste"

        async def fetch(self, limit):
            return offers
    return Source()


def offer(**kw):
    return dict(title="Fone Bluetooth", price=100, discount_pct=30,
                url="https://example.com/fone", store="Loja", source="teste", **kw)


async def test_atualiza_preco_sem_duplicar_ou_perder_publicacao(monkeypatch, db_session):
    raw = offer()
    batch = [raw, raw.copy()]
    monkeypatch.setattr(collector, "SCRAPERS", [source(batch)])
    assert await collector.collect_site_deals() == 1
    row = (await db_session.scalars(select(Deal))).one()
    row.published_tg = True
    row.status = "published"
    row.affiliate_url = "https://example.com/link-manual"
    await db_session.commit()
    raw["price"] = 90
    batch[:] = [raw]
    assert await collector.collect_site_deals() == 1
    db_session.expire_all()
    rows = (await db_session.scalars(select(Deal))).all()
    assert len(rows) == 1
    assert float(rows[0].price) == 90
    assert rows[0].published_tg is True
    assert rows[0].status == "published"
    assert rows[0].affiliate_url == "https://example.com/link-manual"
    assert rows[0].expires_at > datetime.now(timezone.utc)


async def test_retém_shein_sem_link_e_aceita_link_convertido(monkeypatch, db_session):
    sem_link = offer()
    sem_link.update(store="SHEIN", url="https://br.shein.com/produto")
    com_link = dict(sem_link, url="https://br.shein.com/outro",
                    affiliate_url="https://onelink.shein.com/link-oficial")
    invalida = dict(offer(), price=0)
    monkeypatch.setattr(collector, "SCRAPERS", [source([sem_link, com_link, invalida])])
    assert await collector.collect_site_deals() == 1
    row = (await db_session.scalars(select(Deal))).one()
    assert row.affiliate_url == com_link["affiliate_url"]
    assert row.published_tg is False
    assert row.published_twitter is False


async def test_fonte_indisponivel_nao_impede_outra(monkeypatch):
    bad = source([])
    bad.fetch = AsyncMock(side_effect=RuntimeError("fora do ar"))
    monkeypatch.setattr(collector, "SCRAPERS", [bad, source([offer()])])
    assert await collector.collect_site_deals() == 1


async def test_catalogo_nao_lista_oferta_expirada(db_session):
    db_session.add(Deal(**offer(), expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
    await db_session.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/deals")
    assert response.status_code == 200
    assert response.json()["total"] == 0


async def test_lifespan_inicia_e_cancela_coleta(monkeypatch):
    started, stopped = asyncio.Event(), asyncio.Event()

    async def run():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    monkeypatch.setattr(get_settings(), "site_deal_collection_enabled", True)
    monkeypatch.setattr(collector, "run_site_collector", run)
    async with lifespan(app):
        await asyncio.wait_for(started.wait(), timeout=2)
    assert stopped.is_set()
