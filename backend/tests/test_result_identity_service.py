from app.services.result_identity import result_key


def normalize_store(value, fallback=""):
    return str(value or fallback).strip().lower()


def safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def url_identity(value):
    from app.services.offer_identity import offer_url_identity
    return offer_url_identity(value)


def key(item):
    return result_key(item, normalize_store, safe_float, url_identity)


def test_same_listing_url_ignores_different_catalog_ids():
    first = {"store": "sabina", "url": "https://www.sabina.com/es/item",
             "product_url": "https://www.sabina.com/es/item", "catalog_id": "a", "size_ml": 100}
    second = {**first, "catalog_id": "b"}
    assert key(first) == key(second)


def test_different_sizes_remain_distinct():
    first = {"store": "sabina", "url": "https://www.sabina.com/es/item", "size_ml": 50}
    second = {**first, "size_ml": 100}
    assert key(first) != key(second)


def test_variant_ids_remain_distinct_even_when_size_matches():
    first = {"store": "sabina", "url": "https://www.sabina.com/es/item", "size_ml": 100, "variant_id": "a"}
    second = {**first, "variant_id": "b"}
    assert key(first) != key(second)


def test_url_variant_selectors_remain_distinct():
    first = {"store": "easycosmetic", "url": "https://shop.example/item?variant=100", "size_ml": 100}
    second = {"store": "easycosmetic", "url": "https://shop.example/item?variant=200", "size_ml": 100}
    assert key(first) != key(second)


def test_sku_is_fallback_variant_identity_when_size_missing():
    first = {"store": "sabina", "url": "https://shop.example/item", "sku": "A"}
    second = {**first, "sku": "B"}
    assert key(first) != key(second)


def test_name_is_final_fallback_when_other_identity_is_missing():
    first = {"store": "sabina", "name": "Perfume A"}
    second = {"store": "sabina", "name": "Perfume B"}
    assert key(first) != key(second)
