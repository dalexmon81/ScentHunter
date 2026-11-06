"""Pure identity helpers for fragrance offers."""
from __future__ import annotations

import re
import urllib.parse


def offer_concentration_token(value: object) -> str:
    """Extract an explicit fragrance concentration from title or URL text."""
    text = str(value or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    for pattern, token in (
        (r"\b(?:eau de parfum intense|edp intense|intense edp)\b", "edp_intense"),
        (r"\b(?:eau de toilette intense|edt intense|intense edt)\b", "edt_intense"),
        (r"\b(?:extrait de parfum|extrait)\b", "extrait"),
        (r"\b(?:eau de parfum|edp)\b", "edp"),
        (r"\b(?:eau de toilette|edt)\b", "edt"),
        (r"\b(?:eau de cologne|edc)\b", "edc"),
        # Elixir is more specific than the generic "parfum" URL descriptor.
        (r"\belixir\b", "elixir"),
        (r"\bparfum\b", "parfum"),
    ):
        if re.search(pattern, text):
            return token
    return ""


def is_dior_line_url_mismatch(item: object) -> bool:
    """Reject cross-line Dior Eau Sauvage / Dior Sauvage title-to-URL conflicts.

    Prefer the displayed product title and primary offer URL. Secondary/raw
    metadata can contain stale canonical labels and must not override a clear
    conflict between the visible product and its destination.
    """
    if not isinstance(item, dict):
        return False

    title = next(
        (str(item.get(key) or "").strip() for key in
         ("name", "title", "product_name", "canonical_name", "raw_name", "_raw_name")
         if str(item.get(key) or "").strip()),
        "",
    )
    url = next(
        (str(item.get(key) or "").strip() for key in
         ("url", "product_url", "link", "product_page", "source_url", "_raw_url")
         if str(item.get(key) or "").strip()),
        "",
    )
    normalize = lambda value: re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()
    title_norm = normalize(title)
    url_norm = normalize(url)

    title_is_eau_sauvage = bool(re.search(r"\beau sauvage\b", title_norm))
    url_is_eau_sauvage = bool(re.search(r"\beau sauvage\b", url_norm))
    title_is_sauvage = bool(re.search(r"\bsauvage\b", title_norm))
    url_is_sauvage = bool(re.search(r"\bsauvage\b", url_norm))

    if url_is_eau_sauvage and title_is_sauvage and not title_is_eau_sauvage:
        return True
    if title_is_eau_sauvage and url_is_sauvage and not url_is_eau_sauvage:
        return True
    return False


def is_concentration_mismatch_offer(item: object) -> bool:
    """Reject decisive product-title / destination identity conflicts."""
    if not isinstance(item, dict):
        return False
    title = " ".join(str(item.get(key) or "") for key in
                     ("name", "title", "product_name", "raw_name", "_raw_name")).strip()
    url = " ".join(str(item.get(key) or "") for key in
                   ("url", "product_url", "source_url", "product_page", "link", "_raw_url")).strip()
    title_norm = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    url_norm = re.sub(r"[^a-z0-9]+", " ", url.lower()).strip()

    title_token = offer_concentration_token(title)
    url_token = offer_concentration_token(url)
    hard_tokens = {"edt", "edp", "edc", "edt_intense", "edp_intense"}
    if title_token in hard_tokens and url_token in hard_tokens and title_token != url_token:
        return True
    if is_dior_line_url_mismatch(item):
        return True

    brand = str(item.get("canonical_brand") or item.get("brand") or item.get("manufacturer") or "").strip()
    brand_norm = re.sub(r"[^a-z0-9]+", " ", brand.lower()).strip()
    if brand_norm and len(brand_norm) >= 3 and brand_norm not in {"unknown", "perfume"}:
        url_path = urllib.parse.urlparse(url.split()[0] if url else "").path
        url_identity = re.sub(r"[^a-z0-9]+", " ", url_path.lower()).strip()
        known_brands = {
            "vertus", "french avenue", "rasasi", "dior", "afnan", "lattafa",
            "armaf", "maison alhambra", "parfums de marly", "xerjoff",
            "initio", "creed", "chanel", "versace", "gucci", "prada",
            "yves saint laurent", "givenchy", "valentino", "burberry",
            "hugo boss", "dolce gabbana", "montale", "mancera", "nishane",
        }
        for candidate in known_brands:
            if candidate != brand_norm and candidate in url_identity and brand_norm in known_brands:
                return True
    return False


def offer_url_identity(value: object) -> str:
    """Normalize a retailer listing URL while retaining commercial selectors."""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    try:
        parsed = urlsplit(str(value or "").strip())
        host = parsed.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        path = parsed.path.rstrip("/").lower()
        selectors = {
            "variant", "variant_id", "id_product_attribute",
            "combination_id", "sku", "size", "size_ml", "attribute",
        }
        query = [
            (key.lower(), val)
            for key, val in parse_qsl(parsed.query, keep_blank_values=False)
            if key.lower() in selectors
        ]
        fragment = parsed.fragment.lower()
        return urlunsplit((parsed.scheme.lower(), host, path, urlencode(sorted(query)), fragment))
    except Exception:
        return str(value or "").strip().lower()
