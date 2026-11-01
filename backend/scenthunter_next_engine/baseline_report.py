"""Export the complete offer-level Phase 0 baseline.

The exporter is read-only and fails closed: it never emits a partial baseline
when one of the eleven supported retailer catalogs has no persisted offers.
"""
from __future__ import annotations

import argparse
import csv
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from .catalog_repository import CatalogRepository
from .canonical_matcher import (
    _offer_name_forms,
    _variant_forms,
    normalize_brand_text,
    normalize_identity_text,
)


SUPPORTED_STORES = (
    "amazon_de", "amazon_fr", "bplatz", "deloox", "easycosmetic",
    "notino", "orioudh", "parfumcity", "parfumzentrum",
    "perfumemarket", "sabina",
)
VALID_STOCK = {
    "in_stock", "out_of_stock", "preorder", "backorder",
    "limited_availability", "available", "unavailable",
}
COLUMNS = (
    "store", "canonical_product_id", "canonical_variant_id", "brand",
    "fragrance", "concentration", "size_ml", "variant_type", "gtin",
    "external_product_id", "offer_url", "price", "currency",
    "availability", "captured_at", "source", "match_confidence",
    "match_status", "is_valid_offer",
)


class BaselineIncompleteError(RuntimeError):
    """Raised when the persisted retailer catalogs cannot support a full baseline."""


def _valid_url(value):
    try:
        parsed = urlparse(str(value or "").strip())
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except ValueError:
        return False


def _captured_at(value):
    try:
        timestamp = float(value)
        if timestamp <= 0:
            return ""
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def _rows(conn):
    tables = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    has_variants = "store_product_variants" in tables
    has_products = "store_products" in tables
    if not has_variants and not has_products:
        raise RuntimeError(
            "SQLite database has neither store_product_variants nor store_products"
        )

    records = []
    if has_variants:
        records.extend(conn.execute(
            """SELECT store, COALESCE(variant_url, url) AS offer_url,
                      url AS product_url, name, brand, sku, gtin, mpn,
                      size_ml, concentration, price, currency, availability,
                      fetched_at, variant_key, 'store_product_variants' AS source
                 FROM store_product_variants"""
        ).fetchall())
    if has_products:
        if has_variants:
            query = """SELECT p.store, p.url AS offer_url, p.url AS product_url,
                              p.name, p.brand, p.sku, p.gtin, p.mpn,
                              p.size_ml, p.concentration, p.price, p.currency,
                              p.availability, p.fetched_at, NULL AS variant_key,
                              'store_products' AS source
                         FROM store_products AS p
                        WHERE NOT EXISTS (
                            SELECT 1 FROM store_product_variants AS v
                             WHERE v.store = p.store AND v.url = p.url
                        )"""
        else:
            query = """SELECT store, url AS offer_url, url AS product_url,
                              name, brand, sku, gtin, mpn, size_ml,
                              concentration, price, currency, availability,
                              fetched_at, NULL AS variant_key,
                              'store_products' AS source
                         FROM store_products"""
        records.extend(conn.execute(query).fetchall())
    return records, tables


def _catalog_matcher(catalog):
    """Build conservative exact-name indexes; never invent fuzzy identities."""
    products_by_key = defaultdict(dict)
    variants_by_key = defaultdict(list)
    for product in catalog.all_products():
        brand = normalize_brand_text(product.brand)
        product_forms = set()
        for value in (product.name, *product.aliases):
            product_forms.update(_offer_name_forms(value, product.brand))
        for form in product_forms:
            products_by_key[brand][form] = product
        for variant in product.variants:
            for form in _variant_forms(variant, product.brand):
                products_by_key[brand][form] = product
                variants_by_key[(brand, form)].append((product, variant))
    return products_by_key, variants_by_key


def _match(row, catalog_indexes):
    products_by_key, variants_by_key = catalog_indexes
    brand_raw = str(row["brand"] or "").strip()
    brand = normalize_brand_text(brand_raw) if brand_raw else ""
    raw_name = str(row["name"] or "").strip()
    forms = _offer_name_forms(raw_name, brand_raw or None)
    exact_title = normalize_identity_text(raw_name)

    candidates = {
        product.product_id: product
        for form in forms
        if (product := products_by_key.get(brand, {}).get(form)) is not None
    }
    if not candidates:
        return None, None, "", "unresolved"

    exact = {
        product.product_id: product
        for product in candidates.values()
        if normalize_identity_text(product.name) == exact_title
    }
    if exact:
        candidates = exact
    if len(candidates) != 1:
        return None, None, "", "ambiguous"

    product = next(iter(candidates.values()))
    size = row["size_ml"]
    try:
        size = float(size) if size not in (None, "") else None
    except (TypeError, ValueError):
        size = None

    variant_matches = []
    for form in forms:
        variant_matches.extend(variants_by_key.get((brand, form), []))
    variant_matches = [
        (candidate_product, variant)
        for candidate_product, variant in variant_matches
        if candidate_product.product_id == product.product_id
    ]

    if size is not None:
        sized = [
            variant for variant in product.variants
            if variant.size_ml is not None and abs(variant.size_ml - size) < 0.01
        ]
        if len(sized) == 1:
            if variant_matches and all(v.variant_id != sized[0].variant_id for _, v in variant_matches):
                return product, None, "", "unresolved"
            return product, sized[0], "1.0", "matched"
        if len(sized) > 1:
            return product, None, "", "ambiguous"
        return product, None, "", "unresolved"

    unique_aliases = {v.variant_id: v for p, v in variant_matches}
    if len(unique_aliases) == 1:
        return product, next(iter(unique_aliases.values())), "1.0", "matched"
    if len(product.variants) == 1:
        return product, product.variants[0], "0.95", "matched"
    return product, None, "", "unresolved"


