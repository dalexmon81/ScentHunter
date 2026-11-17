"""Import canonical identities and explicitly declared variants only.

Products without known variants are retained as fragrance identities. No
variant is inferred, no retailer offer is imported, and the source/legacy
catalog databases are never modified. Dry-run is the default.
"""
from __future__ import annotations

import argparse
import json
from decimal import Decimal, InvalidOperation
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
from app.models import Brand, Fragrance, ProductVariant, ProductIdentifier, Store, LegacyProductIdMap, LegacyVariantIdMap

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
    # Phase 2 publication freshness window; operators may adjust explicitly.
    "offer_ttl_minutes": 1440,
}

def ensure_bplatz_store(session: Session) -> Store:
    """Create the opt-in Bplatz store or fill missing configuration safely.

    An operator's existing freshness TTL is preserved. The default is applied
    only when the store is first created or its TTL has never been configured.
    """
    store = session.scalar(select(Store).where(Store.slug == BPLATZ_STORE["slug"]))
    if store is None:
        store = Store(**BPLATZ_STORE)
        session.add(store)
        session.flush()
        return store

    for field, value in BPLATZ_STORE.items():
        if field == "offer_ttl_minutes" and store.offer_ttl_minutes is not None:
            continue
        setattr(store, field, value)
    session.flush()
    return store



def norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch)).lower()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def normalize_brand(value: str) -> str:
    """Normalize brand names consistently without depending on optional app modules."""
    normalized = norm(str(value).replace("&", " and "))
    return {"dior": "christian dior", "christian dior": "christian dior",
            "nishane": "nishane istanbul", "nishane istanbul": "nishane istanbul"}.get(
                normalized, normalized
            )


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


def _parse_size_ml(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"invalid size_ml {value!r}") from exc
    normalized = amount.normalize()
    if (
        not amount.is_finite()
        or amount <= 0
        or amount > Decimal("999999.9999")
        or normalized.as_tuple().exponent < -4
    ):
        raise ValueError(f"invalid size_ml {value!r}")
    return amount


def _flag_key(value) -> str:
    """Keep unknown packaging flags distinct from explicit false values."""
    if value is None:
        return "unknown"
    if isinstance(value, bool):
        return "true" if value else "false"
    raise ValueError(f"packaging flag must be true, false, or null; got {value!r}")


def _collect_variant_identifiers(product: dict, variant: dict) -> list[dict]:
    """Return source identifiers with explicit namespaces; never guess a namespace."""
    result: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    brand_namespace = f"brand:{slugify(str(product.get('brand_name') or ''))}"

    def add(kind: str, value, namespace: str, *, source_url: str | None = None):
        if value in (None, ""):
            return
        if not isinstance(value, str):
            raise ValueError(f"{kind} identifier must be a string")
        original = value.strip()
        if not original:
            return
        if kind == "gtin":
            normalized = re.sub(r"[\s-]", "", original)
            if not normalized.isdigit() or len(normalized) not in {8, 12, 13, 14}:
                raise ValueError(f"invalid GTIN {original!r}")
        else:
            normalized = re.sub(r"\s+", "", original).upper()
        key = (kind, namespace, normalized)
        if key in seen:
            return
        seen.add(key)
        result.append({
            "identifier_type": kind,
            "namespace": namespace,
            "value": original,
            "normalized_value": normalized,
            "source_url": source_url,
        })

    gtins = variant.get("gtins", [])
    mpns = variant.get("mpns", [])
    mappings = variant.get("store_mappings", [])
    if not isinstance(gtins, list) or not isinstance(mpns, list) or not isinstance(mappings, list):
        raise ValueError("gtins, mpns, and store_mappings must be arrays")
    if variant.get("gtin") not in (None, ""):
        gtins = [*gtins, variant["gtin"]]
    if variant.get("mpn") not in (None, ""):
        mpns = [*mpns, variant["mpn"]]
    for value in gtins:
        add("gtin", value, "global")
    for value in mpns:
        add("mpn", value, brand_namespace)
    for mapping in mappings:
        if not isinstance(mapping, dict):
            raise ValueError("store_mappings entries must be objects")
        store_name = str(mapping.get("store") or "").strip()
        sku = mapping.get("sku")
        if not store_name or not isinstance(sku, str) or not sku.strip():
            raise ValueError("store mapping requires a store name and non-empty string SKU")
        store_slug = slugify(store_name)
        source_url = mapping.get("url")
        if not store_slug:
            raise ValueError("store mapping has an invalid store name")
        if source_url is not None and not isinstance(source_url, str):
            raise ValueError("store mapping URL must be a string")
        add("sku", sku, f"store:{store_slug}", source_url=source_url)
    return result


