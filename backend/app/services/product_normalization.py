"""Deterministic product identity normalization for ScentHunter Phase 3.

This module is deliberately side-effect free: it never edits catalog rows.
Ambiguous identity data is reported as a review conflict, never auto-merged.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

_SPACE = re.compile(r"\\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_SIZE = re.compile(r"(?<![a-z0-9])(\\d+(?:[.,]\\d+)?)\\s*(ml|milliliter|milliliters|cl|l|oz)(?![a-z])", re.I)
_GTIN = re.compile(r"\\D+")

# Explicit, reviewed aliases only. Do not use fuzzy brand matching.
_BRAND_ALIASES = {
    "dior": "christian dior",
    "christian dior": "christian dior",
    "nishane": "nishane istanbul",
    "nishane istanbul": "nishane istanbul",
}

_CONCENTRATIONS = (
    (("extrait de parfum", "extrait", "parfum extract"), "extrait"),
    (("eau de parfum", "edp"), "edp"),
    (("eau de toilette", "edt"), "edt"),
    (("eau de cologne", "edc", "cologne"), "cologne"),
    (("parfum", "pure perfume"), "parfum"),
)
_PACKAGING = {
    "tester": ("tester", ("tester", "testeur")),
    "refill": ("refill", ("refill", "recharge", "nachfullung", "nachfullpackung")),
    "gift_set": ("gift_set", ("gift set", "coffret", "set regalo", "geschenkset")),
    "mini": ("mini", ("mini", "miniature", "travel size", "sample")),
}

def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = value.casefold().replace("&", " and ")
    return _SPACE.sub(" ", _NON_ALNUM.sub(" ", value)).strip()

def normalize_brand(value: str | None) -> str:
    normalized = normalize_text(value)
    return _BRAND_ALIASES.get(normalized, normalized)

def _remove_phrase(text: str, phrase: str) -> str:
    return re.sub(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", " ", text)

@dataclass(frozen=True)
class NormalizedProduct:
    brand: str
    fragrance_name: str
    concentration: str | None
    size_ml: float | None
    packaging: str
    canonical_key: str

@dataclass(frozen=True)
class IdentityConflict:
    code: str
    message: str
    requires_review: bool = True

def normalize_product(brand: str, title: str, *, concentration: str | None = None,
                      size_ml: float | None = None, packaging: str | None = None) -> NormalizedProduct:
    brand_norm = normalize_brand(brand)
    name = normalize_text(title)
    explicit_concentration = normalize_text(concentration)
    concentration_value = None
    for phrases, code in _CONCENTRATIONS:
        if any(re.search(r"(?<![a-z0-9])" + re.escape(p) + r"(?![a-z0-9])", name) for p in phrases):
            concentration_value = code
            break
    if explicit_concentration:
        for phrases, code in _CONCENTRATIONS:
            if explicit_concentration in phrases or explicit_concentration == code:
                concentration_value = code
                break

    packaging_value = normalize_text(packaging or "")
    for code, phrases in _PACKAGING.values():
        if packaging_value == code or any(p in name for p in phrases):
            packaging_value = code
            break
    if packaging_value not in {v[0] for v in _PACKAGING.values()}:
        packaging_value = "standard"

    found_sizes = _SIZE.findall(name)
    parsed_sizes = []
    for amount, unit in found_sizes:
        number = float(amount.replace(",", "."))
        unit = unit.lower()
        if unit == "cl": number *= 10
        elif unit == "l": number *= 1000
        elif unit == "oz": number *= 29.5735
        parsed_sizes.append(number)
    if size_ml is None and len(parsed_sizes) == 1:
        size_ml = parsed_sizes[0]
    elif size_ml is None and len(parsed_sizes) > 1:
        raise ValueError("multiple_size_values_require_review")

    for phrases, _ in _CONCENTRATIONS:
        for phrase in phrases:
            name = _remove_phrase(name, phrase)
    for _, phrases in _PACKAGING.values():
        for phrase in phrases:
            name = _remove_phrase(name, phrase)
    name = _SIZE.sub(" ", name)
    name = _SPACE.sub(" ", name).strip()
    if brand_norm and name.startswith(brand_norm + " "):
        name = name[len(brand_norm):].strip()
    if not brand_norm or not name:
        raise ValueError("brand_and_fragrance_name_are_required")

    size_token = str(int(size_ml)) if size_ml is not None and float(size_ml).is_integer() else (str(size_ml).rstrip("0").rstrip(".") if size_ml is not None else "unknown")
    key = "|".join((brand_norm.replace(" ", "-"), name.replace(" ", "-"),
                    concentration_value or "unknown", size_token,
                    packaging_value))
    return NormalizedProduct(brand_norm, name, concentration_value, size_ml, packaging_value, key)

def normalize_gtin(value: object) -> str | None:
    if value is None or isinstance(value, (dict, list, tuple, bool)):
        return None
    digits = _GTIN.sub("", str(value))
    if len(digits) not in (8, 12, 13, 14):
        return None
    total = sum(int(d) * (3 if i % 2 == 0 else 1)
                for i, d in enumerate(reversed(digits[:-1])))
    if (10 - total % 10) % 10 != int(digits[-1]):
        return None
    return digits

def deduplication_decision(*, left_gtin: object, right_gtin: object,
                            left_key: str, right_key: str) -> tuple[str, IdentityConflict | None]:
    """Return same/different/review. Conflicting valid GTINs always require review."""
    a, b = normalize_gtin(left_gtin), normalize_gtin(right_gtin)
    if a and b and a != b:
        return "review", IdentityConflict("gtin_conflict", "Different valid GTINs cannot be auto-merged.")
    if a and b and a == b:
        return "same", None
    if left_key == right_key:
        return "same", None
    return "different", None
