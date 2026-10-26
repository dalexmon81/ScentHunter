"""Amazon Creators API client for approved Amazon Associates integrations.

This client is disabled unless credentials and a marketplace-specific Partner
Tag are configured. It uses Amazon's documented OAuth 2.0 flow and SearchItems
operation; it never falls back to challenge evasion or private endpoints.
"""
from __future__ import annotations

import os
import threading
import time
from urllib.parse import urlparse

import requests

API_BASE = "https://creatorsapi.amazon"
DEFAULT_TOKEN_URL = "https://api.amazon.co.uk/auth/o2/token"
TIMEOUT = (3.0, 8.0)
MAX_RESULTS = 10

_TOKEN_LOCK = threading.Lock()
_TOKEN_CACHE = {"client_id": None, "access_token": None, "expires_at": 0.0}


def _env(name: str) -> str:
    return str(os.environ.get(name, "") or "").strip()


def _marketplace(market: str) -> tuple[str, str]:
    if market == "fr":
        return "www.amazon.fr", "AMAZON_ASSOCIATE_TAG_FR"
    if market == "de":
        return "www.amazon.de", "AMAZON_ASSOCIATE_TAG_DE"
    raise ValueError("unsupported_amazon_marketplace")


def is_configured(market: str) -> bool:
    try:
        _, tag_name = _marketplace(market)
    except ValueError:
        return False
    return bool(
        _env("AMAZON_CREATORS_API_CLIENT_ID")
        and _env("AMAZON_CREATORS_API_CLIENT_SECRET")
        and _env(tag_name)
    )


def _failure(status: str, error: str, market: str, http_status: int | None = None):
    details = {"market": market, "source": "amazon_creators_api"}
    if http_status is not None:
        details["http_status"] = http_status
    return {
        "status": status,
        "verified": False,
        "results": [],
        "error": error,
        "details": details,
    }


