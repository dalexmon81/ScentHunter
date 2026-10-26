from backend.catalog_engine import _first_offer


def test_first_offer_prefers_priced_offer_after_availability_only_entry():
    product = {
        "offers": [
            {"availability": "https://schema.org/InStock"},
            {"price": "28.90", "priceCurrency": "EUR", "availability": "https://schema.org/InStock"},
        ]
    }
    assert _first_offer(product)["price"] == "28.90"


def test_first_offer_uses_availability_only_entry_if_no_offer_has_price():
    product = {
        "offers": [
            {"availability": "https://schema.org/OutOfStock"},
            {"availability": "https://schema.org/InStock"},
        ]
    }
    assert _first_offer(product)["availability"] == "https://schema.org/OutOfStock"


def test_first_offer_keeps_single_offer_object_unchanged():
    offer = {"price": "23.00", "priceCurrency": "EUR"}
    assert _first_offer({"offers": offer}) is offer



def test_first_offer_prefers_nested_price_specification_price():
    product = {
        "offers": [
            {"availability": "https://schema.org/InStock"},
            {
                "priceSpecification": {
                    "@type": "PriceSpecification",
                    "price": "31.45",
                    "priceCurrency": "EUR",
                },
                "availability": "https://schema.org/InStock",
            },
        ]
    }
    selected = _first_offer(product)
    from backend.catalog_engine import _offer_price, _price_specification

    assert _offer_price(selected) == 31.45
    assert _price_specification(selected)["priceCurrency"] == "EUR"


def test_offer_price_does_not_infer_active_price_from_aggregate_low_price():
    from backend.catalog_engine import _offer_price

    assert _offer_price({"lowPrice": "19.99", "highPrice": "49.99"}) is None


def test_price_specification_list_uses_explicit_price():
    from backend.catalog_engine import _offer_price

    offer = {
        "priceSpecification": [
            {"@type": "DeliveryChargeSpecification", "price": "4.99"},
            {"@type": "UnitPriceSpecification", "price": "27.50", "priceCurrency": "EUR"},
        ]
    }
    assert _offer_price(offer) == 27.50



def test_price_specification_does_not_use_delivery_charge_as_product_price():
    from backend.catalog_engine import _offer_price

    offer = {
        "priceSpecification": {
            "@type": "DeliveryChargeSpecification",
            "price": "5.00",
        }
    }
    assert _offer_price(offer) is None



def test_catalog_refresh_preserves_existing_price_when_new_parse_has_no_price():
    # Guard the persistence contract: a successful page refresh with missing
    # price metadata must not erase the last known explicit price.
    from pathlib import Path

    source = Path("backend/catalog_engine.py").read_text(encoding="utf-8")
    assert "price=COALESCE(excluded.price,store_products.price)" in source
    assert "currency=CASE WHEN excluded.price IS NOT NULL THEN excluded.currency ELSE COALESCE(store_products.currency,excluded.currency) END" in source
