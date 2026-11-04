"""Deterministic, side-effect-free product identity normalization."""
from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

_SPACE = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_SIZE = re.compile(r"(?<![a-z0-9])(\d+(?:[.,]\d+)?)\s*(ml|milliliters?|cl|l|oz)(?![a-z])", re.I)
_GTIN = re.compile(r"\D+")
_BRAND_ALIASES = {
    "dior": "christian dior",
    "christian dior": "christian dior",
    "nishane": "nishane istanbul",
    "nishane istanbul": "nishane istanbul",
}
_CONCENTRATIONS = (
    (("extrait de parfum", "parfum extract", "extrait"), "extrait"),
    (("eau de parfum", "edp"), "edp"),
    (("eau de toilette", "edt"), "edt"),
    (("eau de cologne", "edc", "cologne"), "cologne"),
    (("pure perfume", "parfum"), "parfum"),
)
_PACKAGING = {
    "tester": ("tester", "testeur"),
    "refill": ("refill", "recharge", "nachfullung", "nachfullpackung"),
    "gift_set": ("gift set", "coffret", "set regalo", "geschenkset"),
    "mini": ("miniature", "mini", "travel size", "sample"),
}
_NOISE = ("spray", "vap", "vaporisateur", "vaporizer")

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

def _contains_phrase(text: str, phrase: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", text) is not None

@dataclass(frozen=True)
class NormalizedProduct:
    brand: str
    fragrance_name: str
    concentration: str | None
    size_ml: float | None
    packaging: str
    canonical_key: str

    @property
    def is_tester(self) -> bool:
        return self.packaging == "tester"

    @property
    def is_refill(self) -> bool:
        return self.packaging == "refill"

    @property
    def is_gift_set(self) -> bool:
        return self.packaging == "gift_set"

    @property
    def is_mini(self) -> bool:
        return self.packaging == "mini"

@dataclass(frozen=True)
class IdentityConflict:
    code: str
    message: str
    requires_review: bool = True

def _extract_concentration(name: str, explicit: str | None) -> str | None:
    found = {code for phrases, code in _CONCENTRATIONS
             if any(_contains_phrase(name, phrase) for phrase in phrases)}
    explicit_norm = normalize_text(explicit)
    if explicit_norm:
        explicit_codes = {code for phrases, code in _CONCENTRATIONS
                          if explicit_norm == code or explicit_norm in phrases}
        if not explicit_codes:
            raise ValueError("unsupported_concentration_requires_review")
        found.update(explicit_codes)
    if len(found) > 1:
        raise ValueError("conflicting_concentrations_require_review")
    return next(iter(found), None)

def normalize_product(brand: str, title: str, *, concentration: str | None = None,
                      size_ml: float | None = None, packaging: str | None = None) -> NormalizedProduct:
    brand_norm = normalize_brand(brand)
    name = normalize_text(title)
    if not brand_norm or not name:
        raise ValueError("brand_and_fragrance_name_are_required")

    concentration_value = _extract_concentration(name, concentration)

    packaging_found = {kind for kind, phrases in _PACKAGING.items()
                       if any(_contains_phrase(name, phrase) for phrase in phrases)}
    explicit_packaging = normalize_text(packaging or "")
    if explicit_packaging:
        explicit_packaging = explicit_packaging.replace(" ", "_")
        if explicit_packaging not in _PACKAGING and explicit_packaging != "standard":
            raise ValueError("unsupported_packaging_requires_review")
        if explicit_packaging != "standard":
            packaging_found.add(explicit_packaging)
    if len(packaging_found) > 1:
        raise ValueError("conflicting_packaging_requires_review")
    packaging_value = next(iter(packaging_found), "standard")

    sizes = []
    for amount, unit in _SIZE.findall(name):
        number = float(amount.replace(",", "."))
        unit = unit.lower()
        if unit == "cl":
            number *= 10
        elif unit == "l":
            number *= 1000
        elif unit == "oz":
            number *= 29.5735
        sizes.append(number)
    if size_ml is not None and (not isinstance(size_ml, (int, float)) or size_ml <= 0):
        raise ValueError("size_ml_must_be_positive")
    if size_ml is not None and sizes and any(abs(v - size_ml) > 0.01 for v in sizes):
        raise ValueError("conflicting_sizes_require_review")
    if size_ml is None:
        if len(sizes) > 1 and any(abs(v - sizes[0]) > 0.01 for v in sizes[1:]):
            raise ValueError("multiple_size_values_require_review")
        size_ml = sizes[0] if sizes else None

    for phrases, _ in _CONCENTRATIONS:
        for phrase in phrases:
            name = re.sub(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", " ", name)
    for phrases in _PACKAGING.values():
        for phrase in phrases:
            name = re.sub(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", " ", name)
    for phrase in _NOISE:
        name = re.sub(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", " ", name)
    name = _SIZE.sub(" ", name)
    name = _SPACE.sub(" ", name).strip()
    if name.startswith(brand_norm + " "):
        name = name[len(brand_norm):].strip()
    if not name:
        raise ValueError("fragrance_name_empty_after_normalization")

    size_token = "unknown" if size_ml is None else (
        str(int(size_ml)) if float(size_ml).is_integer() else format(float(size_ml), "g")
    )
    key = "|".join((brand_norm.replace(" ", "-"), name.replace(" ", "-"),
                    concentration_value or "unknown", size_token, packaging_value))
    return NormalizedProduct(brand_norm, name, concentration_value, size_ml,
                             packaging_value, key)

def normalize_gtin(value: object) -> str | None:
    if value is None or isinstance(value, (dict, list, tuple, bool)):
        return None
    digits = _GTIN.sub("", str(value))
    if len(digits) not in (8, 12, 13, 14):
        return None
    total = sum(int(d) * (3 if i % 2 == 0 else 1)
                for i, d in enumerate(reversed(digits[:-1])))
    return digits if (10 - total % 10) % 10 == int(digits[-1]) else None

def deduplication_decision(*, left_gtin: object, right_gtin: object,
                            left_key: str, right_key: str) -> tuple[str, IdentityConflict | None]:
    """Return same/different/review; mismatched verified GTINs are never merged."""
    a, b = normalize_gtin(left_gtin), normalize_gtin(right_gtin)
    if a and b and a != b:
        return "review", IdentityConflict("gtin_conflict", "Different valid GTINs cannot be auto-merged.")
    if a and b:
        return ("same", None) if a == b else ("review", IdentityConflict("gtin_incomplete", "GTIN identity is uncertain."))
    if left_key == right_key:
        return "same", None
    return "different", None
