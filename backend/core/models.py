"""
Modelos ORM compartilhados entre Price Aggregator e Bot de Achadinhos.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    Numeric,
    String,
    Text,
    ForeignKey,
    func,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


# =============================================
# MODELOS DO PRICE AGGREGATOR
# =============================================

class Product(Base):
    """Produto normalizado (independente de marketplace)."""
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ean: Mapped[str | None] = mapped_column(String(13))
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(100))
    category: Mapped[str | None] = mapped_column(String(100))
    image_url: Mapped[str | None] = mapped_column(Text)
    slug: Mapped[str | None] = mapped_column(String(600), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relacionamentos
    offers: Mapped[list["Offer"]] = relationship(back_populates="product", cascade="all, delete-orphan")
    alerts: Mapped[list["PriceAlert"]] = relationship(back_populates="product", cascade="all, delete-orphan")


class Offer(Base):
    """Oferta de um produto num marketplace específico."""
    __tablename__ = "offers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id"), nullable=False
    )
    marketplace: Mapped[str] = mapped_column(String(50), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(Text, nullable=False)
    affiliate_url: Mapped[str | None] = mapped_column(Text)
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    price_old: Mapped[float | None] = mapped_column(Numeric(10, 2))
    in_stock: Mapped[bool] = mapped_column(Boolean, default=True)
    rating: Mapped[float | None] = mapped_column(Numeric(3, 2))
    rating_count: Mapped[int | None] = mapped_column(Integer)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relacionamentos
    product: Mapped["Product"] = relationship(back_populates="offers")

    __table_args__ = (
        Index("idx_offers_marketplace", "marketplace"),
        Index("idx_offers_product_marketplace", "product_id", "marketplace"),
    )


class PriceAlert(Base):
    """Alerta de preço configurado por um usuário."""
    __tablename__ = "price_alerts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    target_price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relacionamentos
    product: Mapped["Product"] = relationship(back_populates="alerts")


# =============================================
# MODELOS DO BOT DE ACHADINHOS
# =============================================

class Deal(Base):
    """Deal (achado/promoção) coletado e processado pelo bot."""
    __tablename__ = "deals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source: Mapped[str | None] = mapped_column(String(50))  # pelando, promobit, amazon...
    title: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    price: Mapped[float | None] = mapped_column(Numeric(10, 2))
    price_original: Mapped[float | None] = mapped_column(Numeric(10, 2))
    discount_pct: Mapped[float | None] = mapped_column(Numeric(5, 2))
    url: Mapped[str | None] = mapped_column(Text)
    affiliate_url: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    store: Mapped[str | None] = mapped_column(String(100))
    quality_score: Mapped[float | None] = mapped_column(Numeric(5, 2))  # 0-100

    # Status de publicação
    status: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending, approved, rejected, published
    published_tg: Mapped[bool] = mapped_column(Boolean, default=False)
    published_ig: Mapped[bool] = mapped_column(Boolean, default=False)
    tg_message_id: Mapped[int | None] = mapped_column(Integer)
    ig_post_id: Mapped[str | None] = mapped_column(String(100))

    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_deals_status", "status"),
        Index("idx_deals_source", "source"),
        Index("idx_deals_created", "created_at"),
    )
