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


def _size_from_title(title: str) -> Decimal | None:
    """Extract a volume from a title only when it has a recognized unit."""
    match = _SIZE_RE.search(title)
    if not match:
        return None

    number_match = re.match(
        r"(\d+(?:[.,]\d+)?)\s*(.*)",
        match.group(0).strip().lower(),
    )
    if not number_match:
        return None

    try:
        amount = Decimal(number_match.group(1).replace(",", "."))
    except InvalidOperation:
        return None

    unit = re.sub(r"\s+", "", number_match.group(2).replace(".", ""))
    factors = {
        "ml": Decimal("1"),
        "cl": Decimal("10"),
        "l": Decimal("1000"),
        "liter": Decimal("1000"),
        "liters": Decimal("1000"),
        "litre": Decimal("1000"),
        "litres": Decimal("1000"),
        "floz": Decimal("29.5735295625"),
        "oz": Decimal("29.5735295625"),
    }
    factor = factors.get(unit)
    if factor is None:
        return None

    result = amount * factor
    return result if result.is_finite() and result > 0 else None


def _concentration_from_title(title: str) -> str | None:
    """Extract and normalize a concentration descriptor from the raw title."""
    match = _CONCENTRATION_RE.search(title)
    if not match:
        return None

    value = re.sub(r"\s+", " ", match.group(0)).strip().lower()
    return {
        "edp": "eau de parfum",
        "edt": "eau de toilette",
        "edc": "eau de cologne",
        "perfume": "parfum",
    }.get(value, value)


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
    """Recover missing title/brand from stored URL evidence, without network I/O.

    Retailer URL path segments are not treated as brands by default. A brand
    is inferred from a repeated slug prefix or a curated brand prefix in the
    product slug. This avoids turning generic paths such as ``product`` into
    brands or inventing a brand from an arbitrary first word.
    """
    urls = [
        _text(variant_row.get("variant_url")),
        _text(variant_row.get("url")),
        _text(product_row.get("url")),
    ]
    urls = list(dict.fromkeys(url for url in urls if url))

    def url_evidence(url: str) -> tuple[int, int, int]:
        parsed_url = urlparse(url)
        parts = [_slug_text(part) for part in parsed_url.path.split("/") if part]
        candidate_slug = parts[-1] if parts else ""
        normalized = re.sub(r"[^a-z0-9]+", " ", candidate_slug.casefold()).strip()
        generic = {
            "product", "products", "produit", "produits", "artikel",
            "articolo", "item", "items", "p", "shop", "category",
            "categorie", "search", "catalog",
        }
        words = normalized.split()
        informative = bool(words) and normalized not in generic and not all(
            word.isdigit() for word in words
        )
        known_brand = any(
            re.search(r"(?:^| )" + re.escape(token) + r"(?:$| )", normalized)
            for token in (
                "hugo boss", "giorgio armani", "jean paul gaultier",
                "dolce gabbana", "calvin klein", "carolina herrera",
                "narciso rodriguez", "yves saint laurent", "paco rabanne",
                "issey miyake", "tom ford", "ralph lauren", "estee lauder",
                "maison margiela", "victoria secret", "bois 1920",
                "miu miu", "versace", "dior", "chanel", "givenchy",
                "burberry", "prada", "gucci", "hermes", "montblanc",
                "lancome", "rasasi", "floris", "valentino", "mancera",
                "mugler", "yves rocher", "bvlgari", "bulgari", "sisley",
                "clinique", "shiseido", "elizabeth arden", "byredo",
                "diptyque", "creed", "xerjoff", "initio", "amouage",
                "lattafa", "armaf", "ajmal", "azzaro", "michael kors",
                "boss",
            )
        )
        return (int(informative), int(known_brand), min(len(normalized), 180))

    url = max(urls, key=url_evidence) if urls else ""
    parsed = urlparse(url)
    segments = [_slug_text(part) for part in parsed.path.split("/") if part]

    name = _text(variant_row.get("name") or product_row.get("name"))
    brand = _text(variant_row.get("brand") or product_row.get("brand"))
    slug = segments[-1] if segments else ""
    original_name_missing = not name

    if not brand and slug:
        words = slug.split()
        folded = [word.casefold() for word in words]
        for size in range(min(4, len(words) // 2), 0, -1):
            if folded[:size] == folded[size:2 * size]:
                brand = " ".join(words[:size])
                if original_name_missing:
                    name = " ".join(words[size:])
                break

    if not brand and slug:
        normalized_slug = re.sub(r"[^a-z0-9]+", " ", slug.casefold()).strip()
        known_brand_prefixes = (
            ("hugo boss", "Hugo Boss"),
            ("giorgio armani", "Giorgio Armani"),
            ("jean paul gaultier", "Jean Paul Gaultier"),
            ("dolce gabbana", "Dolce & Gabbana"),
            ("calvin klein", "Calvin Klein"),
            ("carolina herrera", "Carolina Herrera"),
            ("narciso rodriguez", "Narciso Rodriguez"),
            ("yves saint laurent", "Yves Saint Laurent"),
            ("paco rabanne", "Rabanne"),
            ("ysl beauty", "Yves Saint Laurent"),
            ("issey miyake", "Issey Miyake"),
            ("tom ford", "Tom Ford"),
            ("ralph lauren", "Ralph Lauren"),
            ("estee lauder", "Estée Lauder"),
            ("maison margiela", "Maison Margiela"),
            ("vera wang", "Vera Wang"),
            ("anna sui", "Anna Sui"),
            ("victoria secret", "Victoria's Secret"),
            ("valentino", "Valentino"),
            ("rasasi", "Rasasi"),
            ("bois 1920", "Bois 1920"),
            ("floris", "Floris"),
            ("miu miu", "Miu Miu"),
            ("versace", "Versace"),
            ("dior", "Dior"),
            ("chanel", "Chanel"),
            ("givenchy", "Givenchy"),
            ("burberry", "Burberry"),
            ("prada", "Prada"),
            ("gucci", "Gucci"),
            ("hermes", "Hermès"),
            ("montblanc", "Montblanc"),
            ("lancome", "Lancôme"),
            ("boss", "BOSS"),
        )
        for prefix, canonical_brand in known_brand_prefixes:
            if normalized_slug == prefix or normalized_slug.startswith(prefix + " "):
                brand = canonical_brand
                if original_name_missing:
                    name = normalized_slug[len(prefix):].strip()
                break

        if not brand:
            known_brand_tokens = (
                ("rasasi", "Rasasi"),
                ("valentino", "Valentino"),
                ("floris", "Floris"),
                ("bois 1920", "Bois 1920"),
                ("miu miu", "Miu Miu"),
                ("hugo boss", "Hugo Boss"),
                ("giorgio armani", "Giorgio Armani"),
                ("jean paul gaultier", "Jean Paul Gaultier"),
                ("dolce gabbana", "Dolce & Gabbana"),
                ("calvin klein", "Calvin Klein"),
                ("carolina herrera", "Carolina Herrera"),
                ("narciso rodriguez", "Narciso Rodriguez"),
                ("yves saint laurent", "Yves Saint Laurent"),
                ("paco rabanne", "Rabanne"),
                ("dior", "Dior"),
                ("chanel", "Chanel"),
                ("versace", "Versace"),
                ("prada", "Prada"),
                ("gucci", "Gucci"),
                ("givenchy", "Givenchy"),
                ("burberry", "Burberry"),
                ("hermes", "Hermès"),
                ("montblanc", "Montblanc"),
                ("lancome", "Lancôme"),
            )
            for token, canonical_brand in known_brand_tokens:
                if re.search(r"(?:^| )" + re.escape(token) + r"(?:$| )", normalized_slug):
                    brand = canonical_brand
                    if original_name_missing:
                        name = re.sub(
                            r"(?:^| )" + re.escape(token) + r"(?:$| )",
                            " ",
                            normalized_slug,
                        )
                        name = re.sub(r"\s+", " ", name).strip()
                    break

    if not brand and len(segments) >= 2:
        prefix_key = re.sub(r"[^a-z0-9]+", "", segments[0].casefold())
        known_path_brands = {
            "hugoboss": "Hugo Boss",
            "boss": "BOSS",
            "chanel": "Chanel",
            "dior": "Dior",
            "armani": "Armani",
            "giorgioarmani": "Giorgio Armani",
            "ysl": "Yves Saint Laurent",
            "versace": "Versace",
            "prada": "Prada",
            "gucci": "Gucci",
            "givenchy": "Givenchy",
            "hermes": "Hermès",
            "jeanpaulgaultier": "Jean Paul Gaultier",
            "rabanne": "Rabanne",
            "valentino": "Valentino",
            "dolcegabbana": "Dolce & Gabbana",
            "calvinklein": "Calvin Klein",
            "burberry": "Burberry",
            "mugler": "Mugler",
            "lancome": "Lancôme",
            "yvesrocher": "Yves Rocher",
            "mancera": "Mancera",
            "montblanc": "Montblanc",
            "isseymiyake": "Issey Miyake",
        }
        brand = known_path_brands.get(prefix_key, "")

    if not name:
        name = slug

    return name, brand


def _timestamp(value: Any) -> str:
    if value in (None, ""):
        raise ValueError(
            "legacy row has no fetched_at timestamp; refusing to invent freshness"
        )
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

    # Structured source values take precedence. Fall back to descriptors in
    # the raw title only when the corresponding field is absent.
    size_ml = _size(product_row, variant_row)
    if size_ml is None:
        size_ml = _size_from_title(raw_name)

    concentration = (
        _text(variant_row.get("concentration") or product_row.get("concentration"))
        or _concentration_from_title(raw_name)
    )
    gender = _text(variant_row.get("gender") or product_row.get("gender")) or None
    sku = _text(variant_row.get("sku") or product_row.get("sku")) or None
    gtin = _text(variant_row.get("gtin") or product_row.get("gtin")) or None
    mpn = _text(variant_row.get("mpn") or product_row.get("mpn")) or None
    variant_key = _text(
        variant_row.get("variant_key") or product_row.get("variant_key")
    ) or None

    pack_count = int(
        variant_row.get("pack_count") or product_row.get("pack_count") or 1
    )

    variant_id = _id(
        "var",
        product_id,
        concentration or "",
        size_ml or "",
        pack_count,
        gender or "",
        gtin or "",
        mpn or "",
        variant_key or "",
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
