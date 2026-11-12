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

try:
    from backend.gtin import is_valid_gtin
except ModuleNotFoundError:  # CLI invoked from inside backend/
    from gtin import is_valid_gtin


GTIN_LENGTHS = {8, 12, 13, 14}
CONCENTRATIONS = {
    "eau de parfum intense": "EDP_INTENSE",
    "eau de toilette intense": "EDT_INTENSE",
    "pure parfum": "PARFUM",
    "eau de parfum": "EDP",
    "eau de toilette": "EDT",
    "eau de cologne": "EDC",
    "parfum": "PARFUM",
    "extrait de parfum": "EXTRAIT",
    "elixir": "ELIXIR",
    "edp": "EDP",
    "edt": "EDT",
    "edc": "EDC",
    "extrait": "EXTRAIT",
}


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.casefold().replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def parse_size(value: str) -> float | None:
    text = value or ""
    ml_match = re.search(
        r"(?<![0-9])(\d+(?:[.,]\d+)?)\s*(?:ml|millilit(?:er|re)s?)\b",
        text, re.I,
    )
    if ml_match:
        try:
            return float(ml_match.group(1).replace(",", "."))
        except ValueError:
            return None

    # Perfume packaging commonly uses US fluid ounces; do not interpret bare
    # "oz" as volume because it can also denote weight.
    fl_oz_match = re.search(
        r"(?<![0-9])(\d+(?:[.,]\d+)?)\s*(?:fl\.?\s*oz\.?|fluid\s+ounces?)\b",
        text, re.I,
    )
    if not fl_oz_match:
        return None
    try:
        return round(float(fl_oz_match.group(1).replace(",", ".")) * 29.5735295625, 2)
    except ValueError:
        return None


def extract_concentration(value: str) -> str | None:
    normalized = normalize(value)
    for phrase in sorted(CONCENTRATIONS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(normalize(phrase))}\b", normalized):
            return CONCENTRATIONS[phrase]
    return None


def extract_gender(value: str) -> str | None:
    """Extract explicit audience markers in common retailer/catalog languages."""
    text = normalize(value)
    has_men = bool(re.search(
        r"\b(?:for men|pour homme|homme|hommes|men|mens|man|male|masculine|"
        r"uomo|uomini|for him|pour lui)\b",
        text,
    ))
    has_women = bool(re.search(
        r"\b(?:for women|pour femme|femme|femmes|women|womens|woman|female|"
        r"feminine|donna|donne|for her|pour elle)\b",
        text,
    ))
    if has_men and has_women:
        return "conflict"
    if has_men:
        return "men"
    if has_women:
        return "women"
    if re.search(r"\bunisex\b", text):
        return "unisex"
    return None


def strip_product_noise(value: str) -> str:
    text = normalize(value)
    text = re.sub(r"\b\d+(?:\.\d+)?\s*(?:ml|milliliters?|millilitres?)\b", " ", text)
    for phrase in sorted(CONCENTRATIONS, key=len, reverse=True):
        text = re.sub(rf"\b{re.escape(normalize(phrase))}\b", " ", text)
    text = re.sub(r"\b(?:spray|vaporisateur|natural spray|tester|refill|recharge|gift set|coffret|for men|for women|for him|for her|pour homme|pour femme|pour lui|pour elle|homme|femme|men|women|man|woman)\b", " ", text)
    return " ".join(text.split())


def _entry_values(entry: ET.Element) -> dict[str, str]:
    return {
        child.tag.rsplit("}", 1)[-1]: (child.text or "").strip()
        for child in entry
    }


CORE_PRODUCT_TYPES = {
    "toaletní vody", "parfémované vody", "kolínské vody",
    "parfémy", "parfémované oleje", "eau fraîche",
}


def iter_perfume_rows(feed_path: str | Path):
    """Yield core fragrance listings, excluding gift sets and accessories."""
    for _, entry in ET.iterparse(str(feed_path), events=("end",)):
        if entry.tag.rsplit("}", 1)[-1] == "entry":
            row = _entry_values(entry)
            terminal_type = row.get("product_type", "").split(">")[-1].strip().casefold()
            if row.get("google_product_category") == "479" and terminal_type in CORE_PRODUCT_TYPES:
                yield row
            entry.clear()


BRAND_ALIASES = {
    "rabanne": "paco rabanne",
    "ferragamo": "salvatore ferragamo",
}


def _brand_key(value: str) -> str:
    key = normalize(value)
    return BRAND_ALIASES.get(key, key)


def _catalog_gender(product: dict, names: list[str]) -> str | None:
    # Canonical name is primary evidence, followed by explicit catalog metadata.
    # Aliases are secondary: they must not override a clear primary declaration.
    primary = extract_gender(" ".join([
        product.get("canonical_name", ""),
        product.get("family_name", ""),
    ]))
    if primary:
        return primary

    metadata_gender = extract_gender(str(product.get("gender") or ""))
    if metadata_gender:
        return metadata_gender

    alias_genders = {
        gender for gender in (extract_gender(name) for name in names)
        if gender in {"men", "women", "unisex", "conflict"}
    }
    if "conflict" in alias_genders or len(alias_genders) > 1:
        return "conflict"
    return next(iter(alias_genders), None)


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
        product_variants = variants_by_product.get(product_id, [])
        # Keep products without variants visible as product-only candidates.
        # They have no size/GTIN evidence and cannot identify a purchasable variant.
        if not product_variants:
            product_variants = [None]
        for variant in product_variants:
            variant_names = list((variant or {}).get("aliases") or [])
            variant_names = [strip_product_noise(n) for n in variant_names if n]
            indexed.append({
                "product_id": product_id,
                "variant_id": (variant or {}).get("variant_id", ""),
                "candidate_scope": "variant" if variant else "product_only",
                "brand": brand,
                "brand_key": brand_key,
                "names": sorted(set(normalized_names + [n for n in variant_names if n])),
                "size_ml": (variant or {}).get("size_ml"),
                "concentration": extract_concentration(
                    (variant or {}).get("concentration") or product.get("concentration", "")
                ),
                "gender": _catalog_gender(product, names),
                "gtins": (variant or {}).get("gtins") or [],
            })
    return indexed


