"""Explicit canonical seed import. Never imports offers or alters source/legacy DB."""
from __future__ import annotations
import argparse, json, re, sys, unicodedata, uuid
from pathlib import Path
from sqlalchemy import select
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

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default=str(ROOT / "backend" / "product_catalog.json"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    with Path(args.catalog).open(encoding="utf-8") as handle:
        raw = json.load(handle)
    products, variants = raw.get("products"), raw.get("variants")
    if not isinstance(products, list) or not isinstance(variants, list):
        raise SystemExit("STOP: catalog must contain products[] and variants[]")
    by_product: dict[str, list[dict]] = {}
    for row in variants:
        if isinstance(row, dict):
            pid = str(row.get("product_id") or "").strip()
            if pid: by_product.setdefault(pid, []).append(row)
    blocked = []
    for row in products:
        if not isinstance(row, dict): blocked.append("non-object product row"); continue
        pid = str(row.get("product_id") or "").strip()
        if not pid or not str(row.get("brand_name") or "").strip() or not str(row.get("canonical_name") or "").strip():
            blocked.append(f"{pid or '(no id)'}: missing canonical identity fields")
        elif not by_product.get(pid): blocked.append(f"{pid}: no explicit variant records")
    if blocked:
        print(json.dumps({"status":"blocked","blocked_count":len(blocked),"examples":blocked[:25],"source_modified":False}, ensure_ascii=False, indent=2))
        return 2
    names, seen = {}, set()
    for row in products:
        pid = str(row["product_id"]).strip()
        if pid in seen: raise SystemExit(f"STOP: duplicate product_id {pid}")
        seen.add(pid)
        names.setdefault(norm(str(row["brand_name"])), str(row["brand_name"]).strip())
    variant_count = sum(len(by_product[str(row["product_id"])]) for row in products)
    if args.dry_run:
        print(json.dumps({"status":"validated","brands":len(names),"fragrances":len(products),"variants":variant_count,"database_written":False}, indent=2))
        return 0
    engine = make_engine()
    try:
        with Session(engine) as session, session.begin():
            brand_rows = {}
            for key, name in names.items():
                brand = session.scalar(select(Brand).where(Brand.normalized_name == key))
                if brand is None:
                    brand = Brand(id=stable_id("brand", key), name=name, slug=slugify(name), normalized_name=key)
                    session.add(brand)
                brand_rows[key] = brand
            session.flush()
            for product in products:
                pid = str(product["product_id"]).strip()
                brand = brand_rows[norm(str(product["brand_name"]))]
                name = str(product["canonical_name"]).strip()
                fragrance = session.scalar(select(Fragrance).where(Fragrance.brand_id == brand.id, Fragrance.slug == slugify(name)))
                if fragrance is None:
                    fragrance = Fragrance(id=stable_id("fragrance", pid), brand_id=brand.id, name=name, slug=slugify(name), gender=product.get("gender"), family=product.get("family_name"), description=product.get("description"), image_url=product.get("canonical_image"))
                    session.add(fragrance)
                session.flush()
                for variant in by_product[pid]:
                    source_id = str(variant.get("variant_id") or "").strip()
                    if not source_id: raise ValueError(f"{pid}: variant missing variant_id")
                    concentration = variant.get("concentration") or product.get("concentration")
                    size = variant.get("size_ml")
                    key = "|".join((norm(str(product["brand_name"])), norm(name), norm(str(concentration or "")), str(size or ""), str(bool(variant.get("is_tester", False))), str(bool(variant.get("is_refill", False))), str(bool(variant.get("is_gift_set", False))), source_id))
                    variant_id = stable_id("variant", source_id)
                    if session.get(ProductVariant, variant_id) is None:
                        session.add(ProductVariant(id=variant_id, fragrance_id=fragrance.id, concentration=concentration, size_ml=int(size) if size not in (None, "") else None, is_tester=bool(variant.get("is_tester", False)), is_refill=bool(variant.get("is_refill", False)), is_gift_set=bool(variant.get("is_gift_set", False)), gtin=variant.get("gtin"), canonical_key=key[:320]))
        print(json.dumps({"status":"seeded","brands":len(names),"fragrances":len(products),"variants":variant_count,"source_file_modified":False}, indent=2))
        return 0
    finally:
        engine.dispose()

if __name__ == "__main__":
    raise SystemExit(main())
