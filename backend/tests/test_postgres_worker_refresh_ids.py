from app.workers.postgres_worker import _refresh_external_id


def test_bplatz_refresh_uses_product_url_instead_of_gtin():
    url = "https://en.bplatz.de/products/liquid-brun-eau-de-parfum-100ml"
    assert _refresh_external_id("bplatz", "6290360375694", url) == url


def test_legacy_refresh_keeps_external_product_id():
    url = "https://www.deloox.be/product/example"
    assert _refresh_external_id("deloox-be", url, url) == url


def test_bplatz_without_product_url_is_not_given_a_gtin_fetch_key():
    assert _refresh_external_id("bplatz", "6290360375694", None) == ""