def score_row(row: dict[str, str], catalog_index: list[dict]) -> list[dict]:
    feed_brand = row.get("brand", "")
    brand_key = _brand_key(feed_brand)
    raw_title = row.get("title", "")
    feed_name = strip_product_noise(raw_title)
    # Retailer titles often repeat the brand while canonical product names do
    # not. Remove only an exact leading brand prefix before comparing names;
    # this keeps "Rayhaan Kiss" distinct from "Rayhaan Aquatica" without
    # penalizing legitimate "Rabanne 1 Million" -> "1 Million" matches.
    title_brand_tokens = normalize(feed_brand).split()
    feed_name_tokens = feed_name.split()
    if title_brand_tokens and feed_name_tokens[:len(title_brand_tokens)] == title_brand_tokens:
        feed_name = " ".join(feed_name_tokens[len(title_brand_tokens):])
    feed_size = parse_size(row.get("size", "")) or parse_size(raw_title) or parse_size(row.get("description", ""))
    feed_concentration = extract_concentration(raw_title) or extract_concentration(row.get("product_type", ""))
    feed_gender = extract_gender(raw_title)
    feed_gtin = row.get("gtin", "")

    # Exact GTIN evidence is reported separately; this tool is designed for
    # candidate generation where canonical GTINs are absent or incomplete.
    results = []
    for item in catalog_index:
        gtin_match = bool(
            is_valid_gtin(str(feed_gtin))
            and str(feed_gtin) in {
                str(value) for value in item.get("gtins", [])
                if is_valid_gtin(str(value))
            }
        )
        if not gtin_match and (not brand_key or item["brand_key"] != brand_key):
            continue
        best_name = max(
            (SequenceMatcher(None, feed_name, candidate).ratio() for candidate in item["names"]),
            default=0.0,
        )
        if not feed_name or (not gtin_match and best_name < 0.70):
            continue

        size_match = feed_size is not None and item["size_ml"] is not None and abs(feed_size - float(item["size_ml"])) < 0.01
        size_conflict = feed_size is not None and item["size_ml"] is not None and not size_match
        canonical_concentration = item["concentration"]
        concentration_match = bool(feed_concentration and canonical_concentration and feed_concentration == canonical_concentration)
        concentration_conflict = bool(feed_concentration and canonical_concentration and feed_concentration != canonical_concentration)
        gender_conflict = bool(
            feed_gender and item.get("gender")
            and (item["gender"] == "conflict" or feed_gender != item["gender"])
        )
        # Missing canonical gender is unknown evidence, not agreement. Keep
        # name/size/concentration candidates visible, but do not rank a
        # name-based candidate as high confidence without gender validation.
        gender_unverified = bool(feed_gender and not item.get("gender"))

        score = 1.0 if gtin_match else 0.72 * best_name
        if not gtin_match and size_match:
            score += 0.20
        elif not gtin_match and size_conflict:
            score -= 0.18
        if not gtin_match and concentration_match:
            score += 0.08
        elif not gtin_match and concentration_conflict:
            score -= 0.15
        if gender_conflict:
            score -= 0.35

        # Hard safety gate: a known size mismatch or concentration mismatch
        # cannot be labeled high confidence.
        if size_conflict or concentration_conflict or gender_conflict:
            confidence = "low"
        elif gtin_match:
            confidence = "review_high"
        elif gender_unverified:
            confidence = "review_medium" if score >= 0.78 and size_match else "review_low"
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
            "feed_gender": feed_gender or "",
            "canonical_gender": item.get("gender") or "",
            "gender_conflict": gender_conflict,
            "gender_unverified": gender_unverified,
            "canonical_product_id": item["product_id"],
            "canonical_variant_id": item["variant_id"],
            "candidate_scope": item["candidate_scope"],
            "canonical_brand": item["brand"],
            "canonical_names": " | ".join(item["names"]),
            "canonical_size_ml": item["size_ml"],
            "canonical_concentration": canonical_concentration or "",
            "name_similarity": round(best_name, 4),
            "gtin_match": gtin_match,
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
                "feed_gender": extract_gender(row.get("title", "")) or "",
                "canonical_gender": "",
                "gender_conflict": False,
                "gender_unverified": bool(extract_gender(row.get("title", ""))),
                "canonical_product_id": "",
                "canonical_variant_id": "",
                "candidate_scope": "",
                "canonical_brand": "",
                "canonical_names": "",
                "canonical_size_ml": "",
                "canonical_concentration": "",
                "name_similarity": 0.0,
                "gtin_match": False,
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
        "feed_gender", "canonical_gender", "gender_conflict", "gender_unverified", "canonical_product_id", "canonical_variant_id", "candidate_scope", "canonical_brand",
        "canonical_names", "canonical_size_ml", "canonical_concentration",
        "name_similarity", "gtin_match", "size_match", "concentration_match", "review_status",
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