def generate(catalog_path: Path, db_path: Path, output_path: Path) -> dict:
    catalog = CatalogRepository.from_file(catalog_path)
    catalog_indexes = _catalog_matcher(catalog)
    if not db_path.is_file():
        raise FileNotFoundError(f"Retailer SQLite database not found: {db_path}")

    conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        records, tables = _rows(conn)
        indexed_urls = {}
        if "store_urls" in tables:
            indexed_urls = {
                row["store"]: int(row["active_urls"] or 0)
                for row in conn.execute(
                    """SELECT store, SUM(CASE WHEN active=1 THEN 1 ELSE 0 END) AS active_urls
                         FROM store_urls GROUP BY store"""
                )
            }
    finally:
        conn.close()

    seen = set()
    rows_out = []
    counts = defaultdict(int)
    duplicates = 0
    for row in records:
        store = str(row["store"] or "").strip().lower()
        if store not in SUPPORTED_STORES:
            continue
        offer_url = str(row["offer_url"] or "").strip()
        sku = str(row["sku"] or "").strip()
        mpn = str(row["mpn"] or "").strip()
        gtin = str(row["gtin"] or "").strip()
        external_id = sku or mpn
        try:
            price = float(row["price"]) if row["price"] is not None else None
        except (TypeError, ValueError):
            price = None
        currency = str(row["currency"] or "").strip().upper()
        availability = str(row["availability"] or "").strip().lower()
        try:
            size_ml = float(row["size_ml"]) if row["size_ml"] not in (None, "") else None
        except (TypeError, ValueError):
            size_ml = None

        # An offer is unique by retailer, destination, retailer ID and format.
        # Price is deliberately not part of the key: repeated captures are not
        # allowed to masquerade as distinct offers.
        dedupe_key = (
            store, offer_url, external_id, gtin, size_ml,
            str(row["concentration"] or "").strip().casefold(),
        )
        if dedupe_key in seen:
            duplicates += 1
            continue
        seen.add(dedupe_key)

        product, variant, confidence, match_status = _match(row, catalog_indexes)
        valid_price = price is not None and price > 0
        valid_currency = len(currency) == 3
        valid_stock = availability in VALID_STOCK
        valid_offer = valid_price and _valid_url(offer_url) and valid_currency and valid_stock
        counts[store] += 1
        rows_out.append({
            "store": store,
            "canonical_product_id": product.product_id if product else "",
            "canonical_variant_id": variant.variant_id if variant else "",
            "brand": product.brand if product else str(row["brand"] or "").strip(),
            "fragrance": product.name if product else str(row["name"] or "").strip(),
            "concentration": (
                product.concentration if product and product.concentration
                else str(row["concentration"] or "").strip()
            ),
            "size_ml": variant.size_ml if variant and variant.size_ml is not None else size_ml or "",
            "variant_type": "retailer_variant" if row["variant_key"] else "base_offer",
            "gtin": gtin,
            "external_product_id": external_id,
            "offer_url": offer_url,
            "price": price if price is not None else "",
            "currency": currency,
            "availability": availability,
            "captured_at": _captured_at(row["fetched_at"]),
            "source": str(row["source"]),
            "match_confidence": confidence,
            "match_status": match_status,
            "is_valid_offer": "true" if valid_offer else "false",
        })

    missing = [
        store for store in SUPPORTED_STORES
        if counts.get(store, 0) == 0
    ]
    if missing:
        details = {
            store: {"offers": counts.get(store, 0), "indexed_urls": indexed_urls.get(store, 0)}
            for store in missing
        }
        raise BaselineIncompleteError(
            "No persisted offer rows for required retailers; refusing partial baseline: "
            + str(details)
        )

    rows_out.sort(key=lambda item: (
        item["store"], item["offer_url"], item["external_product_id"],
        str(item["size_ml"]), str(item["price"]),
    ))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows_out)

    return {
        "catalog_products": catalog.product_count(),
        "catalog_variants": catalog.variant_count(),
        "offers": len(rows_out),
        "stores": len({row["store"] for row in rows_out}),
        "duplicate_rows_skipped": duplicates,
        "valid_offers": sum(row["is_valid_offer"] == "true" for row in rows_out),
        "matched_offers": sum(row["match_status"] == "matched" for row in rows_out),
        "unresolved_offers": sum(row["match_status"] == "unresolved" for row in rows_out),
        "ambiguous_offers": sum(row["match_status"] == "ambiguous" for row in rows_out),
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
