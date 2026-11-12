"""Regression tests for Notino public discovery and product URL recognition."""

from types import SimpleNamespace
import sqlite3
import time

from backend.scrapers.notino import legacy_public, scraper as notino_scraper


def test_price_bearing_search_card_is_parsed_without_page_enrichment():
    candidate = {
        "url": "https://www.notino.fr/dior/sauvage-eau-de-parfum/p-123456/",
        "name": "Dior Sauvage Eau de Parfum 100 ml",
        "card_text": "Dior Sauvage Eau de Parfum 100 ml 89,90€ En stock",
        "stock": False,
    }

    row = legacy_public._card_result(candidate, "Dior Sauvage Eau de Parfum 100 ml")

    assert row is not None
    assert row["url"] == candidate["url"]
    assert row["price"] == "89,90€"
    assert row["size_ml"] == 100
    assert row["concentration"] == "Eau de Parfum"


def test_discovery_collects_direct_html_candidates_before_reader_fallback(monkeypatch):
    candidate = {
        "url": "https://www.notino.fr/dior/sauvage-eau-de-parfum/p-123456/",
        "name": "Dior Sauvage Eau de Parfum 100 ml",
        "score": 100,
    }
    monkeypatch.setattr(legacy_public, "_search_urls", lambda query: ["https://www.notino.fr/search.asp?exps=Dior"])
    monkeypatch.setattr(
        legacy_public,
        "_request",
        lambda session, url: SimpleNamespace(text="<html></html>", status_code=200),
    )
    monkeypatch.setattr(legacy_public, "_html_candidates", lambda html, query: [candidate])
    monkeypatch.setattr(
        legacy_public,
        "_reader_search",
        lambda session, url: (None, "reader unavailable"),
    )

    candidates, report = legacy_public._discover("Dior Sauvage Eau de Parfum 100 ml", object())

    assert candidates == [candidate]
    assert report["direct"][0]["candidates"] == 1
    assert report["reader"][0]["error"] == "reader unavailable"


def test_descriptive_notino_product_slug_without_numeric_id_is_accepted():
    url = "https://www.notino.fr/rayhaan/aquatica-eau-de-parfum-pour-homme/"
    assert legacy_public.lookslikeproducturl(url)
    assert notino_scraper.lookslikeproducturl(url)


def test_generic_notino_brand_product_root_without_product_identity_is_rejected():
    url = "https://www.notino.fr/rayhaan/aquatica/"
    assert not legacy_public.lookslikeproducturl(url)
    assert not notino_scraper.lookslikeproducturl(url)


def test_active_scraper_parses_descriptive_rayhaan_aquatica_page_price_and_stock():
    url = "https://www.notino.fr/rayhaan/aquatica-eau-de-parfum-pour-homme/"
    html = """
    <html>
      <head>
        <meta property="product:price:amount" content="40.90">
        <meta property="product:price:currency" content="EUR">
      </head>
      <body>
        <h1>Rayhaan Aquatica Eau de Parfum pour homme</h1>
        <button>100 ml - Ajouter au panier</button>
        <div>32,72 € avec le code BFSALE</div>
        <div>Prix actuel 40,90 € -20%</div>
      </body>
    </html>
    """

    row = notino_scraper._parse_product(url, html, "Rayhaan Aquatica")

    assert row is not None
    assert row["url"] == url
    assert row["name"] == "Rayhaan Aquatica Eau de Parfum pour homme"
    assert row["price_num"] == 32.72
    assert row["price"] == "32.72 €"
    assert row["regular_price_num"] == 40.90
    assert row["regular_price"] == "40.90 €"
    assert row["coupon_code"] == "BFSALE"
    assert row["coupon_required"] is True
    assert row["currency"] == "EUR"
    assert row["size_ml"] == 100
    assert row["availability"] == "in stock"



def test_catalog_hydration_adapter_uses_coupon_aware_product_parser():
    url = "https://www.notino.fr/rayhaan/aquatica-eau-de-parfum-pour-homme/"
    html = """
    <html>
      <head>
        <meta property="product:price:amount" content="40.90">
        <meta property="product:price:currency" content="EUR">
      </head>
      <body>
        <h1>Rayhaan Aquatica Eau de Parfum pour homme</h1>
        <button>100 ml - Ajouter au panier</button>
        <div>32,72 € avec le code BFSALE</div>
      </body>
    </html>
    """

    row = notino_scraper.extract_product_page(None, url, "rayhaan aquatica", html=html)

    assert row is not None
    assert row["price_num"] == 32.72
    assert row["regular_price_num"] == 40.90
    assert row["coupon_code"] == "BFSALE"





def test_catalog_search_returns_coupon_price_and_keeps_regular_price(monkeypatch):
    from backend.scrapers.notino import affiliate_feed
    import catalog_engine

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE store_urls(store TEXT, url TEXT, active INTEGER);
        CREATE TABLE store_product_variants(
            store TEXT, url TEXT, variant_key TEXT, name TEXT, brand TEXT,
            image TEXT, sku TEXT, gtin TEXT, mpn TEXT, size_ml REAL,
            concentration TEXT, gender TEXT, price REAL, currency TEXT,
            availability TEXT, fetched_at REAL, variant_url TEXT,
            regular_price REAL, coupon_code TEXT, coupon_required INTEGER
        );
    """)
    url = "https://www.notino.fr/rayhaan/aquatica-eau-de-parfum-pour-homme/"
    now = time.time()
    conn.execute("INSERT INTO store_urls VALUES(?,?,1)", ("notino", url))
    conn.execute(
        """INSERT INTO store_product_variants(
               store,url,variant_key,name,brand,size_ml,price,currency,
               availability,fetched_at,variant_url,regular_price,coupon_code,coupon_required)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "notino", url, "100ml:SKU", "Rayhaan Aquatica Eau de Parfum pour homme",
            "Rayhaan", 100, 32.72, "EUR", "in_stock", now, url,
            40.90, "BFSALE", 1,
        ),
    )
    conn.commit()
    monkeypatch.setattr(catalog_engine, "db", lambda: conn)

    report = affiliate_feed.search_feed("Rayhaan Aquatica")

    assert report["status"] == "success"
    assert len(report["results"]) == 1
    row = report["results"][0]
    assert row["price_num"] == 32.72
    assert row["regular_price_num"] == 40.90
    assert row["coupon_code"] == "BFSALE"
    assert row["coupon_required"] is True
    assert row["url"] == url


def test_legacy_notino_product_id_url_remains_accepted():
    url = "https://www.notino.fr/dior/sauvage-eau-de-parfum/p-123456/"
    assert legacy_public.lookslikeproducturl(url)
    assert notino_scraper.lookslikeproducturl(url)
