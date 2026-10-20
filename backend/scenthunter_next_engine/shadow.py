"""Pure comparison helpers for legacy-vs-next search shadow runs."""
from __future__ import annotations
import hashlib
import json
import re
import unicodedata
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable


def _fold(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).split())


def _canonical_name(value: Any) -> str:
    name = str(value or "")
    name = re.sub(r"(?<!\d)\d+(?:[.,]\d+)?\s*(?:ml|cl|oz)\b", " ", name, flags=re.I)
    name = re.sub(r"\b(?:eau\s+de\s+parfum|eau\s+de\s+toilette|eau\s+de\s+cologne|edp|edt|edc|extrait(?:\s+de\s+parfum)?)\b", " ", name, flags=re.I)
    return _fold(name)


def _stable_key(row: dict[str, Any]) -> str:
    offer = row.get("offer") if isinstance(row.get("offer"), dict) else row
    variant = row.get("variant") if isinstance(row.get("variant"), dict) else {}
    store = _fold(offer.get("store") or row.get("store"))
    brand = _fold(row.get("brand"))
    name = _canonical_name(row.get("name") or row.get("canonical_name"))
    size = _fold(variant.get("size_ml") or row.get("size_ml"))
    concentration = _fold(variant.get("concentration") or row.get("concentration"))
    material = json.dumps([store, brand, name, size, concentration], separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _price_minor(row: dict[str, Any]) -> int | None:
    value = row.get("price_minor")
    if value is not None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    value = row.get("price")
    if value is None:
        return None
    try:
        amount = Decimal(str(value).strip().replace(",", ".").replace("€", "").strip())
        if not amount.is_finite() or amount <= 0:
            return None
        return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return None


def compare_search_results(legacy_rows: Iterable[dict[str, Any]], next_rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Compare coverage and commercial values without mutating either system.

    Prices are compared only when both rows expose the same currency. Missing
    matches remain explicit; fuzzy title similarity is intentionally excluded.
    """
    def index(rows):
        output = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            output.setdefault(_stable_key(row), row)
        return output

    legacy = index(legacy_rows)
    newer = index(next_rows)
    shared = legacy.keys() & newer.keys()
    price_differences = []
    currency_mismatches = []
    url_differences = []
    for key in sorted(shared):
        left = legacy[key].get("offer") if isinstance(legacy[key].get("offer"), dict) else legacy[key]
        right = newer[key].get("offer") if isinstance(newer[key].get("offer"), dict) else newer[key]
        lc = _fold(left.get("currency")).upper()
        rc = _fold(right.get("currency")).upper()
        if lc != rc:
            currency_mismatches.append(key)
            continue
        legacy_url = str(left.get("url") or left.get("product_url") or "")
        next_url = str(right.get("url") or right.get("product_url") or "")
        if legacy_url and next_url and legacy_url != next_url:
            url_differences.append({"key": key, "legacy_url": legacy_url, "next_url": next_url})
        lp = _price_minor(left)
        rp = _price_minor(right)
        if lp is not None and rp is not None and lp != rp:
            price_differences.append({"key": key, "legacy_price_minor": lp, "next_price_minor": rp, "currency": lc})

    return {
        "legacy_count": len(legacy),
        "next_count": len(newer),
        "matched_count": len(shared),
        "legacy_only_count": len(legacy.keys() - newer.keys()),
        "next_only_count": len(newer.keys() - legacy.keys()),
        "currency_mismatch_count": len(currency_mismatches),
        "price_difference_count": len(price_differences),
        "url_difference_count": len(url_differences),
        "price_differences": price_differences[:100],
        "url_differences": url_differences[:100],
        "currency_mismatch_keys": currency_mismatches[:100],
    }
