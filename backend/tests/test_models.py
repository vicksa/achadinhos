"""Testes para core/models.py — persistência e defaults dos modelos ORM."""

import uuid

from sqlalchemy import select

from core.models import Deal, Offer, PriceAlert, Product


class TestDealModel:
    async def test_cria_com_defaults_corretos(self, db_session, oferta_exemplo):
        deal = Deal(**{k: v for k, v in oferta_exemplo.items() if k != "status"})
        db_session.add(deal)
        await db_session.commit()
        await db_session.refresh(deal)

        assert isinstance(deal.id, uuid.UUID)
        assert deal.status == "pending"
        assert deal.published_tg is False
        assert deal.published_ig is False
        assert deal.published_twitter is False
        assert deal.created_at is not None
        assert deal.created_at.tzinfo is not None

    async def test_persiste_e_busca_pelo_id(self, db_session, oferta_exemplo):
        deal = Deal(**oferta_exemplo)
        db_session.add(deal)
        await db_session.commit()

        resultado = await db_session.execute(select(Deal).where(Deal.id == deal.id))
        encontrado = resultado.scalar_one()
        assert encontrado.title == oferta_exemplo["title"]
        assert float(encontrado.price) == oferta_exemplo["price"]

    async def test_permite_campos_opcionais_nulos(self, db_session):
        deal = Deal(title="Produto mínimo")
        db_session.add(deal)
        await db_session.commit()
        await db_session.refresh(deal)

        assert deal.price is None
        assert deal.store is None
        assert deal.discount_pct is None


class TestProductModel:
    async def test_cria_produto_minimo(self, db_session):
        produto = Product(name="Echo Dot 5ª Geração")
        db_session.add(produto)
        await db_session.commit()
        await db_session.refresh(produto)

        assert isinstance(produto.id, uuid.UUID)
        assert produto.created_at is not None


class TestOfferModel:
    async def test_offer_associada_a_product(self, db_session):
        produto = Product(name="SSD 1TB NVMe")
        db_session.add(produto)
        await db_session.flush()

        offer = Offer(
            product_id=produto.id,
            marketplace="mercadolivre",
            url="https://www.mercadolivre.com.br/produto",
            price=399.90,
        )
        db_session.add(offer)
        await db_session.commit()
        await db_session.refresh(offer)

        assert offer.in_stock is True
        resultado = await db_session.execute(
            select(Offer).where(Offer.product_id == produto.id)
        )
        assert resultado.scalar_one().marketplace == "mercadolivre"


class TestPriceAlertModel:
    async def test_alerta_criado_com_defaults(self, db_session):
        produto = Product(name="Monitor 144Hz")
        db_session.add(produto)
        await db_session.flush()

        alerta = PriceAlert(
            product_id=produto.id,
            email="usuario@exemplo.com",
            target_price=899.90,
        )
        db_session.add(alerta)
        await db_session.commit()
        await db_session.refresh(alerta)

        assert alerta.is_active is True
        assert alerta.notified_at is None
