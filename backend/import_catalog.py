#!/usr/bin/env python3
"""
ScentHunter catalog importer.

Purpose:
- Import perfume-like products from an Open Beauty Facts CSV/JSONL/JSONL.GZ dump
  into backend/scenthunter_catalog.json.
- Keep manually curated ScentHunter entries.
- Normalize names/brands, deduplicate, generate aliases, and preserve source metadata.
- No network calls happen while the user types in ScentHunter.

Usage examples:
  python import_catalog.py /path/to/openbeautyfacts-products.csv.gz
  python import_catalog.py /path/to/openbeautyfacts-products.jsonl.gz

The importer intentionally accepts a LOCAL dump path. Open Beauty Facts recommends
bulk exports instead of large numbers of API calls.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Any

HERE = Path(__file__).resolve().parent
DEFAULT_CATALOG = HERE / "scenthunter_catalog.json"

PERFUME_HINTS = {
    "perfume", "parfum", "fragrance", "eau de parfum", "eau-de-parfum",
    "eau de toilette", "eau-de-toilette", "edt", "edp", "extrait",
    "cologne", "eau de cologne", "body fragrance",
}
NON_PERFUME_HINTS = {
    "deodorant", "antiperspirant", "shower gel", "body lotion", "soap",
    "shampoo", "conditioner", "toothpaste", "cream", "serum", "makeup",
    "lipstick", "mascara", "nail polish", "after shave", "aftershave",
}

def norm(value: Any) -> str:
    s = str(value or "").lower().strip()
    s = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())

def first_value(row: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        v = row.get(key)
        if v not in (None, "", []):
            if isinstance(v, list):
                return clean_text(v[0] if v else "")
            return clean_text(v)
    return ""

def looks_like_perfume(row: Dict[str, Any]) -> bool:
    hay = " ".join([
        first_value(row, "categories", "categories_tags", "categories_en"),
        first_value(row, "product_name", "product_name_en", "generic_name"),
        first_value(row, "labels", "labels_tags"),
    ]).lower()

    if any(x in hay for x in NON_PERFUME_HINTS):
        # Permit a product explicitly categorized as perfume even if another
        # incidental term appears.
        strong = any(x in hay for x in ("eau de parfum", "eau-de-parfum", "perfume", "parfum", "fragrance"))
        if not strong:
            return False
    return any(x in hay for x in PERFUME_HINTS)

def extract_name(row: Dict[str, Any]) -> str:
    return first_value(
        row, "product_name", "product_name_en", "product_name_fr",
        "product_name_it", "generic_name"
    )

def extract_brand(row: Dict[str, Any]) -> str:
    brand = first_value(row, "brands")
    if "," in brand:
        brand = brand.split(",", 1)[0]
    return clean_text(brand)

def extract_image(row: Dict[str, Any]) -> str:
    return first_value(
        row,
        "image_front_url", "image_url", "image_front_small_url",
        "image_front_thumb_url"
    )

def extract_source_url(row: Dict[str, Any]) -> str:
    code = first_value(row, "code", "_id")
    if not code:
        return ""
    return f"https://world.openbeautyfacts.org/product/{code}"

def aliases_for(name: str, brand: str) -> List[str]:
    values = {norm(name), norm(f"{brand} {name}")}
    for v in list(values):
        if v:
            values.add(v.replace(" ", ""))
    # Remove common concentration/size noise for search aliases.
    stripped = re.sub(
        r"\b(eau de parfum|eau de toilette|edp|edt|parfum|perfume|spray|extrait)\b",
        " ", norm(name)
    )
    stripped = re.sub(r"\b\d+\s*ml\b", " ", stripped)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    if stripped:
        values.add(stripped)
        values.add(stripped.replace(" ", ""))
    return sorted(v for v in values if v)

def canonical_key(item: Dict[str, Any]) -> str:
    brand = norm(item.get("brand"))
    name = norm(item.get("name"))
    name = re.sub(
        r"\b(eau de parfum|eau de toilette|edp|edt|parfum|perfume|spray|extrait)\b",
        " ", name
    )
    name = re.sub(r"\b\d+\s*ml\b", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return f"{brand}|{name}"

def open_text(path: Path):
    if path.suffix.lower() == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace", newline="")
    return path.open("r", encoding="utf-8", errors="replace", newline="")

def iter_rows(path: Path) -> Iterator[Dict[str, Any]]:
    name = path.name.lower()
    if name.endswith(".jsonl") or name.endswith(".jsonl.gz"):
        with open_text(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    yield obj
        return

    # Open Facts CSV dumps are typically tab-separated.
    with open_text(path) as f:
        sample = f.read(8192)
        f.seek(0)
        delimiter = "\t" if sample.count("\t") >= sample.count(",") else ","
        reader = csv.DictReader(f, delimiter=delimiter)
        for row in reader:
            yield dict(row)

def load_catalog(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []

def main() -> int:
    ap = argparse.ArgumentParser(description="Import Open Beauty Facts perfumes into ScentHunter catalog")
    ap.add_argument("dump", type=Path, help="Local Open Beauty Facts CSV/JSONL(.gz) dump")
    ap.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    ap.add_argument("--max-products", type=int, default=0, help="0 = no limit")
    args = ap.parse_args()

    if not args.dump.exists():
        raise SystemExit(f"Dump not found: {args.dump}")

    existing = load_catalog(args.catalog)
    merged: Dict[str, Dict[str, Any]] = {}

    # Existing/manual entries win over imported values when they contain data.
    for item in existing:
        if not isinstance(item, dict) or not clean_text(item.get("name")):
            continue
        item = dict(item)
        item.setdefault("aliases", aliases_for(item.get("name", ""), item.get("brand", "")))
        item.setdefault("source", item.get("source") or "scenthunter")
        merged[canonical_key(item)] = item

    scanned = imported = skipped = 0
    for row in iter_rows(args.dump):
        scanned += 1
        if not looks_like_perfume(row):
            skipped += 1
            continue

        name = extract_name(row)
        brand = extract_brand(row)
        if not name:
            skipped += 1
            continue

        item = {
            "catalog_id": first_value(row, "code", "_id") or None,
            "name": name,
            "brand": brand,
            "image": extract_image(row),
            "aliases": aliases_for(name, brand),
            "source": "open-beauty-facts",
            "source_url": extract_source_url(row),
            "data_license": "ODbL",
            "image_license": "CC BY-SA",
        }

        key = canonical_key(item)
        old = merged.get(key)
        if old:
            # Preserve curated ScentHunter values; fill only blanks and merge aliases.
            for field in ("catalog_id", "brand", "image", "source_url"):
                if not old.get(field) and item.get(field):
                    old[field] = item[field]
            old["aliases"] = sorted(set(old.get("aliases", [])) | set(item["aliases"]))
            if old.get("source") in (None, "", "scenthunter") and item.get("image"):
                old.setdefault("image_source", "open-beauty-facts")
                old.setdefault("image_license", "CC BY-SA")
        else:
            merged[key] = item
            imported += 1

        if args.max_products and imported >= args.max_products:
            break

    output = sorted(
        merged.values(),
        key=lambda x: (norm(x.get("brand")), norm(x.get("name")))
    )
    args.catalog.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"Scanned: {scanned}")
    print(f"New perfume records: {imported}")
    print(f"Skipped/non-perfume: {skipped}")
    print(f"Catalog total: {len(output)}")
    print(f"Saved: {args.catalog}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
