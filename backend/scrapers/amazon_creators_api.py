"""Amazon Creators API client for approved Amazon Associates integrations.

This client is disabled unless credentials and a marketplace-specific Partner
Tag are configured. It uses Amazon's documented OAuth 2.0 flow and SearchItems
operation; it never falls back to challenge evasion or private endpoints.
"""
from __future__ import annotations

import os
import re
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


def _configuration_error(market: str) -> str:
    try:
        _, tag_name = _marketplace(market)
    except ValueError:
        return "amazon_creators_api_unsupported_market"
    if _env("AMAZON_CREATORS_API_COMPARISON_APPROVED").lower() not in {"1", "true", "yes"}:
        return "amazon_creators_api_comparison_not_approved"
    if not (
        _env("AMAZON_CREATORS_API_CLIENT_ID")
        and _env("AMAZON_CREATORS_API_CLIENT_SECRET")
        and _env(tag_name)
    ):
        return "amazon_creators_api_not_configured"
    return ""


def is_configured(market: str) -> bool:
    """Require credentials and explicit prior approval for price comparison."""
    return not _configuration_error(market)


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


def _normalised_tokens(value: str) -> list[str]:
    import unicodedata
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return [token for token in re.findall(r"[a-z0-9]+", text.lower()) if len(token) > 1]


def _query_matches_title(query: str, title: str) -> bool:
    wanted = _normalised_tokens(query)
    available = set(_normalised_tokens(title))
    return bool(wanted) and all(token in available for token in wanted)


def _requested_size(query: str, size_parser):
    try:
        return size_parser(query)
    except Exception:
        return None


def _matches_size(query: str, title: str, size_parser) -> bool:
    wanted = _requested_size(query, size_parser)
    if wanted is None:
        return True
    offered = _requested_size(title, size_parser)
    return offered is not None and abs(float(offered) - float(wanted)) < 0.01


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
    # Amazon supplies the product URL, including any affiliate attribution.
    # Validate the destination but do not rewrite or strip query parameters:
    # the API-provided link must remain intact for attribution and compliance.
    if not raw or not asin or len(asin) != 10 or not asin.isalnum():
        return None
    parsed = urlparse(raw)
    if (
        parsed.scheme != "https"
        or parsed.hostname != marketplace
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
    ):
        return None
    path_parts = [part for part in parsed.path.split("/") if part]
    asin_upper = asin.upper()
    valid_path = (
        len(path_parts) == 2 and path_parts[0] == "dp" and path_parts[1].upper() == asin_upper
    ) or (
        len(path_parts) == 3 and path_parts[0] == "gp"
        and path_parts[1] == "product" and path_parts[2].upper() == asin_upper
    )
    return raw if valid_path else None


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

    configuration_error = _configuration_error(market)
    if configuration_error:
        return _failure("unavailable", configuration_error, market)

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
            if (
                not title or not url or price is None or currency != "EUR"
                or url in seen
                or not _query_matches_title(query, title)
                or not _matches_size(query, title, size_parser)
                or available not in {"IN_STOCK", "LIMITED_AVAILABILITY", "PREORDER"}
            ):
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



def discover_product_urls(market: str, max_queries: int = 4) -> dict:
    """Discover canonical ASIN URLs through the approved catalog API only."""
    try:
        marketplace, tag_name = _marketplace(market)
    except ValueError:
        return {"status": "unavailable", "error": "amazon_creators_api_unsupported_market", "urls": []}
    configuration_error = _configuration_error(market)
    if configuration_error:
        return {"status": "unavailable", "error": configuration_error, "urls": []}

    queries = ("parfum", "eau de parfum", "eau de toilette", "extrait de parfum")[:max(1, min(4, int(max_queries)))]
    urls = set()
    errors = []
    for query in queries:
        response = None
        try:
            response = requests.post(
                API_BASE + "/catalog/v1/searchItems",
                headers={
                    "Authorization": "Bearer " + _access_token(),
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "x-marketplace": marketplace,
                },
                json={
                    "keywords": query,
                    "marketplace": marketplace,
                    "partnerTag": _env(tag_name),
                    "searchIndex": "All",
                    "itemCount": 10,
                    "resources": ["itemInfo.title"],
                },
                timeout=TIMEOUT,
            )
            if response.status_code >= 400:
                errors.append(f"{query}:http_{response.status_code}")
                continue
            payload = response.json()
            result = payload.get("searchResult") if isinstance(payload, dict) else None
            items = result.get("items") if isinstance(result, dict) else []
            for item in items if isinstance(items, list) else []:
                if not isinstance(item, dict):
                    continue
                title = _display(item, "itemInfo", "title")
                if not title or not _query_matches_title(query, title):
                    continue
                asin = _text(item.get("asin")).upper()
                raw_url = _text(item.get("detailPageURL"))
                url = _safe_product_url(raw_url, marketplace, asin)
                if url:
                    # Persist canonical product identity only, not API payloads
                    # or prices. Current prices are fetched during background
                    # hydration through GetItems.
                    urls.add(f"https://{marketplace}/dp/{asin}")
        except requests.Timeout:
            errors.append(f"{query}:timeout")
        except (requests.RequestException, ValueError, TypeError) as exc:
            errors.append(f"{query}:{type(exc).__name__}")
        finally:
            if response is not None:
                response.close()
    return {
        "status": "success" if urls else "unavailable",
        "urls": sorted(urls),
        "queries": len(queries),
        "error": ";".join(errors[:4]) or None,
        "market": market,
        "source": "amazon_creators_api",
    }


