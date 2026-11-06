"""Stable public offer response projection."""


def public_offer(item, url_builder):
    """
    Return only commercial retailer data.
    """
    canonical_name = item.get("canonical_name") or item.get("name") or item.get("title")
    # Canonical identity must win over retailer/source brand metadata.
    # The matcher resolves canonical_brand separately from the retailer's
    # raw brand; using item["brand"] first caused inconsistent display.
    canonical_brand = (
        item.get("canonical_brand")
        or item.get("brand")
        or item.get("manufacturer")
    )

    return {
        # Canonical identity is deliberately repeated on every public offer.
        # The frontend can therefore flatten offers without losing the product
        # identity that the central matcher already resolved.
        "catalog_id": item.get("catalog_id"),
        "brand": canonical_brand,
        "name": canonical_name,
        "canonical_name": item.get("canonical_name") or canonical_name,
        "family": item.get("family"),
        "variant": item.get("variant"),
        "store": item.get("store"),
        "shop": item.get("shop"),
        "price": item.get("price"),
        "price_num": item.get("price_num"),
        "format": item.get("format"),
        "size_ml": item.get("size_ml"),
        "variant_id": item.get("variant_id"),
        "url": url_builder(item),
        "retailer_image": item.get("image") or item.get("image_url"),
        # Preserve the scraper's explicit availability signal in the public
        # offer contract. Previously only `available` survived aggregation,
        # so structured values such as `OutOfStock` could be lost before the
        # frontend rendered the offer. No retailer-specific rule is applied.
        "available": item.get("available"),
        "availability": item.get("availability"),
        "stock": item.get("stock"),
        "stock_status": item.get("stock_status"),
        "availability_status": item.get("availability_status"),
        "in_stock": item.get("in_stock"),
        "inStock": item.get("inStock"),
        "status": item.get("status"),
        "raw_name": item.get("_raw_name")
            or item.get("name")
            or item.get("title"),
        "raw_brand": item.get("_raw_brand")
            or item.get("brand")
            or item.get("manufacturer"),
    }
