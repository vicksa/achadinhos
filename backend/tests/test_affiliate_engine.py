from affiliate.engine import enrich_affiliate_data, identify_marketplace


def test_identifica_shopee_por_dominio():
    assert identify_marketplace("https://shopee.com.br/produto/123") == "shopee"


def test_identifica_shoppe_typo_por_store():
    assert identify_marketplace(store="Shoppe") == "shopee"


def test_identifica_magalu():
    assert identify_marketplace("https://www.magazineluiza.com.br/produto") == "magalu"


def test_identifica_temu():
    assert identify_marketplace("https://www.temu.com/br/item.html") == "temu"


def test_marketplace_suportado_sem_link_afiliado_nao_e_monetizavel():
    result = enrich_affiliate_data(
        {"store": "Shopee", "url": "https://shopee.com.br/produto/123"}
    )
    assert result.marketplace == "shopee"
    assert result.monetizable is False
    assert result.affiliate_url is None


def test_preserva_link_afiliado_existente():
    affiliate_url = "https://shope.ee/exemplo-afiliado"
    result = enrich_affiliate_data(
        {
            "store": "Shopee",
            "url": "https://shopee.com.br/produto/123",
            "affiliate_url": affiliate_url,
        }
    )
    assert result.marketplace == "shopee"
    assert result.monetizable is True
    assert result.affiliate_url == affiliate_url


def test_usa_link_padrao_da_temu_quando_oferta_nao_tem_afiliado():
    result = enrich_affiliate_data(
        {
            "store": "Temu",
            "url": "https://www.temu.com/br/produto/123",
        },
        fallback_urls={"temu": "https://temu.to/k/exemplo"},
    )

    assert result.marketplace == "temu"
    assert result.monetizable is True
    assert result.affiliate_url == "https://temu.to/k/exemplo"
