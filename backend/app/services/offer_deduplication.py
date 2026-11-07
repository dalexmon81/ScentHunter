"""Deduplication for normalized retailer offer rows."""

import re


def dedupe_offer_results(results, diagnostics=None, *, normalize_store, safe_float, result_identity):
    """Remove duplicate offers using URL identity and retailer-specific fallbacks."""
    seen = {}
    output = []

    def fingerprint(item):
        store = normalize_store(item.get("store") or item.get("shop"), "")
        if store not in {"easycosmetic", "sabina"}:
            return None
        name = " ".join(str(item.get("name") or item.get("canonical_name") or item.get("title") or "").lower().split())
        name = re.sub(r"[^a-z0-9]+", " ", name).strip()
        size = safe_float(item.get("size_ml"))
        price = safe_float(item.get("price_num") if item.get("price_num") not in (None, "") else item.get("price"))
        variant = str(item.get("variant_id") or item.get("variant_key") or item.get("variant_sku") or "").strip().lower()
        if price is None:
            return None
        if store == "easycosmetic":
            return ("offer-fingerprint", store, round(price, 2))
        if not name or size is None:
            return None
        return ("offer-fingerprint", store, name, round(size, 3), round(price, 2), variant)

    for index, item in enumerate(results):
        key = result_identity(item)
        fp = fingerprint(item)
        keeper_entry = seen.get(key) or (seen.get(fp) if fp is not None else None)
        if keeper_entry is None:
            entry = {"index": index, "item": item}
            seen[key] = entry
            if fp is not None:
                seen.setdefault(fp, entry)
            output.append(item)
            continue

        if diagnostics is not None:
            keeper = keeper_entry["item"]
            diagnostics.append({
                "action": "DROP",
                "reason": "same_store_name_size_price" if fp is not None and fp in seen and key not in seen else "duplicate_dedupe_key",
                "dedupe_key": [key[0], key[1], key[2]],
                "dropped": {
                    "store": item.get("store") or item.get("shop"),
                    "url": item.get("url") or item.get("product_url"),
                    "product_id": item.get("store_product_id") or item.get("product_id") or item.get("sku"),
                    "sku": item.get("sku"),
                    "name": item.get("name") or item.get("title"),
                    "size_ml": item.get("size_ml"),
                    "price": item.get("price"),
                    "price_num": item.get("price_num"),
                    "catalog_id": item.get("catalog_id"),
                    "canonical_name": item.get("canonical_name"),
                    "raw_name": item.get("_raw_name"),
                },
                "kept": {
                    "store": keeper.get("store") or keeper.get("shop"),
                    "url": keeper.get("url") or keeper.get("product_url"),
                    "product_id": keeper.get("store_product_id") or keeper.get("product_id") or keeper.get("sku"),
                    "sku": keeper.get("sku"),
                    "name": keeper.get("name") or keeper.get("title"),
                    "size_ml": keeper.get("size_ml"),
                    "price": keeper.get("price"),
                    "price_num": keeper.get("price_num"),
                    "catalog_id": keeper.get("catalog_id"),
                    "canonical_name": keeper.get("canonical_name"),
                    "raw_name": keeper.get("_raw_name"),
                },
            })
    return output
