"""Validation for Notino CJ affiliate clickout URLs."""
from __future__ import annotations

from urllib.parse import parse_qs, urlsplit


_CJ_HOSTS = {
    "www.anrdoezrs.net", "www.dpbolvw.net", "www.jdoqocy.com",
    "www.kqzyfj.com", "www.tkqlhce.com",
}


def is_valid_notino_affiliate_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        destinations = parse_qs(parsed.query).get("url", [])
        if (
            parsed.scheme != "https" or parsed.hostname not in _CJ_HOSTS
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or not parsed.path.startswith("/click-") or len(destinations) != 1
        ):
            return False
        destination = urlsplit(destinations[0])
        return (
            destination.scheme == "https"
            and destination.hostname in {"notino.fr", "www.notino.fr"}
            and not destination.username and not destination.password
            and destination.port in (None, 443)
            and bool(__import__("re").search(r"/p-\d+/?$", destination.path))
        )
    except ValueError:
        return False
