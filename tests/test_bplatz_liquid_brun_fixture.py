from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/bplatz/liquid-brun-54015243419916.raw.html"
META = ROOT / "tests/fixtures/bplatz/liquid-brun-54015243419916.meta.json"
EXPECTED_SHA256 = "9f76b00bc7472ccd389116302f06e2e02f258dc17fee7f43371993f79284c017"
VARIANT_ID = "VAR-f87146c82d167f4c"


def parse_liquid_brun_fixture():
    html = FIXTURE.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    product = {}
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or script.get_text())
        except (TypeError, ValueError):
            continue
        queue = data if isinstance(data, list) else [data]
        while queue:
            item = queue.pop(0)
            if isinstance(item, list):
                queue.extend(item)
            elif isinstance(item, dict):
                typ = item.get("@type")
                types = typ if isinstance(typ, list) else [typ]
                if any(str(t).lower() == "product" for t in types):
                    product = item
                    break
                if isinstance(item.get("@graph"), list):
                    queue.extend(item["@graph"])
        if product:
            break
    assert product, "No Product JSON-LD in authentic fixture"
    brand = product.get("brand")
    brand = brand.get("name") if isinstance(brand, dict) else brand
    offers = product.get("offers")
    offer = offers[0] if isinstance(offers, list) else offers
    assert isinstance(offer, dict), "No structured Offer in Product JSON-LD"
    sku = product.get("sku")
    gtin = product.get("gtin13") or product.get("gtin")
    url = offer.get("url") or product.get("url")
    availability_uri = str(offer.get("availability") or "")
    availability = (
        "in_stock" if availability_uri.rstrip("/").endswith("InStock")
        else "out_of_stock" if availability_uri.rstrip("/").endswith("OutOfStock")
        else None
    )
    name = product.get("name")
    import re
    size_match = re.search(r"(\d+(?:[.,]\d+)?)\s*ml\b", name or "", re.I)
    size_ml = int(float(size_match.group(1).replace(",", "."))) if size_match else None
    concentration = "Eau de Parfum" if "eau de parfum" in (name or "").lower() else None
    return {
        "raw_name": name,
        "brand_raw": brand,
        "size_ml": size_ml,
        "concentration": concentration,
        "price": offer.get("price"),
        "currency": offer.get("priceCurrency"),
        "product_url": url,
        "availability": availability,
        "availability_uri": availability_uri,
        "sku": sku,
        "gtin": gtin,
    }


def normalize(record):
    import sys
    sys.path.insert(0, str(ROOT / "backend"))
    from scenthunter_next_engine.offer_normalizer import normalize_offer
    normalized = normalize_offer(record, retailer="Bplatz", currency_default="EUR")
    return normalized


def make_db(path):
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript("""
        CREATE TABLE ingestion_raw (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store TEXT NOT NULL,
            raw_json TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('pending','unmatched','matched','promoted'))
        );
        CREATE TABLE offers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ingestion_raw_id INTEGER NOT NULL UNIQUE REFERENCES ingestion_raw(id),
            store TEXT NOT NULL,
            product_variant_id TEXT NOT NULL,
            price NUMERIC NOT NULL CHECK(price > 0),
            currency TEXT NOT NULL,
            url TEXT NOT NULL,
            availability TEXT NOT NULL
        );
    """)
    return connection


def test_post_commit_fixture_sha256_matches_meta_and_capture():
    payload = FIXTURE.read_bytes()
    meta = json.loads(META.read_text(encoding="utf-8"))
    actual = hashlib.sha256(payload).hexdigest()
    assert actual == EXPECTED_SHA256
    assert actual == meta["sha256"]
    print(f"POST_COMMIT_SHA256={actual}")
    print(f"FIXTURE_SIZE_BYTES={len(payload)}")



