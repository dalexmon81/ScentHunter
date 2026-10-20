"""Pure, deterministic mapper from ScentHunter's legacy catalog rows.

This module performs no network I/O and never writes to the legacy database.
Pass one store_products row and, when available, one store_product_variants
row. Variant URLs and measurements are deliberately preserved as identity.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import re
import unicodedata
from typing import Any, Mapping
from urllib.parse import urlparse

from .models import Offer, Product, SourceObservation, Variant, price_to_minor_units

_SIZE_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:ml|cl|lit(?:er|re)s?|l|fl\.?\s*oz|oz)\b",
    re.I,
)
_CONCENTRATION_RE = re.compile(
    r"\b(?:eau\s+de\s+parfum|eau\s+de\s+toilette|eau\s+de\s+cologne|"
    r"eau\s+fraiche|extrait\s+de\s+parfum|edp|edt|edc|parfum|perfume)\b",
    re.I,
)

_GENERIC_PATH_SEGMENTS = {
    "product", "products", "produit", "produits",
    "artikel", "articolo", "item", "items", "p",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", _text(value).lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text)).strip()


def _id(prefix: str, *parts: Any) -> str:
    material = "\x1f".join(_norm(p) for p in parts)
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _canonical_name(name: str) -> str:
    cleaned = _SIZE_RE.sub(" ", name)
    cleaned = _CONCENTRATION_RE.sub(" ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip(" -|,/")


def _slug_text(value: str) -> str:
    """Convert a stored URL slug into readable text."""
    value = re.sub(r"\.(?:html?|aspx?)$", "", value, flags=re.I)
    value = re.sub(r"(?:[_-]z\d+|[-_]\d{5,})$", "", value, flags=re.I)
    value = re.sub(r"[-_]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _url_fallback(
    product_row: Mapping[str, Any],
    variant_row: Mapping[str, Any],
) -> tuple[str, str]:
    """Recover missing fields from stored URLs where the evidence is adequate.

    No network access is performed. URL-derived guesses are conservative:
    generic URL path prefixes are not treated as brands, and a brand inferred
    from a repeated slug prefix is only used when the prefix repeats exactly.
    """
    url = _text(
        variant_row.get("variant_url")
        or variant_row.get("url")
        or product_row.get("url")
    )
    parsed = urlparse(url)
    segments = [part for part in parsed.path.split("/") if part]

    name = _text(variant_row.get("name") or product_row.get("name"))
    brand = _text(variant_row.get("brand") or product_row.get("brand"))
    slug = _slug_text(segments[-1]) if segments else ""

    if not name:
        name = slug

    # Some retailer URLs have the brand as the first path segment, e.g.
    # /hugo-boss/boss-bottled-night/...
    if not brand and len(segments) >= 2:
        prefix = _slug_text(segments[0])
        if (
            prefix
            and len(prefix) <= 40
            and prefix.casefold() not in _GENERIC_PATH_SEGMENTS
        ):
            brand = prefix

    # Some slugs repeat the brand at the beginning, e.g. "boss-boss-bottled".
    if not brand and slug:
        words = slug.split()
        for size in range(min(3, len(words) // 2), 0, -1):
            first = [word.casefold() for word in words[:size]]
            second = [word.casefold() for word in words[size : 2 * size]]
            if first == second:
                brand = " ".join(words[:size])
                name = " ".join(words[size:])
                break

    return name, brand


def _timestamp(value: Any) -> str:
    if value in (None, ""):
        raise ValueError(
            "legacy row has no fetched_at timestamp; refusing to invent freshness"
        )
    # Legacy catalog stores fetched_at as Unix seconds (REAL).
    try:
        numeric = float(value)
        if numeric > 0:
            return datetime.fromtimestamp(
                numeric, timezone.utc
            ).isoformat(timespec="seconds")
    except (TypeError, ValueError, OverflowError, OSError):
        pass

    raw = _text(value)
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


def _size(
    base: Mapping[str, Any],
    variant: Mapping[str, Any],
) -> Decimal | None:
    value = variant.get("size_ml")
    if value in (None, ""):
        value = base.get("size_ml")
    if value in (None, ""):
        return None

    try:
        parsed = Decimal(str(value).replace(",", "."))
    except InvalidOperation:
        raise ValueError(f"invalid size_ml: {value!r}") from None

    if not parsed.is_finite() or parsed <= 0:
        raise ValueError(f"invalid size_ml: {value!r}")
    return parsed


def observation_from_legacy_rows(
    *,
    store: str,
    product_row: Mapping[str, Any],
    variant_row: Mapping[str, Any] | None = None,
    trace_id: str = "legacy-bridge",
    parser_version: str = "legacy-row-v1",
) -> SourceObservation:
    """Map a legacy catalog row pair to a typed observation or fail loudly.

    `product_row` is a row from store_products. `variant_row` is an optional
    matching row from store_product_variants. No fuzzy product matching occurs.
    """
    variant_row = variant_row or {}

    raw_name = _text(variant_row.get("name") or product_row.get("name"))
    brand = _text(variant_row.get("brand") or product_row.get("brand"))

    # Recover missing name/brand only from the URL already stored in the
    # legacy database. If the URL is insufficient, reject the row explicitly.
    if not raw_name or not brand:
        fallback_name, fallback_brand = _url_fallback(product_row, variant_row)
        raw_name = raw_name or fallback_name
        brand = brand or fallback_brand

    if not raw_name or not brand:
        raise ValueError(
            "legacy row requires name/brand; URL fallback was insufficient"
        )

    canonical_name = _canonical_name(raw_name)
    if not canonical_name:
        raise ValueError(
            "legacy name is empty after removing commercial descriptors"
        )

    product_id = _id("prod", brand, canonical_name)
    size_ml = _size(product_row, variant_row)
    concentration = (
        _text(variant_row.get("concentration") or product_row.get("concentration"))
        or None
    )
    gender = _text(variant_row.get("gender") or product_row.get("gender")) or None
    sku = _text(variant_row.get("sku") or product_row.get("sku")) or None
    gtin = _text(variant_row.get("gtin") or product_row.get("gtin")) or None
    mpn = _text(variant_row.get("mpn") or product_row.get("mpn")) or None

    pack_count = int(
        variant_row.get("pack_count") or product_row.get("pack_count") or 1
    )

    # GTIN/MPN usually identify a sellable variant, not the abstract product.
    variant_id = _id(
        "var",
        product_id,
        concentration or "",
        size_ml or "",
        pack_count,
        gender or "",
        gtin or "",
        mpn or "",
    )

    base_url = _text(product_row.get("url"))
    offer_url = _text(
        variant_row.get("variant_url")
        or variant_row.get("url")
        or base_url
    )
    if not offer_url:
        raise ValueError("legacy row requires url or variant_url")

    source_url = base_url or offer_url

    price_value = variant_row.get("price")
    if price_value in (None, ""):
        price_value = product_row.get("price")
    if price_value in (None, ""):
        raise ValueError("legacy row has no price")

    currency = _text(
        variant_row.get("currency") or product_row.get("currency")
    ).upper()
    price_minor = price_to_minor_units(Decimal(str(price_value)), currency)

    observed_at = _timestamp(
        variant_row.get("fetched_at") or product_row.get("fetched_at")
    )

    product = Product(product_id, brand, canonical_name)
    variant = Variant(
        variant_id,
        product_id,
        concentration,
        size_ml,
        pack_count,
        gender,
    )
    offer_id = _id("offer", store, offer_url, variant_id)

    availability = _text(
        variant_row.get("availability")
        or product_row.get("availability")
        or "unknown"
    ).lower()

    offer = Offer(
        offer_id,
        variant_id,
        store,
        offer_url,
        price_minor,
        currency,
        availability,
        observed_at,
        sku,
    )

    return SourceObservation(
        store=store,
        source_url=source_url,
        observed_at=observed_at,
        product=product,
        variant=variant,
        offer=offer,
        raw_title=raw_name,
        raw_price=str(price_value),
        parser_version=parser_version,
        trace_id=trace_id,
    )
