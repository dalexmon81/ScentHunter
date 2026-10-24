"""Conservative normalization of raw retailer records into RetailerOffer.

This module does not scrape, match canonical products, write databases, or mutate
input records. Field aliases are generic and can be extended by retailer adapters
once their real payload shapes have been inspected.
"""
from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

from .models import RetailerOffer, decimal_or_none


_NAME_FIELDS = ("raw_name", "name", "title", "product_name", "productName", "description")
_BRAND_FIELDS = ("brand_raw", "brand", "brand_name", "brandName", "manufacturer")
_SIZE_FIELDS = ("size_ml", "sizeMl", "volume_ml", "volumeMl", "format_ml", "formatMl")
_PRICE_FIELDS = ("price", "current_price", "currentPrice", "sale_price", "salePrice", "amount")
_URL_FIELDS = ("product_url", "productUrl", "url", "link", "canonical_url")
_ID_FIELDS = ("retailer_product_id", "product_id", "productId", "sku", "id", "ean", "gtin")
_AVAILABILITY_FIELDS = ("availability", "stock_status", "stockStatus", "in_stock", "inStock", "available")
_IMAGE_FIELDS = ("retailer_image_url", "image_url", "imageUrl", "image", "image_link", "imageLink")
_CURRENCY_FIELDS = ("currency", "currency_code", "currencyCode")


def _first_value(record: Mapping[str, Any], fields: tuple[str, ...]) -> Any:
    """Return the first present, non-empty value without guessing semantics."""
    for field in fields:
        if field in record:
            value = record[field]
            if value is not None and not (isinstance(value, str) and not value.strip()):
                return value
    return None


def _text(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list, tuple, set, bool)):
        return None
    result = str(value).strip()
    return result or None


def _size_ml(value: Any) -> int | None:
    """Accept only explicit numeric millilitre fields; do not parse title text."""
    number = decimal_or_none(value)
    if number is None or number <= 0 or number != number.to_integral_value():
        return None
    return int(number)


def _price(value: Any) -> Decimal | None:
    """Convert numeric prices only; locale-formatted strings remain untrusted."""
    if isinstance(value, str):
        normalized = value.strip()
        # Accept simple decimal representations, not currency symbols or thousands separators.
        if not normalized or any(char not in "0123456789.-" for char in normalized):
            return None
        value = normalized
    amount = decimal_or_none(value)
    return amount if amount is not None and amount >= 0 else None


def _http_url(value: Any) -> str | None:
    candidate = _text(value)
    if not candidate:
        return None
    try:
        parsed = urlparse(candidate)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return candidate


def _availability(value: Any) -> str | None:
    if isinstance(value, bool):
        return "in_stock" if value else "out_of_stock"
    return _text(value)


def normalize_offer(
    record: Mapping[str, Any],
    *,
    retailer: str,
    currency_default: str = "EUR",
) -> RetailerOffer:
    """Normalize one retailer record, raising ValueError when identity is absent.

    ``retailer`` is supplied by the caller and never inferred from untrusted input.
    Raw fields are retained in ``raw_payload`` for later audit and diagnostics.
    """
    if not isinstance(record, Mapping):
        raise TypeError("record must be a mapping")
    retailer_name = retailer.strip() if isinstance(retailer, str) else ""
    if not retailer_name:
        raise ValueError("retailer must be supplied explicitly")

    raw_name = _text(_first_value(record, _NAME_FIELDS))
    if not raw_name:
        raise ValueError("record has no recognized product-name field")

    brand_raw = _text(_first_value(record, _BRAND_FIELDS))
    size_ml = _size_ml(_first_value(record, _SIZE_FIELDS))
    price = _price(_first_value(record, _PRICE_FIELDS))
    product_url = _http_url(_first_value(record, _URL_FIELDS))
    retailer_product_id = _text(_first_value(record, _ID_FIELDS))
    availability = _availability(_first_value(record, _AVAILABILITY_FIELDS))
    retailer_image_url = _http_url(_first_value(record, _IMAGE_FIELDS))

    currency_value = _text(_first_value(record, _CURRENCY_FIELDS)) or currency_default
    currency = currency_value.upper()
    if len(currency) != 3 or not currency.isalpha():
        currency = currency_default.upper()
    if len(currency) != 3 or not currency.isalpha():
        raise ValueError("currency_default must be a 3-letter currency code")

    return RetailerOffer(
        retailer=retailer_name,
        raw_name=raw_name,
        product_url=product_url,
        retailer_product_id=retailer_product_id,
        brand_raw=brand_raw,
        size_ml=size_ml,
        price=price,
        currency=currency,
        availability=availability,
        retailer_image_url=retailer_image_url,
        raw_payload=dict(record),
    )


def normalize_offers(
    records: Any,
    *,
    retailer: str,
    currency_default: str = "EUR",
) -> tuple[tuple[RetailerOffer, ...], tuple[dict[str, Any], ...]]:
    """Normalize a batch and report invalid rows instead of silently dropping them.

    Returns ``(offers, rejected_rows)``. Each rejected row includes its zero-based
    index, reason, and a shallow copy of the original mapping when possible.
    """
    if isinstance(records, (str, bytes, Mapping)) or records is None:
        raise TypeError("records must be an iterable of record mappings")
    offers: list[RetailerOffer] = []
    rejected: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        try:
            offers.append(
                normalize_offer(record, retailer=retailer, currency_default=currency_default)
            )
        except (TypeError, ValueError) as exc:
            rejected.append({
                "index": index,
                "reason": str(exc),
                "record": dict(record) if isinstance(record, Mapping) else repr(record),
            })
    return tuple(offers), tuple(rejected)
