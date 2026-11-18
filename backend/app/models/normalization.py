"""Deterministic, loss-minimizing normalization for canonical fragrance identity."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

_SPACE_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_VOLUME_RE = re.compile(r"(?<!\w)(\d+(?:[.,]\d+)?)\s*(ml|millilitre|milliliter|cl|l|oz|fl\s*oz)(?!\w)", re.I)
_CONCENTRATIONS = {
    "eau de parfum": "edp", "edp": "edp", "eau de toilette": "edt", "edt": "edt",
    "eau de cologne": "edc", "edc": "edc", "extrait de parfum": "extrait",
    "extrait": "extrait", "parfum": "parfum",
}
_BRAND_ALIASES = {
    "christian dior": "dior", "dior": "dior",
    "nishane istanbul": "nishane", "nishane": "nishane",
}


def normalize_text(value: str | None) -> str:
    """Normalize Unicode, accents, case and punctuation into stable tokens."""
    if value is None:
        return ""
    decomposed = unicodedata.normalize("NFKD", str(value))
    unaccented = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _SPACE_RE.sub(" ", _NON_ALNUM_RE.sub(" ", unaccented.casefold().replace("&", " and "))).strip()


def normalize_brand(value: str | None) -> str:
    """Use exact, curated aliases only; never collapse brand substrings."""
    normalized = normalize_text(value)
    return _BRAND_ALIASES.get(normalized, normalized)


def extract_concentration(value: str | None) -> str | None:
    """Return an explicit known concentration, or None when not supplied."""
    normalized = normalize_text(value)
    for phrase in sorted(_CONCENTRATIONS, key=len, reverse=True):
        if re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", normalized):
            return _CONCENTRATIONS[phrase]
    return None


def extract_size_ml(value: Any) -> int | None:
    """Accept only positive integral millilitres."""
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None
    return int(amount) if amount > 0 and amount == amount.to_integral_value() else None


def extract_size_from_text(value: str | None) -> int | None:
    """Extract ML values only; do not convert ambiguous package units."""
    if not value:
        return None
    for match in _VOLUME_RE.finditer(value):
        if match.group(2).casefold() in {"ml", "millilitre", "milliliter"}:
            return extract_size_ml(match.group(1))
    return None


def extract_format_flags(value: str | None) -> dict[str, bool]:
    """Detect explicit sellable format markers from a retailer title."""
    normalized = normalize_text(value)
    return {
        "is_tester": bool(re.search(r"(?<!\w)tester(?!\w)", normalized)),
        "is_refill": bool(re.search(r"(?<!\w)(refill|recharge)(?!\w)", normalized)),
        "is_gift_set": bool(re.search(r"(?<!\w)(gift set|coffret)(?!\w)", normalized)),
        "is_mini": bool(re.search(r"(?<!\w)(mini|miniature|minature)(?!\w)", normalized)),
    }


def normalize_fragrance_name(value: str | None) -> str:
    """Remove known concentration/format/volume tokens from a base fragrance name.

    Numeric model/name tokens are retained unless followed by an explicit
    recognized volume unit.
    """
    normalized = normalize_text(value)
    if not normalized:
        return ""
    tokens = normalized.split()
    removable = {
        "eau", "de", "parfum", "edp", "toilette", "edt", "cologne", "edc",
        "extrait", "tester", "refill", "recharge", "coffret", "mini",
        "miniature", "minature", "spray", "vap",
    }
    result: list[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in removable:
            i += 1
            continue
        if re.fullmatch(r"\d+(?:[.,]\d+)?", token) and i + 1 < len(tokens) and tokens[i + 1] in {"ml", "cl", "l", "oz", "vap"}:
            i += 2
            continue
        if token in {"ml", "cl", "oz", "vap"}:
            i += 1
            continue
        result.append(token)
        i += 1
    return " ".join(result).strip()


@dataclass(frozen=True)
class CanonicalIdentity:
    brand: str
    fragrance: str
    concentration: str | None
    size_ml: int | None
    is_tester: bool | None
    is_refill: bool | None
    is_gift_set: bool | None
    is_mini: bool | None

    @property
    def canonical_key(self) -> str:
        """Stable variant key; missing values remain distinct from explicit false."""
        fields = (
            self.brand, self.fragrance, self.concentration or "unknown",
            str(self.size_ml) if self.size_ml is not None else "unknown",
            "tester" if self.is_tester is True else "regular" if self.is_tester is False else "unknown",
            "refill" if self.is_refill is True else "standard" if self.is_refill is False else "unknown",
            "gift_set" if self.is_gift_set is True else "single" if self.is_gift_set is False else "unknown",
            "mini" if self.is_mini is True else "standard" if self.is_mini is False else "unknown",
        )
        return "|".join(fields)


def build_identity(
    *,
    brand: str | None,
    fragrance_name: str | None,
    title: str | None = None,
    concentration: str | None = None,
    size_ml: Any = None,
    is_tester: bool | None = None,
    is_refill: bool | None = None,
    is_gift_set: bool | None = None,
    is_mini: bool | None = None,
) -> CanonicalIdentity:
    """Build a canonical identity without losing variant attributes."""
    full_title = title or fragrance_name or ""
    has_title = bool(full_title)
    flags = extract_format_flags(full_title)
    resolved_concentration = extract_concentration(concentration) or extract_concentration(full_title)
    resolved_size = extract_size_ml(size_ml)
    if resolved_size is None:
        resolved_size = extract_size_from_text(full_title)
    return CanonicalIdentity(
        brand=normalize_brand(brand),
        fragrance=normalize_fragrance_name(fragrance_name or full_title),
        concentration=resolved_concentration,
        size_ml=resolved_size,
        is_tester=flags["is_tester"] if is_tester is None and has_title else is_tester,
        is_refill=flags["is_refill"] if is_refill is None and has_title else is_refill,
        is_gift_set=flags["is_gift_set"] if is_gift_set is None and has_title else is_gift_set,
        is_mini=flags["is_mini"] if is_mini is None and has_title else is_mini,
    )
