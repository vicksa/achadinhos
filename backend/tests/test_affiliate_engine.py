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


def test_usa_loja_do_influenciador_magalu_como_fallback():
    result = enrich_affiliate_data(
        {
            "store": "Magalu",
            "url": "https://www.magazineluiza.com.br/produto/123",
        },
        fallback_urls={
            "magalu": "https://www.magazinevoce.com.br/magazinedescontovipi/"
        },
    )

    assert result.marketplace == "magalu"
    assert result.monetizable is True
    assert result.affiliate_url == (
        "https://www.magazinevoce.com.br/magazinedescontovipi/"
    )


def test_identifica_shein_por_loja_e_dominios():
    assert identify_marketplace(store=" SHEIN ") == "shein"
    for url in (
        "https://br.shein.com/produto-p-123.html",
        "https://www.shein.com.br/produto",
        "https://onelink.shein.com/exemplo",
        "https://shein.top/exemplo",
    ):
        assert identify_marketplace(url) == "shein"
    assert identify_marketplace("https://shein.com.evil.example/produto") is None
    assert identify_marketplace("https://fakeshein.com/produto") is None


def test_shein_sem_link_convertido_nao_e_monetizavel():
    for url in ("https://br.shein.com/produto-p-123.html", "https://shein.top/exemplo"):
        result = enrich_affiliate_data({"url": url})
        assert result.marketplace == "shein"
        assert result.monetizable is False
        assert result.affiliate_url is None


def test_shein_preserva_link_convertido_por_produto():
    link = "https://onelink.shein.com/exemplo?tracking=emitido-pelo-portal"
    result = enrich_affiliate_data({
        "store": "SHEIN",
        "url": "https://br.shein.com/produto-p-123.html",
        "affiliate_url": link,
    })
    assert result.marketplace == "shein"
    assert result.monetizable is True
    assert result.affiliate_url == link
