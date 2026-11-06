from app.services.offer_identity import (
    is_dior_line_url_mismatch,
    offer_concentration_token,
)


def test_concentration_parser_prefers_intense_edp_and_edt():
    assert offer_concentration_token("Dior Sauvage Eau de Parfum Intense") == "edp_intense"
    assert offer_concentration_token("Sauvage EDT Intense") == "edt_intense"


def test_concentration_parser_recognizes_standard_concentrations():
    cases = {
        "Eau de Parfum": "edp",
        "EDT 100 ml": "edt",
        "Eau de Cologne": "edc",
        "Extrait de Parfum": "extrait",
        "Parfum": "parfum",
    }
    for value, expected in cases.items():
        assert offer_concentration_token(value) == expected


def test_elixir_wins_over_generic_parfum_url_descriptor():
    assert offer_concentration_token("dior-sauvage-elixir-parfum-60ml") == "elixir"


def test_concentration_parser_handles_empty_and_non_string_values():
    assert offer_concentration_token(None) == ""
    assert offer_concentration_token("") == ""
    assert offer_concentration_token(123) == ""


def test_concentration_parser_does_not_match_partial_words():
    assert offer_concentration_token("EDPextra") == ""
    assert offer_concentration_token("parfumery") == ""


def test_dior_line_guard_rejects_sauvage_title_linked_to_eau_sauvage():
    assert is_dior_line_url_mismatch({
        "name": "Dior Sauvage Eau de Toilette",
        "url": "https://shop.example/dior-eau-sauvage-edt",
    }) is True


def test_dior_line_guard_rejects_eau_sauvage_title_linked_to_sauvage():
    assert is_dior_line_url_mismatch({
        "name": "Dior Eau Sauvage Eau de Toilette",
        "url": "https://shop.example/dior-sauvage-edt",
    }) is True


def test_dior_line_guard_accepts_matching_product_line():
    assert is_dior_line_url_mismatch({
        "name": "Dior Eau Sauvage Eau de Toilette",
        "url": "https://shop.example/dior-eau-sauvage-edt",
    }) is False
    assert is_dior_line_url_mismatch({
        "name": "Dior Sauvage Eau de Toilette",
        "url": "https://shop.example/dior-sauvage-edt",
    }) is False


def test_dior_line_guard_ignores_non_dictionary_values():
    assert is_dior_line_url_mismatch(None) is False
    assert is_dior_line_url_mismatch("Dior Sauvage") is False


def test_concentration_mismatch_guard_rejects_edp_title_linked_to_edt():
    from app.services.offer_identity import is_concentration_mismatch_offer

    assert is_concentration_mismatch_offer({
        "name": "Dior Sauvage Eau de Parfum",
        "url": "https://shop.example/dior-sauvage-eau-de-toilette",
    }) is True


def test_concentration_mismatch_guard_rejects_known_brand_conflict():
    from app.services.offer_identity import is_concentration_mismatch_offer

    assert is_concentration_mismatch_offer({
        "name": "French Avenue Chaos",
        "brand": "French Avenue",
        "url": "https://shop.example/vertus-chaos",
    }) is True


def test_concentration_mismatch_guard_accepts_consistent_identity():
    from app.services.offer_identity import is_concentration_mismatch_offer

    assert is_concentration_mismatch_offer({
        "name": "Dior Sauvage Eau de Parfum",
        "brand": "Dior",
        "url": "https://shop.example/dior-sauvage-eau-de-parfum",
    }) is False


def test_concentration_mismatch_guard_ignores_non_dictionary_values():
    from app.services.offer_identity import is_concentration_mismatch_offer

    assert is_concentration_mismatch_offer(None) is False
    assert is_concentration_mismatch_offer("Dior Sauvage") is False


def test_offer_url_identity_ignores_tracking_and_www_noise():
    from app.services.offer_identity import offer_url_identity

    assert offer_url_identity(
        "HTTPS://WWW.Shop.Example/Product/?utm_source=newsletter&gclid=abc"
    ) == "https://shop.example/product"


