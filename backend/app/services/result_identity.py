"""Retailer offer identity and variant-aware deduplication key."""
import re


def result_key(item, normalize_store, safe_float, url_identity):
    """Return a retailer-offer identity without collapsing distinct variants.

    The canonical catalog ID identifies the fragrance, not necessarily the
    retailer's sellable variant. Size is the strongest generic discriminator;
    when size is missing, preserve any explicit variant identity supplied by
    the catalog/scraper, then fall back to a variant selector in the URL.
    """
    store = normalize_store(item.get('store') or item.get('shop'), '')
    catalog_id = str(item.get('catalog_id') or '').strip().lower()
    raw_url = str(item.get('url') or item.get('variant_url') or item.get('product_url') or '').strip()
    product_url = str(item.get('product_url') or item.get('url') or '').strip()
    url = raw_url.lower()

    product_id = str(item.get('store_product_id') or item.get('product_id') or '').strip().lower()
    sku = str(item.get('sku') or '').strip().lower()
    name = ' '.join(str(item.get('name') or item.get('title') or '').split()).lower()
    size = safe_float(item.get('size_ml'))
    # A retailer product URL is the strongest cross-catalog identity for the same offer.
    # Catalog IDs can differ when the same retailer listing is linked to duplicate
    # canonical records. Explicit size and variant selectors below still keep
    # genuinely distinct sellable variants separate.
    identity_key = url_identity(product_url) or catalog_id or product_id or sku or name

    # Preserve commercial variant identity even when size is known. Size alone
    # is not sufficient: retailers can expose multiple sellable combinations
    # with the same volume, and their selector URLs must not be merged.
    variant_identity = next((str(item.get(field) or '').strip().lower()
                             for field in ('variant_key', 'variant_id', 'variant_sku')
                             if str(item.get(field) or '').strip()), '')
    if not variant_identity and url:
        # Keep explicit query selectors and selector-like fragments, while
        # ignoring ordinary page anchors and unrelated tracking parameters.
        query_match = re.search(
            r'(?:[?&])(?:variant|variant_id|id_product_attribute|combination_id)=([^&#]+)',
            url, flags=re.I,
        )
        fragment = url.split('#', 1)[1] if '#' in url else ''
        fragment = fragment.strip('/')
        if query_match:
            variant_identity = f'url-selector:{query_match.group(1)}'
        elif fragment and re.search(
            r'\d+.*(?:size|tama|ml|variant|attribute|combination)|'
            r'(?:size|tama|ml|variant|attribute|combination).*\d+',
            fragment, re.I,
        ):
            variant_identity = f'url-fragment:{fragment}'
    if not variant_identity and size is None and sku:
        variant_identity = f'sku:{sku}'
    if variant_identity:
        identity_key = f'{identity_key}|{variant_identity}'

    return (store, identity_key, round(size, 3) if size is not None else '')
