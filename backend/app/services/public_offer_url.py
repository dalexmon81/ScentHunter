"""Public retailer URL normalization for published offers."""
import re


def public_offer_url(item):
    """Return a Sabina URL that opens the Spanish storefront and the offer's
    actual size variant.

    Sabina product pages encode the selected size in the URL fragment. The
    catalog may contain Italian canonical URLs or stale fragments in another
    locale. Sabina's Spanish page does not honour those fragments, so it would
    fall back to its default variant. Always normalize the URL to /es/ and
    regenerate the Spanish fragment from the offer's size.
    """
    raw_url = item.get("variant_url") or item.get("url") or item.get("product_url")
    url = str(raw_url or "").strip()
    if not url:
        return raw_url

    store = str(item.get("store") or item.get("shop") or "").strip().lower()
    host = ""
    try:
        from urllib.parse import urlsplit, urlunsplit
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
    except Exception:
        return url

    # Deloox links in the catalog can be stored from a different locale
    # (including .es URLs returned by redirects). ScentHunter serves the
    # Luxembourg/Benelux storefront through Deloox Belgium; keep the original
    # product path and query, but normalize the host to the supported .be
    # storefront so the public offer never opens the Spanish shop.
    if store in {"deloox", "deloox.be", "deloox.nl", "deloox.es", "deloox.com"} or host.endswith("deloox.es") or host.endswith("deloox.nl") or host.endswith("deloox.com") or host.endswith("deloox.be"):
        from urllib.parse import urlsplit, urlunsplit
        if host.endswith("deloox.es") or host.endswith("deloox.nl") or host.endswith("deloox.com") or host.endswith("deloox.be"):
            parsed = parsed._replace(netloc="www.deloox.be")
            return urlunsplit((parsed.scheme or "https", parsed.netloc, parsed.path, parsed.query, parsed.fragment))
        return url

    if store not in {"sabina", "sabina.com"} and not host.endswith("sabina.com"):
        return url

    # Prefer the explicit displayed format when it contains a recognized
    # volume. Some catalog rows have stale/mismatched size_ml values.
    format_value = item.get("format")
    format_match = re.search(
        r"(?<!\d)(30|50|75|100|150|200)\s*(?:ml|мл)?\b",
        str(format_value or ""),
        re.I,
    )
    size = format_value if format_match else item.get("size_ml")
    if size is None or str(size).strip() == "":
        size = format_value
    match = re.search(r"(?<!\d)(30|50|75|100|150|200)\s*(?:ml|мл)?", str(size or ""), re.I)
    if not match:
        try:
            numeric_size = float(size)
            if numeric_size not in {30, 50, 75, 100, 150, 200}:
                return url
            size_ml = int(numeric_size)
        except (TypeError, ValueError):
            return url
    else:
        size_ml = int(match.group(1))

    # Always open the Spanish storefront. Replace only the locale segment;
    # Sabina resolves the canonical Spanish product path from the product ID.
    if "/es/" not in parsed.path.lower():
        parsed = parsed._replace(
            path=re.sub(
                r"^/(?:it|fr|en|de|nl|pt|tw|da|pl)/",
                "/es/",
                parsed.path,
                count=1,
            )
        )

    # Do not invent a fragment from size alone. Preserve Sabina's actual
    # combination ID only when the volume encoded in that selector agrees with
    # the offer's resolved volume. A stale/mismatched fragment silently opens
    # another size (often the default 30 ml), so strip it rather than mislabel it.
    fragment_match = re.search(
        r"(?:^|/)\d+-tama_o-(\d+(?:_\d+)?)_ml$",
        parsed.fragment, re.I,
    )
    if not fragment_match:
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
    try:
        fragment_size = float(fragment_match.group(1).replace("_", "."))
    except (TypeError, ValueError):
        fragment_size = None
    if fragment_size is None or abs(fragment_size - size_ml) >= 0.01:
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))

    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.query, parsed.fragment)
    )
