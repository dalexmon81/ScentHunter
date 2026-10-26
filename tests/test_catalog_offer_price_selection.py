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
