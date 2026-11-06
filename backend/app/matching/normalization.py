"""Deterministic normalization for canonical fragrance identities and variants.

This module is intentionally pure: it performs no I/O and never guesses missing
variant attributes. Ambiguous or absent values remain empty/None.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

_BRAND_ALIASES = {
    "dior": "christian dior",
    "christian dior": "christian dior",
    "nishane": "nishane istanbul",
    "nishane istanbul": "nishane istanbul",
}
_CONCENTRATIONS = (
    ("eau de parfum intense", "edp_intense"),
    ("edp intense", "edp_intense"),
    ("intense eau de parfum", "edp_intense"),
    ("eau de toilette intense", "edt_intense"),
    ("edt intense", "edt_intense"),
    ("intense eau de toilette", "edt_intense"),
    ("parfum intense", "parfum_intense"),
    ("intense parfum", "parfum_intense"),
    ("extrait de parfum", "extrait"),
    ("eau de parfum", "edp"),
    ("eau de toilette", "edt"),
    ("eau de cologne", "edc"),
    ("eau fraiche", "eau_fraiche"),
    ("edp", "edp"), ("edt", "edt"), ("edc", "edc"),
    ("parfum", "parfum"), ("perfume", "parfum"), ("elixir", "elixir"),
)
_AUDIENCES = {
    "women": ("donna", "women", "woman", "femme", "dames", "damen"),
    "men": ("uomo", "men", "man", "homme", "herren", "heren"),
    "unisex": ("unisex",),
}


def _ascii_words(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("’", "'")
    text = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def normalize_brand(value: object) -> str:
    normalized = _ascii_words(value).replace(" and ", " & ")
    return _BRAND_ALIASES.get(normalized, normalized)


def normalize_concentration(*values: object) -> str:
    text = " ".join(_ascii_words(value) for value in values if value not in (None, ""))
    for phrase, token in _CONCENTRATIONS:
        if re.search(rf"\b{re.escape(phrase)}\b", text):
            return token
    return ""


def extract_size_ml(*values: object) -> int | None:
    text = " ".join(str(value or "") for value in values)
    match = re.search(r"(?<!\d)(\d{1,4}(?:[.,]\d+)?)\s*(ml|millilit(?:er|re)s?|cl|l|lit(?:er|re)s?|fl\.?\s*oz|oz)\b", text, re.I)
    if not match:
        return None
    try:
        amount = Decimal(match.group(1).replace(",", "."))
    except InvalidOperation:
        return None
    unit = re.sub(r"\s+", "", match.group(2).lower()).replace(".", "")
    if unit == "cl":
        amount *= 10
    elif unit in {"l", "liter", "liters", "litre", "litres"}:
        amount *= 1000
    elif unit in {"oz", "floz"}:
        amount *= Decimal("29.5735")
    nearest_five = (amount / Decimal("5")).quantize(Decimal("1")) * Decimal("5")
    if abs(amount - nearest_five) <= Decimal("0.6"):
        amount = nearest_five
    result = int(amount.quantize(Decimal("1")))
    return result if result > 0 else None


def _detect_flag(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(rf"\b{pattern}\b", text) for pattern in patterns)


@dataclass(frozen=True)
class NormalizedFragrance:
    brand: str
    name: str
    concentration: str
    size_ml: int | None
    audience: str | None
    is_tester: bool
    is_refill: bool
    is_gift_set: bool
    canonical_key: str


def normalize_fragrance(
    brand: object,
    name: object,
    *,
    concentration: object = "",
    size: object = "",
    is_tester: bool | None = None,
    is_refill: bool | None = None,
    is_gift_set: bool | None = None,
) -> NormalizedFragrance:
    brand_key = normalize_brand(brand)
    raw_name = str(name or "")
    combined = _ascii_words(" ".join((raw_name, str(concentration or ""), str(size or ""))))
    concentration_key = normalize_concentration(concentration, raw_name)
    size_value = extract_size_ml(size, raw_name)

    audience_hits = [key for key, words in _AUDIENCES.items()
                     if any(re.search(rf"\b{re.escape(word)}\b", combined) for word in words)]
    audience = audience_hits[0] if len(audience_hits) == 1 else None

    tester = bool(is_tester) if is_tester is not None else _detect_flag(combined, ("tester", "testeur"))
    refill = bool(is_refill) if is_refill is not None else _detect_flag(combined, ("refill", "recharge"))
    gift_set = bool(is_gift_set) if is_gift_set is not None else _detect_flag(combined, ("gift set", "coffret", "set cadeau"))

    clean = _ascii_words(raw_name)
    for phrase, _token in _CONCENTRATIONS:
        clean = re.sub(rf"\b{re.escape(phrase)}\b", " ", clean)
    clean = re.sub(r"\b\d{1,4}(?:[.,]\d+)?\s*(?:ml|cl|l|oz)\b", " ", clean)
    clean = re.sub(r"\b(?:tester|testeur|refill|recharge|gift set|coffret|set cadeau|spray|vaporisateur)\b", " ", clean)
    for words in _AUDIENCES.values():
        for word in words:
            clean = re.sub(rf"\b{re.escape(word)}\b", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()

    parts = [brand_key, clean, concentration_key, str(size_value or ""),
             "tester" if tester else "", "refill" if refill else "", "gift_set" if gift_set else ""]
    canonical_key = "|".join(parts)
    return NormalizedFragrance(brand_key, clean, concentration_key, size_value,
                               audience, tester, refill, gift_set, canonical_key)
