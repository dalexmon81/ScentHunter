"""Generate a reproducible Phase 0 catalog/offer quality baseline CSV.

Reads the canonical JSON catalog and the local SQLite retailer catalog. It is
read-only: no network requests, scraping, or database writes are performed.
"""
from __future__ import annotations

import argparse
import csv
import sqlite3
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

from .catalog_repository import CatalogRepository
from .canonical_matcher import CanonicalMatcher
from .models import MatchStatus, RetailerOffer


VALID_STOCK = {"in_stock", "out_of_stock", "preorder", "backorder", "limited_availability"}
SUPPORTED_STORES = (
    "amazon_de", "amazon_fr", "bplatz", "deloox", "easycosmetic",
    "notino", "orioudh", "parfumcity", "parfumzentrum",
    "perfumemarket", "sabina",
)


def _valid_price(value, currency):
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return False
    return amount > 0 and currency == "EUR"


def _valid_url(value):
    try:
        parsed = urlparse(str(value or "").strip())
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except ValueError:
        return False


def _rows(conn):
    """Read every live offer exactly once, preferring variant rows over base rows."""
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    has_variants = "store_product_variants" in tables
    has_products = "store_products" in tables
    if has_variants and has_products:
        rows = conn.execute(
            """SELECT store, COALESCE(variant_url, url) AS product_url,
                      name, brand, sku, gtin, size_ml, concentration,
                      price, currency, availability
                 FROM store_product_variants
                UNION ALL
               SELECT p.store, p.url AS product_url, p.name, p.brand,
                      p.sku, p.gtin, p.size_ml, p.concentration,
                      p.price, p.currency, p.availability
                 FROM store_products AS p
                WHERE NOT EXISTS (
                    SELECT 1 FROM store_product_variants AS v
                     WHERE v.store = p.store AND v.url = p.url
                )
                ORDER BY store, product_url"""
        ).fetchall()
        if rows:
            return rows, "store_product_variants+store_products"
        return rows, "store_product_variants+store_products"
    if has_variants:
        rows = conn.execute(
            """SELECT store, COALESCE(variant_url, url) AS product_url,
                      name, brand, sku, gtin, size_ml, concentration,
                      price, currency, availability
                 FROM store_product_variants
                ORDER BY store, url, variant_key"""
        ).fetchall()
        return rows, "store_product_variants"
    if has_products:
        rows = conn.execute(
            """SELECT store, url AS product_url, name, brand, sku, gtin,
                      size_ml, concentration, price, currency, availability
                 FROM store_products
                ORDER BY store, url"""
        ).fetchall()
        return rows, "store_products"
    raise RuntimeError(
        "SQLite database has neither store_product_variants nor store_products"
    )

