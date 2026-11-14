import json
from unittest.mock import patch
from urllib.parse import quote

import pytest

import catalog_engine
import main
from scripts.refresh_notino_staging_pages import _refresh_product


def test_refresh_finds_retailer_only_gtin_and_hydrates_exact_destination():
    destination = "https://www.notino.fr/example/night-eau-de-parfum/p-123/"
    row = {
        "gtin": "4006381333931", "name": "Night Eau de Parfum 100 ml",
        "url": "https://www.kqzyfj.com/click-1-2?url=" + quote(destination, safe=""),
    }
    item = {
        "brand": "Example", "size_ml": 100, "price_num": 36,
        "concentration": "Eau de Parfum", "availability": "in stock", "url": destination,
    }
    with (
        patch("scripts.refresh_notino_staging_pages.search_notino_phase2", return_value=[]),
        patch("scripts.refresh_notino_staging_pages.search_notino_retailer_listings", return_value=[row]),
        patch("catalog_engine.refresh_url", return_value=item) as refresh,
    ):
        result = _refresh_product("Example Night", row["gtin"], "Example", 100, "Eau de Parfum")
    refresh.assert_called_once_with("notino", destination)
    assert result["price"] == 36


def test_refresh_refuses_conflicting_destinations_for_gtin():
    rows = [
        {"gtin": "4006381333931", "url": "https://www.kqzyfj.com/click-1-2?url=" + quote(
            f"https://www.notino.fr/example/night/p-{number}/", safe=""
        )}
        for number in (123, 456)
    ]
    with (
        patch("scripts.refresh_notino_staging_pages.search_notino_phase2", return_value=[]),
        patch("scripts.refresh_notino_staging_pages.search_notino_retailer_listings", return_value=rows),
        pytest.raises(ValueError, match="destination_not_unique"),
    ):
        _refresh_product("Example Night", "4006381333931", "Example", 100, "Eau de Parfum")


@pytest.mark.parametrize("brand,name,product_id", [
    ("Rasasi", "Hawas Ice", "16242201"),
    ("Rayhaan", "Aquatica", "16407892"),
])
def test_hydration_catalog_search_and_affiliate_merge(tmp_path, monkeypatch, brand, name, product_id):
    slug = name.lower().replace(" ", "-")
    destination = f"https://www.notino.fr/{brand.lower()}/{slug}-eau-de-parfum/p-{product_id}/"
    affiliate = "https://www.kqzyfj.com/click-1-2?url=" + quote(destination, safe="")
    product = {
        "@type": "Product", "name": f"{name} Eau de Parfum",
        "brand": {"name": brand}, "url": destination, "gtin13": "4006381333931",
        "offers": {"price": "36.00", "priceCurrency": "EUR",
                   "availability": "https://schema.org/InStock"},
    }
    html = (
        f'<script type="application/ld+json">{json.dumps(product)}</script>'
        f"<h1>{name} Eau de Parfum</h1><div>100&nbsp;ml <b>36,00 €</b></div>"
    ).encode()
    monkeypatch.setattr(catalog_engine, "DB_PATH", tmp_path / "catalog.sqlite3")
    monkeypatch.setattr(catalog_engine, "_SCHEMA_READY", False)
    monkeypatch.setattr(catalog_engine, "http_get", lambda *args, **kwargs: (200, destination, html))
    monkeypatch.setattr(catalog_engine, "_update_local_search_index_product", lambda *args, **kwargs: None)
    item = catalog_engine.refresh_url("notino", destination)
    assert item is not None
    rows = catalog_engine.search_local(f"{brand} {name}", per_store=50)
    hydrated = [row for row in rows if row.get("url") == destination]
    assert len(hydrated) == 1
    assert hydrated[0]["availability"] == "in_stock"
    feed = {
        "store": "notino", "brand": brand, "name": f"{name} Eau de Parfum 100 ml",
        "size_ml": 100, "variant": "EDP", "url": affiliate, "price_num": 32.50,
    }
    merged = main._merge_notino_phase2_offers([feed], hydrated)
    assert len(merged) == 1
    assert merged[0]["price_num"] == 36.0
    assert merged[0]["url"] == affiliate


def test_missing_page_size_cannot_refresh_an_existing_price(tmp_path, monkeypatch):
    destination = "https://www.notino.fr/example/night-eau-de-parfum/p-123/"
    monkeypatch.setattr(catalog_engine, "DB_PATH", tmp_path / "catalog.sqlite3")
    monkeypatch.setattr(catalog_engine, "_SCHEMA_READY", False)
    monkeypatch.setattr(catalog_engine, "_update_local_search_index_product", lambda *args, **kwargs: None)
    conn = catalog_engine.db()
    conn.execute(
        "INSERT INTO store_products(store,url,name,size_ml,price,fetched_at,fetch_status) VALUES(?,?,?,?,?,?,?)",
        ("notino", destination, "Night", 100, 37.4, 1000, "OK"),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(catalog_engine, "http_get", lambda *args, **kwargs: (200, destination, b""))
    monkeypatch.setattr(catalog_engine, "_secondary_store_parser", lambda *args, **kwargs: {
        "name": "Night Eau de Parfum", "price_num": 32.5, "size_ml": None,
    })
    assert catalog_engine.refresh_url("notino", destination) is None
    conn = catalog_engine.db()
    try:
        row = conn.execute(
            "SELECT price,size_ml,fetched_at FROM store_products WHERE store=? AND url=?",
            ("notino", destination),
        ).fetchone()
        assert tuple(row) == (37.4, 100, 1000)
    finally:
        conn.close()
