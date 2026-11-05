"""Import canonical identities and explicitly declared variants only.

Products without known variants are retained as fragrance identities. No
variant is inferred, no retailer offer is imported, and the source/legacy
catalog databases are never modified. Dry-run is the default.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
import uuid
from pathlib import Path

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))
from app.db import make_engine
from app.models import Brand, Fragrance, ProductVariant, Store, LegacyProductIdMap, LegacyVariantIdMap
from app.services.product_normalization import normalize_brand

NAMESPACE = uuid.UUID("f12f2c2b-4c1f-4f4e-9b14-67d59d4b7f21")

# Deliberately seed only Bplatz while its Phase 2 adapter is being validated.
# Other retailer stores remain operator-managed and are never touched here.
BPLATZ_STORE = {
    "name": "Bplatz",
    "slug": "bplatz",
    "domain": "bplatz.de",
    "country": "DE",
    "currency": "EUR",
    "status": "active",
}


def norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch)).lower()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", norm(value)).strip("-")


def stable_id(kind: str, source_id: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"{kind}:{source_id}")


def get_or_create_brand(session: Session, normalized_name: str, name: str) -> Brand:
    """Resolve an existing brand by either canonical name or unique slug.

    Legacy seed data can contain a display-name normalization that differs
    from the current normalizer while retaining the same stable slug. Reuse
    that row instead of attempting a second insert that violates uq_brands_slug.
    If the two identifiers point to different rows, stop for manual review.
    """
    normalized_match = session.scalar(
        select(Brand).where(Brand.normalized_name == normalized_name)
    )
    slug_match = session.scalar(
        select(Brand).where(Brand.slug == slugify(name))
    )
    if (
        normalized_match is not None
        and slug_match is not None
        and normalized_match.id != slug_match.id
    ):
        raise RuntimeError(
            f"Brand identity conflict for {name!r}: normalized name and slug "
            "resolve to different existing rows."
        )

    existing = normalized_match or slug_match
    if existing is not None:
        return existing

    brand = Brand(
        id=stable_id("brand", normalized_name),
        name=name,
        slug=slugify(name),
        normalized_name=normalized_name,
    )
    session.add(brand)
    return brand


def validate_catalog(raw: dict) -> tuple[list[dict], dict[str, list[dict]], list[str]]:
    products = raw.get("products")
    variants = raw.get("variants")
    if not isinstance(products, list) or not isinstance(variants, list):
        raise SystemExit("STOP: catalog must contain products[] and variants[]")

    blocked: list[str] = []
    product_ids: set[str] = set()
    by_product: dict[str, list[dict]] = {}
    variant_ids: set[str] = set()

    for index, row in enumerate(products):
        if not isinstance(row, dict):
            blocked.append(f"products[{index}]: row is not an object")
            continue
        pid = str(row.get("product_id") or "").strip()
        if not pid:
            blocked.append(f"products[{index}]: missing product_id")
            continue
        if pid in product_ids:
            blocked.append(f"{pid}: duplicate product_id")
        product_ids.add(pid)
        if not str(row.get("brand_name") or "").strip():
            blocked.append(f"{pid}: missing brand_name")
        if not str(row.get("canonical_name") or "").strip():
            blocked.append(f"{pid}: missing canonical_name")

    for index, row in enumerate(variants):
        if not isinstance(row, dict):
            blocked.append(f"variants[{index}]: row is not an object")
            continue
        pid = str(row.get("product_id") or "").strip()
        source_id = str(row.get("variant_id") or "").strip()
        if not pid or pid not in product_ids:
            blocked.append(f"variants[{index}]: missing or unknown product_id {pid!r}")
            continue
        if not source_id:
            blocked.append(f"variants[{index}]: missing variant_id")
            continue
        if source_id in variant_ids:
            blocked.append(f"{source_id}: duplicate variant_id")
            continue
        variant_ids.add(source_id)
        size = row.get("size_ml")
        if size not in (None, ""):
            try:
                numeric_size = int(size)
                if numeric_size <= 0 or str(numeric_size) != str(size).strip():
                    raise ValueError
            except (TypeError, ValueError):
                blocked.append(f"{source_id}: invalid size_ml {size!r}")
                continue
        by_product.setdefault(pid, []).append(row)

    return products, by_product, blocked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default=str(ROOT / "backend" / "product_catalog.json"))
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write canonical identities to the configured isolated catalog after reviewing dry-run",
    )
    parser.add_argument(
        "--seed-bplatz-store",
        action="store_true",
        help="explicitly create or activate the Bplatz store row for the dedicated Bplatz integration test",
    )
    args = parser.parse_args()

    with Path(args.catalog).open(encoding="utf-8") as handle:
        raw = json.load(handle)

    products, by_product, blocked = validate_catalog(raw)
    if blocked:
        print(json.dumps({
            "status": "blocked",
            "blocked_count": len(blocked),
            "examples": blocked[:25],
            "source_modified": False,
            "database_written": False,
        }, ensure_ascii=False, indent=2))
        return 2

    names: dict[str, str] = {}
    for row in products:
        names.setdefault(normalize_brand(str(row["brand_name"])), str(row["brand_name"]).strip())

    products_without_variants = [
        str(row["product_id"]).strip()
        for row in products
        if not by_product.get(str(row["product_id"]).strip())
    ]
    variant_count = sum(
        len(by_product.get(str(row["product_id"]).strip(), []))
        for row in products
    )
    source_brands = raw.get("brands") if isinstance(raw.get("brands"), list) else []
    report = {
        "status": "validated",
        "source_brand_records": len(source_brands),
        "brands": len(names),
        "fragrances": len(products),
        "variants": variant_count,
        "products_without_variants": len(products_without_variants),
        "products_without_variants_examples": products_without_variants[:25],
        "offers_imported": 0,
        "stores_to_seed": [BPLATZ_STORE.copy()] if args.seed_bplatz_store else [],
        "database_written": False,
        "source_modified": False,
    }
    if not args.apply:
        report["next_step"] = "review report, then rerun with --apply"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    engine = make_engine()
    try:
        with Session(engine) as session, session.begin():
            brand_rows = {}
            for key, name in names.items():
                brand_rows[key] = get_or_create_brand(session, key, name)
            session.flush()

            for product in products:
                pid = str(product["product_id"]).strip()
                brand = brand_rows[normalize_brand(str(product["brand_name"]))]
                name = str(product["canonical_name"]).strip()
                fragrance = session.scalar(select(Fragrance).where(
                    Fragrance.brand_id == brand.id,
                    Fragrance.slug == slugify(name),
                ))
                if fragrance is None:
                    fragrance = Fragrance(
                        id=stable_id("fragrance", pid),
                        brand_id=brand.id,
                        name=name,
                        slug=slugify(name),
                        gender=product.get("gender"),
                        family=product.get("family_name"),
                        description=product.get("description"),
                        image_url=product.get("canonical_image"),
                    )
                    session.add(fragrance)
                session.flush()

                product_map = session.get(LegacyProductIdMap, pid)
                if product_map is None:
                    session.add(LegacyProductIdMap(legacy_product_id=pid, fragrance_id=fragrance.id))
                elif product_map.fragrance_id != fragrance.id:
                    raise RuntimeError(f"Legacy product ID {pid} is already mapped to a different fragrance UUID.")

                for variant in by_product.get(pid, []):
                    source_id = str(variant["variant_id"]).strip()
                    concentration = variant.get("concentration") or product.get("concentration")
                    size = variant.get("size_ml")
                    key = "|".join((
                        normalize_brand(str(product["brand_name"])),
                        norm(name),
                        norm(str(concentration or "")),
                        str(size or ""),
                        str(bool(variant.get("is_tester", False))),
                        str(bool(variant.get("is_refill", False))),
                        str(bool(variant.get("is_gift_set", False))),
                        source_id,
                    ))
                    variant_id = stable_id("variant", source_id)
                    variant_row = session.get(ProductVariant, variant_id)
                    if variant_row is None:
                        variant_row = ProductVariant(
                            id=variant_id,
                            fragrance_id=fragrance.id,
                            concentration=concentration,
                            size_ml=int(size) if size not in (None, "") else None,
                            is_tester=variant.get("is_tester"),
                            is_refill=variant.get("is_refill"),
                            is_gift_set=variant.get("is_gift_set"),
                            gtin=variant.get("gtin"),
                            canonical_key=str(variant.get("canonical_key") or key[:320]),
                        )
                        session.add(variant_row)
                        session.flush()
                    elif variant_row.fragrance_id != fragrance.id:
                        raise RuntimeError(f"Legacy variant ID {source_id} resolves to a variant of another fragrance.")

                    variant_map = session.get(LegacyVariantIdMap, source_id)
                    if variant_map is None:
                        session.add(LegacyVariantIdMap(
                            legacy_variant_id=source_id,
                            product_variant_id=variant_row.id,
                        ))
                    elif variant_map.product_variant_id != variant_row.id:
                        raise RuntimeError(f"Legacy variant ID {source_id} is already mapped to a different variant UUID.")

        # Retailer activation is opt-in. Canonical catalog seeding must not
        # silently activate Bplatz (or any other store) in staging.
        if args.seed_bplatz_store:
            with Session(engine) as session, session.begin():
                store = session.scalar(select(Store).where(Store.slug == BPLATZ_STORE["slug"]))
                if store is None:
                    session.add(Store(**BPLATZ_STORE))
                else:
                    for field, value in BPLATZ_STORE.items():
                        setattr(store, field, value)

        inspector = inspect(engine)
        expected_tables = {
            "brands", "fragrances", "product_variants", "stores",
            "offers", "price_history", "match_audit", "ingestion_runs",
            "ingestion_raw", "legacy_product_id_map", "legacy_variant_id_map",
        }
        actual_tables = set(inspector.get_table_names())
        if not expected_tables.issubset(actual_tables):
            raise RuntimeError(
                f"Catalog schema incomplete: missing {sorted(expected_tables - actual_tables)}"
            )
        with engine.connect() as connection:
            invalid_active_offers = connection.execute(text(
                "SELECT COUNT(*) FROM offers WHERE status = 'active' AND "
                "(price IS NULL OR url IS NULL OR length(trim(url)) = 0 OR availability IS NULL)"
            )).scalar_one()
            counts = {
                table: connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
                for table in sorted(expected_tables)
            }
        if invalid_active_offers:
            raise RuntimeError(
                f"Found {invalid_active_offers} active offers with missing price/url/availability"
            )
        report.update({
            "status": "seeded",
            "tables": sorted(expected_tables),
            "database_counts": counts,
            "invalid_active_offers": invalid_active_offers,
            "database_written": True,
            "stores_seeded": [BPLATZ_STORE["slug"]] if args.seed_bplatz_store else [],
        })
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