def get_product(market: str, asin: str, size_parser, concentration_parser) -> dict | None:
    """Hydrate one ASIN using GetItems; never scrape the Amazon product page."""
    try:
        marketplace, tag_name = _marketplace(market)
    except ValueError:
        return None
    asin = _text(asin).upper()
    if _configuration_error(market) or not (len(asin) == 10 and asin.isalnum()):
        return None

    response = None
    try:
        response = requests.post(
            API_BASE + "/catalog/v1/getItems",
            headers={
                "Authorization": "Bearer " + _access_token(),
                "Content-Type": "application/json",
                "Accept": "application/json",
                "x-marketplace": marketplace,
            },
            json={
                "itemIds": [asin],
                "itemIdType": "ASIN",
                "marketplace": marketplace,
                "partnerTag": _env(tag_name),
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
        if response.status_code >= 400:
            raise _ApiHttpError(response.status_code)
        payload = response.json()
        result = payload.get("itemsResult") if isinstance(payload, dict) else None
        items = result.get("items") if isinstance(result, dict) else []
        if not isinstance(items, list) or not items:
            return None
        item = items[0]
        if not isinstance(item, dict):
            return None
        title = _display(item, "itemInfo", "title")
        price, currency, availability = _price_and_currency(item)
        if (
            not title or price is None or currency != "EUR"
            or availability not in {"IN_STOCK", "LIMITED_AVAILABILITY", "PREORDER"}
        ):
            # Never publish a product without a current, priced, buyable offer.
            # An out-of-stock or unknown-availability listing is not an offer.
            return None
        url = _safe_product_url(_text(item.get("detailPageURL")), marketplace, asin)
        if not url:
            return None
        image_data = item.get("images")
        primary = image_data.get("primary") if isinstance(image_data, dict) else {}
        image_node = primary.get("medium") if isinstance(primary, dict) else {}
        image = _text(image_node.get("url")) if isinstance(image_node, dict) else ""
        brand = _display(item, "itemInfo", "byLineInfo", "brand")
        return {
            "store": "Amazon.fr" if market == "fr" else "Amazon.de",
            "store_key": f"amazon_{market}",
            "url": url,
            "name": title,
            "brand": brand,
            "image": image or None,
            "sku": asin,
            "gtin": "",
            "mpn": "",
            "size_ml": size_parser(title),
            "concentration": concentration_parser(title),
            "gender": None,
            "price_num": price,
            "price": price,
            "currency": currency,
            "availability": "in_stock" if availability == "IN_STOCK" else "out_of_stock" if availability == "OUT_OF_STOCK" else "unknown",
            "available": True if availability == "IN_STOCK" else False if availability == "OUT_OF_STOCK" else None,
            "fetched_at": time.time(),
            "source": "amazon_creators_api",
        }
    except _ApiHttpError as exc:
        raise RuntimeError(f"amazon_creators_api_http_{exc.status_code}") from exc
    except requests.Timeout as exc:
        raise RuntimeError("amazon_creators_api_timeout") from exc
    except requests.RequestException as exc:
        raise RuntimeError(f"amazon_creators_api_request_error:{type(exc).__name__}") from exc
    finally:
        if response is not None:
            response.close()
