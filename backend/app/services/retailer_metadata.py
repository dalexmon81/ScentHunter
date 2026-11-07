"""Generic cleanup for retailer metadata nested in offer payloads."""


def clean_retailer_brand_metadata(value, normalized_store_label):
    """Clear nested brand fields that merely repeat the retailer's own label.

    The input is copied recursively; unrelated values and container types are
    preserved so callers can retain the original source payload.
    """
    if isinstance(value, dict):
        cleaned = dict(value)
        for key in ("source_brand", "brand", "manufacturer"):
            current = str(cleaned.get(key) or "").strip()
            if current:
                normalized_current = "".join(
                    current.lower().replace("-", " ").split()
                )
                if normalized_current == normalized_store_label:
                    cleaned[key] = ""
        for key, nested in list(cleaned.items()):
            if isinstance(nested, (dict, list, tuple)):
                cleaned[key] = clean_retailer_brand_metadata(
                    nested, normalized_store_label
                )
        return cleaned
    if isinstance(value, list):
        return [
            clean_retailer_brand_metadata(item, normalized_store_label)
            for item in value
        ]
    if isinstance(value, tuple):
        return tuple(
            clean_retailer_brand_metadata(item, normalized_store_label)
            for item in value
        )
    return value
