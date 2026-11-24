"""Pure validation of Notino product URLs and CJ affiliate redirects.

This module has no network, feed, database or scraper dependencies. It is safe
for the read-only catalog search layer to use when displaying affiliate links.
"""
from __future__ import annotations

import re
import urllib.parse

MARKET_HOST = "www.notino.fr"

CJ_TRACKING_HOSTS = frozenset({
    "anrdoezrs.net", "www.anrdoezrs.net",
    "dpbolvw.net", "www.dpbolvw.net",
    "jdoqocy.com", "www.jdoqocy.com",
    "kqzyfj.com", "www.kqzyfj.com",
    "tkqlhce.com", "www.tkqlhce.com",
})
CJ_CLICK_PATH = re.compile(r"^/click-\d+-\d+/?$", re.I)


def _canonical_notino_product_url(raw: str) -> str | None:
    try:
        parsed = urllib.parse.urlparse(str(raw or "").strip())
        host = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or host not in {"notino.fr", "www.notino.fr"}
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
    ):
        return None
    path = re.sub(r"/{2,}", "/", parsed.path or "")
    first_segment = (path.strip("/").split("/", 1)[0] or "").casefold()
    reserved_segments = {
        "search", "parfums", "marques", "login", "account", "cart",
        "checkout", "customer-service", "wishlist",
    }
    # Match complete reserved route segments only. Prefix matching wrongly
    # rejects legitimate brand slugs such as "parfums-de-marly" and "carthusia".
    if not path or path == "/" or first_segment in reserved_segments:
        return None
    return urllib.parse.urlunparse(("https", MARKET_HOST, path, "", "", ""))


def _cj_affiliate_link(raw: str) -> tuple[str, str] | None:
    """Validate an allowlisted CJ click URL and return its Notino target."""
    click_url = str(raw or "").strip()
    try:
        parsed = urllib.parse.urlparse(click_url)
        host = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or host not in CJ_TRACKING_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or not CJ_CLICK_PATH.fullmatch(parsed.path or "")
        or parsed.params
        or parsed.fragment
        or ";" in parsed.query
        or re.search(r"%(?![0-9a-fA-F]{2})|[\x00-\x20\x7f]", click_url)
    ):
        return None
    try:
        params = urllib.parse.parse_qsl(
            parsed.query, keep_blank_values=True, strict_parsing=True, errors="strict"
        )
    except (ValueError, UnicodeDecodeError):
        return None
    if any(not re.fullmatch(r"[a-zA-Z0-9_.~-]+", key) for key, _value in params):
        return None
    if len(params) != 1 or params[0][0].lower() != "url":
        return None
    target = _canonical_notino_product_url(params[0][1])
    if not target:
        return None
    return click_url, target


def validated_cj_offer_url(raw: str, product_url: str) -> str | None:
    """Accept a CJ click only when its destination is the stored product."""
    try:
        affiliate = _cj_affiliate_link(raw)
        product = _canonical_notino_product_url(product_url)
        if not affiliate or not product or affiliate[1] != product:
            return None
        destination = next(
            value for key, value in urllib.parse.parse_qsl(
                urllib.parse.urlparse(affiliate[0]).query, keep_blank_values=True
            ) if key.lower() == "url"
        )
        parsed = urllib.parse.urlparse(destination)
        path = urllib.parse.unquote(parsed.path, errors="strict")
        # Do not let server-side path normalization or redirect parameters
        # turn a matching catalog path into a different destination.
        if (
            parsed.params or parsed.fragment
            or re.search(r"%(?![0-9a-fA-F]{2})|%2f|%5c|%25", parsed.path, re.I)
            or re.search(r"[\x00-\x20\x7f\\;?#]", path)
            or re.search(r"[\x00-\x20\x7f]", destination)
            or "//" in path
            or any(segment in {".", ".."} for segment in path.split("/"))
        ):
            return None
        if parsed.query:
            query = urllib.parse.parse_qsl(
                parsed.query, keep_blank_values=True, strict_parsing=True, errors="strict"
            )
            if re.search(r"%(?![0-9a-fA-F]{2})|[\x00-\x20\x7f]", parsed.query) or any(
                key.lower() not in {
                    "utm_source", "utm_medium", "utm_campaign", "utm_term",
                    "utm_content", "utm_id",
                } for key, _value in query
            ):
                return None
        return affiliate[0]
    except (ValueError, UnicodeDecodeError):
        return None
