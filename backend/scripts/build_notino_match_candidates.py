"""Generate review-only NOTINO-to-canonical product match candidates.

No candidate is automatically accepted. Brand must match after conservative
normalization; name similarity, concentration and size are used to rank review
candidates. The tool writes a CSV for human verification and never edits the
canonical catalog or database.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from pathlib import Path


GTIN_LENGTHS = {8, 12, 13, 14}
CONCENTRATIONS = {
    "eau de parfum intense": "EDP_INTENSE",
    "eau de parfum": "EDP",
    "eau de toilette": "EDT",
    "eau de cologne": "EDC",
    "parfum": "PARFUM",
    "extrait de parfum": "EXTRAIT",
    "elixir": "ELIXIR",
    "edp": "EDP",
    "edt": "EDT",
    "edc": "EDC",
}


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.casefold().replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def parse_size(value: str) -> float | None:
    match = re.search(r"(?<![0-9])(\d+(?:[.,]\d+)?)\s*(?:ml|millilit(?:er|re)s?)\b", value or "", re.I)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


def extract_concentration(value: str) -> str | None:
    normalized = normalize(value)
    for phrase in sorted(CONCENTRATIONS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(normalize(phrase))}\b", normalized):
            return CONCENTRATIONS[phrase]
    return None


def strip_product_noise(value: str) -> str:
    text = normalize(value)
    text = re.sub(r"\b\d+(?:\.\d+)?\s*(?:ml|milliliters?|millilitres?)\b", " ", text)
    for phrase in sorted(CONCENTRATIONS, key=len, reverse=True):
        text = re.sub(rf"\b{re.escape(normalize(phrase))}\b", " ", text)
    text = re.sub(r"\b(?:spray|vaporisateur|natural spray|tester|refill|recharge|gift set|coffret|for men|for women|pour homme|pour femme)\b", " ", text)
    return " ".join(text.split())


def _entry_values(entry: ET.Element) -> dict[str, str]:
    return {
        child.tag.rsplit("}", 1)[-1]: (child.text or "").strip()
        for child in entry
    }


def iter_perfume_rows(feed_path: str | Path):
    for _, entry in ET.iterparse(str(feed_path), events=("end",)):
        if entry.tag.rsplit("}", 1)[-1] == "entry":
            row = _entry_values(entry)
            category_name = row.get("google_product_category_name", "").casefold()
            if row.get("google_product_category") == "479" or "parfums et eaux de cologne" in category_name:
                yield row
            entry.clear()


def _brand_key(value: str) -> str:
    return normalize(value)


def build_catalog_index(catalog: dict) -> list[dict]:
    products = {p.get("product_id"): p for p in catalog.get("products", [])}
    variants_by_product: dict[str, list[dict]] = {}
    for variant in catalog.get("variants", []):
        variants_by_product.setdefault(variant.get("product_id"), []).append(variant)

    indexed = []
    for product_id, product in products.items():
        brand = product.get("brand_name", "")
        brand_key = _brand_key(brand)
        names = [product.get("canonical_name", ""), product.get("family_name", "")]
        names.extend(product.get("aliases") or [])
        normalized_names = sorted({strip_product_noise(n) for n in names if n and strip_product_noise(n)})
        for variant in variants_by_product.get(product_id, []):
            variant_names = list(variant.get("aliases") or [])
            variant_names = [strip_product_noise(n) for n in variant_names if n]
            indexed.append({
                "product_id": product_id,
                "variant_id": variant.get("variant_id", ""),
                "brand": brand,
                "brand_key": brand_key,
                "names": sorted(set(normalized_names + [n for n in variant_names if n])),
                "size_ml": variant.get("size_ml"),
                "concentration": extract_concentration(product.get("concentration", "")),
                "gtins": variant.get("gtins") or [],
            })
    return indexed


def score_row(row: dict[str, str], catalog_index: list[dict]) -> list[dict]:
    feed_brand = row.get("brand", "")
    brand_key = _brand_key(feed_brand)
    raw_title = row.get("title", "")
    feed_name = strip_product_noise(raw_title)
    feed_size = parse_size(row.get("size", "")) or parse_size(raw_title)
    feed_concentration = extract_concentration(raw_title) or extract_concentration(row.get("product_type", ""))
    feed_gtin = row.get("gtin", "")

    # Exact GTIN evidence is reported separately; this tool is designed for
    # candidate generation where canonical GTINs are absent or incomplete.
    results = []
    for item in catalog_index:
        if not brand_key or item["brand_key"] != brand_key:
            continue
        best_name = max(
            (SequenceMatcher(None, feed_name, candidate).ratio() for candidate in item["names"]),
            default=0.0,
        )
        if not feed_name or best_name < 0.45:
            continue

        size_match = feed_size is not None and item["size_ml"] is not None and abs(feed_size - float(item["size_ml"])) < 0.01
        size_conflict = feed_size is not None and item["size_ml"] is not None and not size_match
        canonical_concentration = item["concentration"]
        concentration_match = bool(feed_concentration and canonical_concentration and feed_concentration == canonical_concentration)
        concentration_conflict = bool(feed_concentration and canonical_concentration and feed_concentration != canonical_concentration)

        score = 0.72 * best_name
        if size_match:
            score += 0.20
        elif size_conflict:
            score -= 0.18
        if concentration_match:
            score += 0.08
        elif concentration_conflict:
            score -= 0.15

        # Hard safety gate: a known size mismatch or concentration mismatch
        # cannot be labeled high confidence.
        if size_conflict or concentration_conflict:
            confidence = "low"
        elif score >= 0.92 and size_match and concentration_match:
            confidence = "review_high"
        elif score >= 0.78 and size_match:
            confidence = "review_medium"
        else:
            confidence = "review_low"

        results.append({
            "candidate_score": round(max(0.0, min(score, 1.0)), 4),
            "confidence_band": confidence,
            "feed_external_id": row.get("id", ""),
            "feed_gtin": feed_gtin,
            "feed_brand": feed_brand,
            "feed_title": raw_title,
            "feed_size_ml": feed_size,
            "feed_concentration": feed_concentration or "",
            "canonical_product_id": item["product_id"],
            "canonical_variant_id": item["variant_id"],
            "canonical_brand": item["brand"],
            "canonical_names": " | ".join(item["names"]),
            "canonical_size_ml": item["size_ml"],
            "canonical_concentration": canonical_concentration or "",
            "name_similarity": round(best_name, 4),
            "size_match": size_match,
            "concentration_match": concentration_match,
            "review_status": "needs_human_review",
        })

    results.sort(key=lambda candidate: candidate["candidate_score"], reverse=True)
    return results[:5]


def generate_candidates(feed_path: str | Path, catalog_path: str | Path) -> list[dict]:
    catalog = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    index = build_catalog_index(catalog)
    output = []
    for row in iter_perfume_rows(feed_path):
        candidates = score_row(row, index)
        if candidates:
            output.extend(candidates)
        else:
            output.append({
                "candidate_score": 0.0,
                "confidence_band": "no_candidate",
                "feed_external_id": row.get("id", ""),
                "feed_gtin": row.get("gtin", ""),
                "feed_brand": row.get("brand", ""),
                "feed_title": row.get("title", ""),
                "feed_size_ml": parse_size(row.get("size", "")) or parse_size(row.get("title", "")),
                "feed_concentration": extract_concentration(row.get("title", "")) or "",
                "canonical_product_id": "",
                "canonical_variant_id": "",
                "canonical_brand": "",
                "canonical_names": "",
                "canonical_size_ml": "",
                "canonical_concentration": "",
                "name_similarity": 0.0,
                "size_match": False,
                "concentration_match": False,
                "review_status": "no_candidate",
            })
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("feed", type=Path)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("--output", type=Path, default=Path("notino-match-candidates.csv"))
    args = parser.parse_args()

    rows = generate_candidates(args.feed, args.catalog)
    fields = list(rows[0]) if rows else [
        "candidate_score", "confidence_band", "feed_external_id", "feed_gtin",
        "feed_brand", "feed_title", "feed_size_ml", "feed_concentration",
        "canonical_product_id", "canonical_variant_id", "canonical_brand",
        "canonical_names", "canonical_size_ml", "canonical_concentration",
        "name_similarity", "size_match", "concentration_match", "review_status",
    ]
    with args.output.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    reviewed_rows = {row["feed_external_id"] for row in rows if row["review_status"] == "needs_human_review"}
    print(json.dumps({
        "candidate_rows": len(rows),
        "feed_products_with_candidates": len(reviewed_rows),
        "feed_products_without_candidates": sum(row["review_status"] == "no_candidate" for row in rows),
        "output": str(args.output),
        "automatic_matches": 0,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
