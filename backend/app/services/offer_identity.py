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
