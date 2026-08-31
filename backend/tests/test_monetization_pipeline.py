"""Testes da integração entre Affiliate Engine, pipeline e tracking."""

from types import SimpleNamespace

import pytest

from bot import scheduler


@pytest.mark.asyncio
async def test_supported_marketplace_without_affiliate_is_blocked(monkeypatch):
    async def not_posted(_url: str) -> bool:
        return False

    monkeypatch.setattr(scheduler, "ja_foi_postado", not_posted)
    monkeypatch.setattr(
        scheduler,
        "get_settings",
        lambda: SimpleNamespace(
            deal_min_discount_pct=10.0,
            affiliate_require_monetizable=True,
        ),
    )

    offers = [
        {
            "title": "Produto Shopee",
            "url": "https://shopee.com.br/produto-x",
            "store": "Shopee",
            "discount_pct": 30,
        }
    ]

    result = await scheduler._filtrar_ofertas_novas(offers)
    assert result == []


@pytest.mark.asyncio
async def test_supported_marketplace_with_affiliate_is_allowed(monkeypatch):
    async def not_posted(_url: str) -> bool:
        return False

    monkeypatch.setattr(scheduler, "ja_foi_postado", not_posted)
    monkeypatch.setattr(
        scheduler,
        "get_settings",
        lambda: SimpleNamespace(
            deal_min_discount_pct=10.0,
            affiliate_require_monetizable=True,
        ),
    )

    offers = [
        {
            "title": "Produto Temu",
            "url": "https://www.temu.com/br/produto-x.html",
            "affiliate_url": "https://www.temu.com/br/produto-x.html?affiliate=exemplo",
            "store": "Temu",
            "discount_pct": 35,
        }
    ]

    result = await scheduler._filtrar_ofertas_novas(offers)
    assert len(result) == 1
    assert result[0]["affiliate_url"].startswith("https://www.temu.com/")


def test_tracking_url_uses_public_base_url(monkeypatch):
    monkeypatch.setattr(
        scheduler,
        "get_settings",
        lambda: SimpleNamespace(public_base_url="https://achadinhos.exemplo.com/"),
    )

    url = scheduler._tracking_url("abc-123", "telegram")
    assert url == "https://achadinhos.exemplo.com/go/abc-123?src=telegram"


@pytest.mark.asyncio
async def test_temu_uses_configured_affiliate_fallback(monkeypatch):
    async def not_posted(_url: str) -> bool:
        return False

    monkeypatch.setattr(scheduler, "ja_foi_postado", not_posted)
    monkeypatch.setattr(
        scheduler,
        "get_settings",
        lambda: SimpleNamespace(
            deal_min_discount_pct=10.0,
            affiliate_require_monetizable=True,
            temu_affiliate_url="https://temu.to/k/gjj9tmr3rdo",
        ),
    )

    offers = [
        {
            "title": "Produto Temu",
            "url": "https://www.temu.com/br/produto-x.html",
            "store": "Temu",
            "discount_pct": 35,
        }
    ]

    result = await scheduler._filtrar_ofertas_novas(offers)
    assert result[0]["affiliate_url"] == "https://temu.to/k/gjj9tmr3rdo"
