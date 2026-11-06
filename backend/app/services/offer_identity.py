"""Pure identity helpers for fragrance offers."""
from __future__ import annotations

import re


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

    title_is_eau_sauvage = bool(re.search(r"\\beau sauvage\\b", title_norm))
    url_is_eau_sauvage = bool(re.search(r"\\beau sauvage\\b", url_norm))
    title_is_sauvage = bool(re.search(r"\\bsauvage\\b", title_norm))
    url_is_sauvage = bool(re.search(r"\\bsauvage\\b", url_norm))

    if url_is_eau_sauvage and title_is_sauvage and not title_is_eau_sauvage:
        return True
    if title_is_eau_sauvage and url_is_sauvage and not url_is_eau_sauvage:
        return True
    return False