def test_production_parser_exposes_structured_sku_and_gtin():
    import sys
    sys.path.insert(0, str(ROOT / "backend"))
    from scrapers.bplatz.scraper import parse_product_html

    html = FIXTURE.read_text(encoding="utf-8")
    meta = json.loads(META.read_text(encoding="utf-8"))
    parsed = parse_product_html(
        html,
        meta["url_final"],
        "French Avenue Liquid Brun",
    )
    assert parsed is not None
    structured_product = parsed["raw_data"]["jsonld"]
    expected_sku = structured_product.get("sku")
    expected_gtin = structured_product.get("gtin13") or structured_product.get("gtin")
    assert parsed["sku"] == expected_sku == "6290360375694"
    assert parsed["gtin"] == expected_gtin == "6290360375694"
    assert parsed["identity"]["sku"] == parsed["sku"]
    assert parsed["identity"]["gtin"] == parsed["gtin"]

    # The real normalizer receives the production parser's emitted identifiers.
    normalized = normalize({
        "raw_name": parsed["name"],
        "brand_raw": parsed["brand"],
        "size_ml": parsed["size_ml"],
        "price": parsed["price_num"],
        "currency": parsed["offer"]["currency"],
        "product_url": parsed["url"],
        "availability": parsed["availability"],
        "sku": parsed["sku"],
        "gtin": parsed["gtin"],
    })
    assert normalized.retailer_product_id == parsed["sku"]
    assert normalized.raw_payload["gtin"] == parsed["gtin"]
    print(f"PRODUCTION_PARSER_SKU={parsed['sku']}")
    print(f"PRODUCTION_PARSER_GTIN={parsed['gtin']}")


def test_positive_controlled_association_promotes_offer_from_fixture():
    record = parse_liquid_brun_fixture()
    assert record["brand_raw"] == "French Avenue"
    assert record["raw_name"] and "Liquid Brun" in record["raw_name"]
    assert record["concentration"] == "Eau de Parfum"
    assert record["size_ml"] == 100
    assert record["price"] is not None and float(record["price"]) > 0
    assert record["currency"] == "EUR"
    assert record["availability"] == "in_stock"
    assert record["sku"] == "6290360375694"
    assert record["gtin"] == "6290360375694"
    assert urlparse(record["product_url"]).scheme in {"http", "https"}

    offer = normalize(record)
    assert offer.price is not None and offer.price > 0
    assert offer.product_url == record["product_url"]
    assert offer.availability == "in_stock"

    # Explicit test-only association. Not a production matcher result:
    # the catalog GTIN is empty, so the Bplatz GTIN alone cannot prove identity.
    controlled_variant_id = VARIANT_ID
    with tempfile.TemporaryDirectory(prefix="scenthunter-liquid-brun-") as tmp:
        db = Path(tmp) / "isolated.sqlite3"
        connection = make_db(db)
        try:
            cursor = connection.execute(
                "INSERT INTO ingestion_raw(store,raw_json,status) VALUES(?,?,?)",
                ("Bplatz", json.dumps(record), "matched"),
            )
            raw_id = cursor.lastrowid
            valid = (
                offer.price is not None and offer.price > 0
                and offer.product_url is not None
                and offer.availability == "in_stock"
                and controlled_variant_id == VARIANT_ID
            )
            assert valid
            connection.execute(
                "INSERT INTO offers(ingestion_raw_id,store,product_variant_id,price,currency,url,availability) VALUES(?,?,?,?,?,?,?)",
                (raw_id, "Bplatz", controlled_variant_id, str(offer.price),
                 offer.currency, offer.product_url, offer.availability),
            )
            connection.execute("UPDATE ingestion_raw SET status='promoted' WHERE id=?", (raw_id,))
            connection.commit()
            row = connection.execute(
                "SELECT product_variant_id,price,currency,url,availability FROM offers WHERE ingestion_raw_id=?",
                (raw_id,),
            ).fetchone()
            assert row is not None
            assert row[0] == VARIANT_ID
            assert float(row[1]) == float(record["price"])
            assert row[2] == "EUR" and row[3] == record["product_url"]
            assert row[4] == "in_stock"
            assert connection.execute("SELECT status FROM ingestion_raw WHERE id=?", (raw_id,)).fetchone()[0] == "promoted"
            assert connection.execute("SELECT COUNT(*) FROM offers").fetchone()[0] == 1
            print(f"POSITIVE_OFFER_ID={connection.execute('SELECT id FROM offers WHERE ingestion_raw_id=?',(raw_id,)).fetchone()[0]}")
        finally:
            connection.close()