def test_offer_url_identity_preserves_variant_selectors():
    from app.services.offer_identity import offer_url_identity

    first = offer_url_identity("https://shop.example/item?variant=100&color=blue")
    second = offer_url_identity("https://shop.example/item?variant=200&color=blue")
    assert first == "https://shop.example/item?variant=100"
    assert second == "https://shop.example/item?variant=200"
    assert first != second


def test_offer_url_identity_preserves_selector_fragments():
    from app.services.offer_identity import offer_url_identity

    assert offer_url_identity("https://shop.example/item#size-100ml") == (
        "https://shop.example/item#size-100ml"
    )


def test_offer_url_identity_handles_empty_and_malformed_values():
    from app.services.offer_identity import offer_url_identity

    assert offer_url_identity(None) == ""
    assert offer_url_identity("") == ""


def test_public_offer_url_normalizes_deloox_to_belgian_storefront():
    from app.services.public_offer_url import public_offer_url

    assert public_offer_url({
        "store": "deloox",
        "url": "https://www.deloox.es/product/item?variant=7#details",
    }) == "https://www.deloox.be/product/item?variant=7#details"


def test_public_offer_url_keeps_sabina_matching_size_fragment():
    from app.services.public_offer_url import public_offer_url

    result = public_offer_url({
        "store": "sabina",
        "url": "https://www.sabina.com/it/product/item#123-tama_o-100_ml",
        "size_ml": 100,
    })
    assert result == "https://www.sabina.com/es/product/item#123-tama_o-100_ml"


def test_public_offer_url_removes_stale_sabina_size_fragment():
    from app.services.public_offer_url import public_offer_url

    result = public_offer_url({
        "store": "sabina",
        "url": "https://www.sabina.com/es/product/item#123-tama_o-30_ml",
        "size_ml": 100,
    })
    assert result == "https://www.sabina.com/es/product/item"


def test_public_offer_url_leaves_other_retailers_unchanged():
    from app.services.public_offer_url import public_offer_url

    url = "https://shop.example/product?variant=100#details"
    assert public_offer_url({"store": "other", "url": url}) == url


def test_public_offer_url_handles_empty_url():
    from app.services.public_offer_url import public_offer_url

    assert public_offer_url({"store": "sabina", "url": ""}) == ""


def test_public_offer_projection_prefers_canonical_identity_and_preserves_availability():
    from app.services.public_offer import public_offer

    item = {
        "canonical_name": "Sauvage",
        "name": "Retailer Sauvage EDP",
        "canonical_brand": "Dior",
        "brand": "Retailer Brand",
        "store": "deloox",
        "price": "€99",
        "available": False,
        "availability": "OutOfStock",
        "stock_status": "out_of_stock",
        "_raw_name": "Retailer Sauvage EDP",
        "_raw_brand": "Retailer Brand",
    }
    result = public_offer(item, lambda value: "https://shop.example/canonical")
    assert result["name"] == "Sauvage"
    assert result["brand"] == "Dior"
    assert result["url"] == "https://shop.example/canonical"
    assert result["available"] is False
    assert result["availability"] == "OutOfStock"
    assert result["stock_status"] == "out_of_stock"
    assert result["raw_brand"] == "Retailer Brand"


def test_public_offer_projection_uses_name_and_manufacturer_fallbacks():
    from app.services.public_offer import public_offer

    result = public_offer(
        {"name": "Perfume", "manufacturer": "Brand", "image_url": "image"},
        lambda item: item.get("url"),
    )
    assert result["name"] == "Perfume"
    assert result["brand"] == "Brand"
    assert result["retailer_image"] == "image"


def test_public_offer_projection_does_not_mutate_source_item():
    from app.services.public_offer import public_offer

    item = {"name": "Perfume", "brand": "Brand"}
    original = dict(item)
    public_offer(item, lambda value: None)
    assert item == original