def _access_token() -> str:
    client_id = _env("AMAZON_CREATORS_API_CLIENT_ID")
    client_secret = _env("AMAZON_CREATORS_API_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("amazon_creators_api_not_configured")

    now = time.monotonic()
    with _TOKEN_LOCK:
        if (
            _TOKEN_CACHE["client_id"] == client_id
            and _TOKEN_CACHE["access_token"]
            and _TOKEN_CACHE["expires_at"] > now + 60
        ):
            return str(_TOKEN_CACHE["access_token"])

        token_url = _env("AMAZON_CREATORS_API_TOKEN_URL") or DEFAULT_TOKEN_URL
        parsed = urlparse(token_url)
        if parsed.scheme != "https" or parsed.hostname not in {
            "api.amazon.co.uk", "api.amazon.com", "api.amazon.co.jp"
        }:
            raise RuntimeError("amazon_creators_api_invalid_token_endpoint")

        response = requests.post(
            token_url,
            json={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": "creatorsapi::default",
            },
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=TIMEOUT,
        )
        try:
            if response.status_code >= 400:
                raise _ApiHttpError(response.status_code)
            payload = response.json()
        finally:
            response.close()

        token = str(payload.get("access_token") or "").strip()
        if not token:
            raise RuntimeError("amazon_creators_api_token_missing")
        try:
            expires_in = max(60, int(payload.get("expires_in") or 3600))
        except (TypeError, ValueError):
            expires_in = 3600
        _TOKEN_CACHE.update({
            "client_id": client_id,
            "access_token": token,
            "expires_at": time.monotonic() + expires_in,
        })
        return token


class _ApiHttpError(RuntimeError):
    def __init__(self, status_code: int):
        super().__init__(f"amazon_creators_api_http_{status_code}")
        self.status_code = status_code


def _text(value) -> str:
    return str(value or "").strip()


def _display(item: dict, *path: str) -> str:
    current = item
    for key in path:
        if not isinstance(current, dict):
            return ""
        current = current.get(key)
    if isinstance(current, dict):
        return _text(current.get("displayValue"))
    return _text(current)


def _price_and_currency(item: dict):
    offers = item.get("offersV2")
    listings = offers.get("listings") if isinstance(offers, dict) else []
    if not isinstance(listings, list):
        return None, None, None
    for listing in listings:
        if not isinstance(listing, dict):
            continue
        price = listing.get("price")
        money = price.get("money") if isinstance(price, dict) else None
        if not isinstance(money, dict):
            continue
        try:
            amount = float(money.get("amount"))
        except (TypeError, ValueError):
            continue
        currency = _text(money.get("currency"))
        if amount > 0 and currency:
            availability = listing.get("availability")
            available = availability.get("type") if isinstance(availability, dict) else None
            return round(amount, 2), currency, available
    return None, None, None


def _safe_product_url(raw: str, marketplace: str, asin: str) -> str | None:
    base = "https://" + marketplace
    if raw:
        parsed = urlparse(raw)
        if parsed.scheme == "https" and parsed.hostname == marketplace:
            return raw
    if asin and len(asin) == 10 and asin.isalnum():
        return f"{base}/dp/{asin.upper()}"
    return None


def search_marketplace(
    query: str,
    market: str,
    store_key: str,
    size_parser,
    concentration_parser,
) -> dict:
    query = str(query or "").strip()
    if not query:
        return {"status": "success", "verified": True, "results": [], "error": None,
                "details": {"empty_query": True, "source": "amazon_creators_api"}}
    try:
        marketplace, tag_name = _marketplace(market)
    except ValueError:
        return _failure("unavailable", "amazon_creators_api_unsupported_market", market)

    if not is_configured(market):
        return _failure("unavailable", "amazon_creators_api_not_configured", market)

    response = None
    try:
        token = _access_token()
        response = requests.post(
            API_BASE + "/catalog/v1/searchItems",
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "x-marketplace": marketplace,
            },
            json={
                "keywords": query,
                "marketplace": marketplace,
                "partnerTag": _env(tag_name),
                "searchIndex": "All",
                "itemCount": MAX_RESULTS,
                "resources": [
                    "images.primary.medium",
                    "itemInfo.title",
                    "itemInfo.byLineInfo",
                    "offersV2.listings.price",
                    "offersV2.listings.availability",
                ],
            },
            timeout=TIMEOUT,
        )
        if response.status_code in (401, 403):
            return _failure("blocked", "amazon_creators_api_access_denied", market, response.status_code)
        if response.status_code == 429:
            return _failure("unavailable", "amazon_creators_api_rate_limited", market, 429)
        if response.status_code >= 400:
            return _failure("unavailable", "amazon_creators_api_http_error", market, response.status_code)
        payload = response.json()
        search_result = payload.get("searchResult") if isinstance(payload, dict) else None
        items = search_result.get("items") if isinstance(search_result, dict) else []
        if not isinstance(items, list):
            items = []

        results = []
        seen = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            title = _display(item, "itemInfo", "title")
            asin = _text(item.get("asin")).upper()
            url = _safe_product_url(_text(item.get("detailPageURL")), marketplace, asin)
            price, currency, available = _price_and_currency(item)
            if not title or not url or price is None or currency != "EUR" or url in seen:
                continue
            seen.add(url)
            image_data = item.get("images")
            primary = image_data.get("primary") if isinstance(image_data, dict) else {}
            image_node = primary.get("medium") if isinstance(primary, dict) else {}
            image = _text(image_node.get("url")) if isinstance(image_node, dict) else ""
            brand = _display(item, "itemInfo", "byLineInfo", "brand")
            results.append({
                "shop": "Amazon.fr" if market == "fr" else "Amazon.de",
                "store": store_key,
                "brand": brand,
                "name": title,
                "price": f"{price:.2f} €",
                "price_num": price,
                "currency": currency,
                "available": available == "IN_STOCK" if available else None,
                "availability": available or None,
                "image": image or None,
                "size_ml": size_parser(title),
                "concentration": concentration_parser(title),
                "url": url,
            })
        return {
            "status": "success",
            "verified": True,
            "results": results,
            "error": None,
            "details": {
                "market": market,
                "candidate_count": len(results),
                "source": "amazon_creators_api",
                "total_result_count": search_result.get("totalResultCount") if isinstance(search_result, dict) else None,
            },
        }
    except _ApiHttpError as exc:
        return _failure("unavailable", "amazon_creators_api_token_http_error", market, exc.status_code)
    except requests.Timeout:
        return _failure("timeout", "amazon_creators_api_timeout", market)
    except requests.RequestException as exc:
        return _failure("unavailable", f"amazon_creators_api_request_error:{type(exc).__name__}", market)
    except (ValueError, TypeError, RuntimeError) as exc:
        return _failure("unavailable", str(exc) if str(exc).startswith("amazon_creators_api_") else "amazon_creators_api_invalid_response", market)
    finally:
        if response is not None:
            response.close()