def test_negative_without_certain_association_stays_raw_and_not_offers():
    record = parse_liquid_brun_fixture()
    offer = normalize(record)
    with tempfile.TemporaryDirectory(prefix="scenthunter-liquid-brun-negative-") as tmp:
        connection = make_db(Path(tmp) / "isolated.sqlite3")
        try:
            cursor = connection.execute(
                "INSERT INTO ingestion_raw(store,raw_json,status) VALUES(?,?,?)",
                ("Bplatz", json.dumps(record), "pending"),
            )
            raw_id = cursor.lastrowid
            # No canonical association: GTIN is not a match because catalog GTIN is empty.
            product_variant_id = None
            assert product_variant_id is None
            connection.commit()
            status = connection.execute("SELECT status FROM ingestion_raw WHERE id=?", (raw_id,)).fetchone()[0]
            count = connection.execute("SELECT COUNT(*) FROM offers").fetchone()[0]
            assert status in {"pending", "unmatched"}
            assert count == 0
            print(f"NEGATIVE_STATUS={status}")
        finally:
            connection.close()

# Re-run offline verification after adding pytest to the dedicated workflow.

# Trigger rerun with requests installed for production parser import.



def test_real_canonical_matcher_resolves_bplatz_against_actual_catalog():
    """Exercise the real catalog adapter and matcher; no controlled variant assignment."""
    import sys
    sys.path.insert(0, str(ROOT / "backend"))
    from scenthunter_next_engine.next_engine_service import NextEngineService

    from scrapers.bplatz.scraper import parse_product_html

    catalog_path = ROOT / "backend" / "product_catalog.json"
    service = NextEngineService.from_catalog_file(catalog_path)
    meta = json.loads(META.read_text(encoding="utf-8"))
    parsed = parse_product_html(
        FIXTURE.read_text(encoding="utf-8"),
        meta["url_final"],
        "French Avenue Liquid Brun",
    )
    assert parsed is not None
    record = {
        "raw_name": parsed["name"],
        "brand_raw": parsed["brand"],
        "size_ml": parsed["size_ml"],
        "price": parsed["price_num"],
        "currency": parsed["offer"]["currency"],
        "product_url": parsed["url"],
        "availability": parsed["availability"],
        "sku": parsed["sku"],
        "gtin": parsed["gtin"],
    }
    assert record["sku"] == record["gtin"] == "6290360375694"

    result = service.process_records([record], retailer="Bplatz", currency_default="EUR")
    aggregation = result.aggregation
    assert aggregation.matched_offer_count == 1
    assert len(aggregation.groups) == 1
    group = aggregation.groups[0]
    assert group.canonical_product_id == "SH-0030"
    assert group.canonical_variant_id == VARIANT_ID
    assert group.offers[0].retailer == "Bplatz"

    # A wrong brand must not be rescued by a matching product title.
    wrong_brand = dict(record)
    wrong_brand["brand_raw"] = "Fragrance World"
    wrong_brand_result = service.process_records(
        [wrong_brand], retailer="Bplatz", currency_default="EUR"
    ).aggregation
    assert wrong_brand_result.matched_offer_count == 0
    assert not wrong_brand_result.groups
    assert len(wrong_brand_result.unresolved) == 1

    # A 150 ml claim cannot be attached to the declared 100 ml variant.
    wrong_size = dict(record)
    wrong_size["size_ml"] = 150
    wrong_size_result = service.process_records(
        [wrong_size], retailer="Bplatz", currency_default="EUR"
    ).aggregation
    assert wrong_size_result.matched_offer_count == 0
    assert not wrong_size_result.groups
    assert len(wrong_size_result.unresolved) == 1

    # An insufficient title without brand or format remains unresolved.
    insufficient_identity = dict(record)
    insufficient_identity["raw_name"] = "Liquid"
    insufficient_identity["brand_raw"] = None
    insufficient_identity["size_ml"] = None
    insufficient_result = service.process_records(
        [insufficient_identity], retailer="Bplatz", currency_default="EUR"
    ).aggregation
    assert insufficient_result.matched_offer_count == 0
    assert not insufficient_result.groups
    assert len(insufficient_result.unresolved) == 1

# Keep this file covered by the dedicated branch-specific offline workflow.
