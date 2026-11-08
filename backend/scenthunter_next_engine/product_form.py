"""Controlled product-form taxonomy and conservative retailer-title detection.

Forms describe the sellable variant, not the abstract fragrance identity.
Unknown forms remain unknown; the detector only returns a form for explicit
product-type language or explicit fine-fragrance concentration terms.
"""
from __future__ import annotations

import re
import unicodedata


PRODUCT_FORM_VALUES = frozenset({
    "fine_fragrance",
    "perfume_oil",
    "deodorant",
    "body_mist",
    "hair_mist",
    "body_care",
    "home_fragrance",
    "gift_set",
    "discovery_set",
})


def _normalized(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


_FORM_ALIASES = {
    "fine fragrance": "fine_fragrance",
    "fine_fragrance": "fine_fragrance",
    "perfume": "fine_fragrance",
    "perfume spray": "fine_fragrance",
    "eau de parfum": "fine_fragrance",
    "edp": "fine_fragrance",
    "eau de toilette": "fine_fragrance",
    "edt": "fine_fragrance",
    "eau de cologne": "fine_fragrance",
    "edc": "fine_fragrance",
    "extrait de parfum": "fine_fragrance",
    "parfum": "fine_fragrance",
    "perfume oil": "perfume_oil",
    "fragrance oil": "perfume_oil",
    "concentrated perfume oil": "perfume_oil",
    "attar": "perfume_oil",
    "mukhallat": "perfume_oil",
    "deodorant": "deodorant",
    "deodorant spray": "deodorant",
    "deodorant stick": "deodorant",
    "deo stick": "deodorant",
    "perfumed deodorant spray": "deodorant",
    "antiperspirant": "deodorant",
    "body mist": "body_mist",
    "body spray": "body_mist",
    "body splash": "body_mist",
    "hair mist": "hair_mist",
    "body care": "body_care",
    "body lotion": "body_care",
    "body cream": "body_care",
    "body butter": "body_care",
    "body wash": "body_care",
    "shower gel": "body_care",
    "hand cream": "body_care",
    "home fragrance": "home_fragrance",
    "room spray": "home_fragrance",
    "reed diffuser": "home_fragrance",
    "diffuser": "home_fragrance",
    "scented candle": "home_fragrance",
    "gift set": "gift_set",
    "giftset": "gift_set",
    "coffret": "gift_set",
    "discovery set": "discovery_set",
    "discovery kit": "discovery_set",
}


def normalize_product_form(value: object) -> str | None:
    """Map a recognized explicit form label to its canonical enum value."""
    if value is None:
        return None
    normalized = _normalized(value)
    if not normalized:
        return None
    direct = _FORM_ALIASES.get(normalized)
    if direct:
        return direct
    underscored = normalized.replace(" ", "_")
    return underscored if underscored in PRODUCT_FORM_VALUES else None


def detect_product_form(title: object) -> str | None:
    """Detect only clear form descriptors; otherwise leave the form unclassified."""
    value = _normalized(title)
    if not value:
        return None

    # Specific kit forms must be checked before the generic fragrance terms.
    checks = (
        ("discovery_set", (r"\bdiscovery set\b", r"\bdiscovery kit\b")),
        ("gift_set", (r"\bgift set\b", r"\bgiftset\b", r"\bcoffret\b")),
        ("deodorant", (r"\bperfumed deodorant spray\b", r"\bdeodorant(?: spray| stick)?\b", r"\bdeo stick\b", r"\bantiperspirant\b")),
        ("hair_mist", (r"\bhair mist\b",)),
        ("body_mist", (r"\bbody mist\b", r"\bbody spray\b", r"\bbody splash\b")),
        ("home_fragrance", (r"\bhome fragrance\b", r"\broom spray\b", r"\breed diffuser\b", r"\bdiffuser\b", r"\bscented candle\b")),
        ("body_care", (r"\bbody lotion\b", r"\bbody cream\b", r"\bbody butter\b", r"\bbody wash\b", r"\bshower gel\b", r"\bhand cream\b", r"\bbody care\b")),
        ("perfume_oil", (r"\bconcentrated perfume oil\b", r"\bperfume oil\b", r"\bfragrance oil\b", r"\battar\b", r"\bmukhallat\b")),
        ("fine_fragrance", (r"\beau de parfum\b", r"\beau de toilette\b", r"\beau de cologne\b", r"\bextrait de parfum\b", r"\bedp\b", r"\bedt\b", r"\bedc\b")),
    )
    for form, patterns in checks:
        if any(re.search(pattern, value) for pattern in patterns):
            return form
    return None
