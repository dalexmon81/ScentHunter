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
from app.models import Brand, Fragrance, ProductVariant

NAMESPACE = uuid.UUID("f12f2c2b-4c1f-4f4e-9b14-67d59d4b7f21")


def norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch)).lower()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", norm(value)).strip("-")


def stable_id(kind: str, source_id: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"{kind}:{source_id}")


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
        help="write canonical identities to the isolated SQLite catalog after reviewing dry-run",
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
        names.setdefault(norm(str(row["brand_name"])), str(row["brand_name"]).strip())

    products_without_variants = [
        str(row["product_id"]).strip()
        for row in products
        if not by_product.get(str(row["product_id"]).strip())
    ]
    variant_count = sum(
        len(by_product.get(str(row["product_id"]).strip(), []))
        for row in products
    )
    report = {
        "status": "validated",
        "brands": len(names),
        "fragrances": len(products),
        "variants": variant_count,
        "products_without_variants": len(products_without_variants),
        "products_without_variants_examples": products_without_variants[:25],
        "offers_imported": 0,
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
                brand = session.scalar(select(Brand).where(Brand.normalized_name == key))
                if brand is None:
                    brand = Brand(
                        id=stable_id("brand", key),
                        name=name,
                        slug=slugify(name),
                        normalized_name=key,
                    )
                    session.add(brand)
                brand_rows[key] = brand
            session.flush()

            for product in products:
                pid = str(product["product_id"]).strip()
                brand = brand_rows[norm(str(product["brand_name"]))]
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

                for variant in by_product.get(pid, []):
                    source_id = str(variant["variant_id"]).strip()
                    concentration = variant.get("concentration") or product.get("concentration")
                    size = variant.get("size_ml")
                    key = "|".join((
                        norm(str(product["brand_name"])),
                        norm(name),
                        norm(str(concentration or "")),
                        str(size or ""),
                        str(bool(variant.get("is_tester", False))),
                        str(bool(variant.get("is_refill", False))),
                        str(bool(variant.get("is_gift_set", False))),
                        source_id,
                    ))
                    variant_id = stable_id("variant", source_id)
                    if session.get(ProductVariant, variant_id) is None:
                        session.add(ProductVariant(
                            id=variant_id,
                            fragrance_id=fragrance.id,
                            concentration=concentration,
                            size_ml=int(size) if size not in (None, "") else None,
                            is_tester=variant.get("is_tester"),
                            is_refill=variant.get("is_refill"),
                            is_gift_set=variant.get("is_gift_set"),
                            gtin=variant.get("gtin"),
                            canonical_key=key[:320],
                        ))

        inspector = inspect(engine)
        expected_tables = {
            "brands", "fragrances", "product_variants", "stores",
            "offers", "price_history", "match_audit", "ingestion_runs",
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
        })
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