def generate(catalog_path: Path, db_path: Path, output_path: Path) -> dict:
    catalog = CatalogRepository.from_file(catalog_path)
    matcher = CanonicalMatcher(catalog)

    if not db_path.is_file():
        raise FileNotFoundError(
            f"Retailer SQLite database not found: {db_path}. "
            "Run this report in the environment containing the live catalog DB."
        )

    conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        records, source_table = _rows(conn)
    finally:
        conn.close()

    totals = defaultdict(lambda: {
        "offers": 0, "valid_price": 0, "valid_url": 0, "valid_stock": 0,
        "ambiguous": 0, "matched": 0, "unresolved": 0,
    })
    # Include every supported retailer even when the live database currently
    # contains zero offers for it. A missing row must not hide a coverage gap.
    for store in SUPPORTED_STORES:
        totals[store]

    for row in records:
        store = str(row["store"] or "unknown")
        item = totals[store]
        item["offers"] += 1

        if _valid_price(row["price"], str(row["currency"] or "").upper()):
            item["valid_price"] += 1
        if _valid_url(row["product_url"]):
            item["valid_url"] += 1
        if str(row["availability"] or "").strip().lower() in VALID_STOCK:
            item["valid_stock"] += 1

        offer = RetailerOffer(
            retailer=store,
            raw_name=str(row["name"] or "unknown product"),
            product_url=str(row["product_url"]) if row["product_url"] else None,
            retailer_product_id=str(row["gtin"] or row["sku"]) if (row["gtin"] or row["sku"]) else None,
            brand_raw=str(row["brand"]) if row["brand"] else None,
            size_ml=int(row["size_ml"]) if row["size_ml"] not in (None, "") and float(row["size_ml"]).is_integer() and float(row["size_ml"]) > 0 else None,
            price=None,
            currency=str(row["currency"] or "EUR").upper(),
            availability=str(row["availability"]) if row["availability"] else None,
            raw_payload={
                "gtin": row["gtin"],
                "sku": row["sku"],
                "concentration": row["concentration"],
            },
        )
        result = matcher.match(offer)
        if result.status is MatchStatus.AMBIGUOUS:
            item["ambiguous"] += 1
        elif result.status is MatchStatus.MATCHED:
            item["matched"] += 1
        else:
            item["unresolved"] += 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "store", "offer_count", "valid_price_count", "valid_price_pct",
        "valid_url_count", "valid_url_pct", "valid_stock_count",
        "valid_stock_pct", "ambiguous_match_count", "matched_count",
        "unresolved_match_count", "catalog_product_count", "offer_source_table",
    ]
    rows_out = []
    for store in sorted(totals):
        item = totals[store]
        count = item["offers"]
        rows_out.append({
            "store": store,
            "offer_count": count,
            "valid_price_count": item["valid_price"],
            "valid_price_pct": round(100 * item["valid_price"] / count, 2) if count else 0,
            "valid_url_count": item["valid_url"],
            "valid_url_pct": round(100 * item["valid_url"] / count, 2) if count else 0,
            "valid_stock_count": item["valid_stock"],
            "valid_stock_pct": round(100 * item["valid_stock"] / count, 2) if count else 0,
            "ambiguous_match_count": item["ambiguous"],
            "matched_count": item["matched"],
            "unresolved_match_count": item["unresolved"],
            "catalog_product_count": catalog.product_count(),
            "offer_source_table": source_table,
        })

    all_offers = sum(x["offer_count"] for x in rows_out)
    aggregate = {key: sum(x[key] for x in totals.values()) for key in (
        "valid_price", "valid_url", "valid_stock", "ambiguous", "matched", "unresolved"
    )}
    rows_out.append({
        "store": "TOTAL",
        "offer_count": all_offers,
        "valid_price_count": aggregate["valid_price"],
        "valid_price_pct": round(100 * aggregate["valid_price"] / all_offers, 2) if all_offers else 0,
        "valid_url_count": aggregate["valid_url"],
        "valid_url_pct": round(100 * aggregate["valid_url"] / all_offers, 2) if all_offers else 0,
        "valid_stock_count": aggregate["valid_stock"],
        "valid_stock_pct": round(100 * aggregate["valid_stock"] / all_offers, 2) if all_offers else 0,
        "ambiguous_match_count": aggregate["ambiguous"],
        "matched_count": aggregate["matched"],
        "unresolved_match_count": aggregate["unresolved"],
        "catalog_product_count": catalog.product_count(),
        "offer_source_table": source_table,
    })

    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows_out)

    return {
        "catalog_products": catalog.product_count(),
        "catalog_variants": catalog.variant_count(),
        "offers": all_offers,
        "stores": len(totals),
        "ambiguous_matches": aggregate["ambiguous"],
        "source_table": source_table,
        "output": str(output_path),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--catalog", type=Path, default=root / "product_catalog.json")
    parser.add_argument("--db", type=Path, default=root / "store_catalog.sqlite3")
    parser.add_argument("--output", type=Path, default=root / "reports" / "phase-0-retailer-baseline.csv")
    args = parser.parse_args()
    result = generate(args.catalog, args.db, args.output)
    for key, value in result.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