def validate_catalog(raw: dict) -> tuple[list[dict], dict[str, list[dict]], list[str]]:
    products = raw.get("products")
    variants = raw.get("variants")
    if not isinstance(products, list) or not isinstance(variants, list):
        raise SystemExit("STOP: catalog must contain products[] and variants[]")

    blocked: list[str] = []
    product_ids: set[str] = set()
    by_product: dict[str, list[dict]] = {}
    variant_ids: set[str] = set()
    product_by_id: dict[str, dict] = {}
    identifier_owners: dict[tuple[str, str, str], str] = {}

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
        product_by_id[pid] = row
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
        try:
            _parse_size_ml(size)
            for flag in ("is_tester", "is_refill", "is_gift_set", "is_mini"):
                _flag_key(row.get(flag))
            identifiers = _collect_variant_identifiers(product_by_id[pid], row)
        except ValueError as exc:
            blocked.append(f"{source_id}: {exc}")
            continue
        for identifier in identifiers:
            identifier_key = (
                identifier["identifier_type"],
                identifier["namespace"],
                identifier["normalized_value"],
            )
            owner = identifier_owners.get(identifier_key)
            if owner is not None and owner != source_id:
                blocked.append(
                    f"{source_id}: identifier {identifier_key!r} is already assigned to {owner}"
                )
            else:
                identifier_owners[identifier_key] = source_id
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
                    numeric_size = _parse_size_ml(size)
                    key = "|".join((
                        normalize_brand(str(product["brand_name"])),
                        norm(name),
                        norm(str(concentration or "")),
                        format(numeric_size.normalize(), "f") if numeric_size is not None else "",
                        _flag_key(variant.get("is_tester")),
                        _flag_key(variant.get("is_refill")),
                        _flag_key(variant.get("is_gift_set")),
                        _flag_key(variant.get("is_mini")),
                        source_id,
                    ))
                    variant_id = stable_id("variant", source_id)
                    variant_row = session.get(ProductVariant, variant_id)
                    if variant_row is None:
                        variant_row = ProductVariant(
                            id=variant_id,
                            fragrance_id=fragrance.id,
                            concentration=concentration,
                            size_ml=numeric_size,
                            is_tester=variant.get("is_tester"),
                            is_refill=variant.get("is_refill"),
                            is_gift_set=variant.get("is_gift_set"),
                            gtin=(
                            [item["value"] for item in _collect_variant_identifiers(product, variant)
                             if item["identifier_type"] == "gtin"][0]
                            if len([item for item in _collect_variant_identifiers(product, variant)
                                    if item["identifier_type"] == "gtin"]) == 1
                            else None
                        ),
                            canonical_key=str(variant.get("canonical_key") or key[:320]),
                        )
                        session.add(variant_row)
                        session.flush()
                    elif variant_row.fragrance_id != fragrance.id:
                        raise RuntimeError(f"Legacy variant ID {source_id} resolves to a variant of another fragrance.")

                    for identifier in _collect_variant_identifiers(product, variant):
                        store_id = None
                        if identifier["identifier_type"] == "sku":
                            store_slug = identifier["namespace"].removeprefix("store:")
                            store_row = session.scalar(select(Store).where(Store.slug == store_slug))
                            store_id = store_row.id if store_row is not None else None
                        existing_identifier = session.scalar(select(ProductIdentifier).where(
                            ProductIdentifier.identifier_type == identifier["identifier_type"],
                            ProductIdentifier.namespace == identifier["namespace"],
                            ProductIdentifier.normalized_value == identifier["normalized_value"],
                        ))
                        if existing_identifier is None:
                            session.add(ProductIdentifier(
                                id=stable_id(
                                    "product_identifier",
                                    "|".join((
                                        identifier["identifier_type"],
                                        identifier["namespace"],
                                        identifier["normalized_value"],
                                    )),
                                ),
                                product_variant_id=variant_row.id,
                                identifier_type=identifier["identifier_type"],
                                namespace=identifier["namespace"],
                                value=identifier["value"],
                                normalized_value=identifier["normalized_value"],
                                store_id=store_id,
                                source_url=identifier["source_url"],
                            ))
                        elif existing_identifier.product_variant_id != variant_row.id:
                            raise RuntimeError(
                                f"Identifier {identifier['identifier_type']}:{identifier['namespace']}:{identifier['normalized_value']} "
                                "is already assigned to another variant."
                            )
                        elif existing_identifier.store_id is not None and store_id is not None and existing_identifier.store_id != store_id:
                            raise RuntimeError(
                                f"Identifier store conflict for {identifier['namespace']}:{identifier['normalized_value']}."
                            )
                        elif (
                            existing_identifier.source_url
                            and identifier["source_url"]
                            and existing_identifier.source_url != identifier["source_url"]
                        ):
                            raise RuntimeError(
                                f"Identifier source URL conflict for {identifier['namespace']}:{identifier['normalized_value']}."
                            )
                        elif existing_identifier.source_url is None and identifier["source_url"]:
                            existing_identifier.source_url = identifier["source_url"]
                        if existing_identifier is not None and existing_identifier.store_id is None and store_id is not None:
                            existing_identifier.store_id = store_id

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
                ensure_bplatz_store(session)

        inspector = inspect(engine)
        expected_tables = {
            "brands", "fragrances", "product_variants", "stores",
            "offers", "price_history", "match_audit", "ingestion_runs",
            "ingestion_raw", "legacy_product_id_map", "legacy_variant_id_map", "product_identifiers",
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
