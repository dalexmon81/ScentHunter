"""Deterministic, loss-minimizing normalization for canonical fragrance identity.

Do not remove concentration, volume or sellable-format information from the
incoming record. The base-name helper is intended for canonical identity only;
variant fields must be extracted and retained separately by the caller.
"""
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
    "eau de parfum": "edp", "edp": "edp",
    "eau de toilette": "edt", "edt": "edt",
    "eau de cologne": "edc", "edc": "edc",
    "extrait de parfum": "extrait", "extrait": "extrait",
    "parfum": "parfum",
}

_FORMAT_TERMS = {
    "tester": "tester",
    "refill": "refill",
    "recharge": "refill",
    "gift set": "gift_set",
    "coffret": "gift_set",
    "mini": "mini",
    "minature": "mini",
    "miniature": "mini",
}

# Only exact curated aliases belong here. Never use prefix or substring aliases.
_BRAND_ALIASES = {
    "christian dior": "dior",
    "dior": "dior",
    "nishane istanbul": "nishane",
    "nishane": "nishane",
}


def normalize_text(value: str | None) -> str:
    """Fold Unicode, accents, case and punctuation into stable ASCII tokens."""
    if value is None:
        return ""
    decomposed = unicodedata.normalize("NFKD", str(value))
    unaccented = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    folded = unaccented.casefold().replace("&", " and ")
    return _SPACE_RE.sub(" ", _NON_ALNUM_RE.sub(" ", folded)).strip()


def normalize_brand(value: str | None) -> str:
    """Normalize a brand name through exact, explicitly curated aliases."""
    normalized = normalize_text(value)
    return _BRAND_ALIASES.get(normalized, normalized)


def extract_concentration(value: str | None) -> str | None:
    """Return an explicit known concentration without guessing a default."""
    normalized = normalize_text(value)
    if not normalized:
        return None
    for phrase in sorted(_CONCENTRATIONS, key=len, reverse=True):
        if re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", normalized):
            return _CONCENTRATIONS[phrase]
    return None


def extract_size_ml(value: Any) -> int | None:
    """Extract explicit ML size only; reject ambiguous or non-integral sizes."""
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None
    if amount <= 0 or amount != amount.to_integral_value():
        return None
    return int(amount)


def extract_size_from_text(value: str | None) -> int | None:
    """Extract ML size from text; other units are deliberately not converted."""
    if not value:
        return None
    for match in _VOLUME_RE.finditer(str(value)):
        unit = match.group(2).casefold()
        if unit in {"ml", "millilitre", "milliliter"}:
            return extract_size_ml(match.group(1))
    return None


def extract_format_flags(value: str | None) -> dict[str, bool]:
    """Return explicit package-format flags, defaulting to False for a known title.

    Callers that distinguish unknown from false should persist None when the
    incoming title is absent or not authoritative.
    """
    normalized = normalize_text(value)
    return {
        "is_tester": bool(re.search(r"(?<!\w)tester(?!\w)", normalized)),
        "is_refill": bool(re.search(r"(?<!\w)(refill|recharge)(?!\w)", normalized)),
        "is_gift_set": bool(re.search(r"(?<!\w)(gift set|coffret)(?!\w)", normalized)),
        "is_mini": bool(re.search(r"(?<!\w)(mini|miniature|minature)(?!\w)", normalized)),
    }


def normalize_fragrance_name(value: str | None) -> str:
    """Return a normalized base name while removing recognized variant tokens."""
    normalized = normalize_text(value)
    if not normalized:
        return ""
    tokens = normalized.split()
    removable = {
        "eau", "de", "parfum", "edp", "toilette", "edt", "cologne", "edc",
        "extrait", "tester", "refill", "recharge", "coffret", "mini",
        "miniature", "minature", "spray", "vap",
    }
    output: list[str] = []
    for token in tokens:
        if token in removable:
            continue
        # A size token is removed only when it is a numeric value immediately
        # followed by a recognized unit.
        if re.fullmatch(r"\d+(?:[.,]\d+)?", token):
            continue
        output.append(token)
    return " ".join(output).strip()


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
        """Stable identity key. Unknown attributes remain explicit as 'unknown'."""
        fields = (
            self.brand,
            self.fragrance,
            self.concentration or "unknown",
            str(self.size_ml) if self.size_ml is not None else "unknown",
            "tester" if self.is_tester else "regular" if self.is_tester is False else "unknown",
            "refill" if self.is_refill else "standard" if self.is_refill is False else "unknown",
            "gift_set" if self.is_gift_set else "single" if self.is_gift_set is False else "unknown",
            "mini" if self.is_mini else "standard" if self.is_mini is False else "unknown",
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
    """Build a conservative identity while preserving explicit variant data."""
    full_title = title or fragrance_name or ""
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
        is_tester=flags["is_tester"] if is_tester is None and full_title else is_tester,
        is_refill=flags["is_refill"] if is_refill is None and full_title else is_refill,
        is_gift_set=flags["is_gift_set"] if is_gift_set is None and full_title else is_gift_set,
        is_mini=flags["is_mini"] if is_mini is None and full_title else is_mini,
    )
