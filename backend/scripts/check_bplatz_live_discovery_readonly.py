"""Read-only live Bplatz discovery, fetch, extraction and canonical matching probe."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import requests  # noqa: E402
from scrapers.bplatz.scraper import HEADERS, discover, parse_product_html  # noqa: E402
from scenthunter_next_engine.next_engine_service import NextEngineService  # noqa: E402
from scenthunter_next_engine.offer_normalizer import normalize_offer  # noqa: E402


QUERY = "Liquid Brun"
BASE_URL = "https://en.bplatz.de"
FETCH_TIMEOUT = (5, 20)


def _status_label(status_code: int) -> str:
    if status_code == 403:
        return "http_403_forbidden"
    if status_code == 404:
        return "http_404_not_found"
    if status_code == 429:
        return "http_429_rate_limited"
    if status_code >= 500:
        return f"http_{status_code}_server_error"
    if status_code >= 400:
        return f"http_{status_code}_error"
    return "ok"


def fetch_candidate(session: requests.Session, url: str, query: str = QUERY) -> dict:
    """Fetch exactly one discovered product URL and parse its returned HTML."""
    result = {
        "requested_url": url,
        "final_url": None,
        "http_status": None,
        "http_status_label": None,
        "html_bytes": 0,
        "fetch_status": None,
        "fetch_error": None,
        "parsed": None,
    }
    try:
        response = session.get(
            url, headers=HEADERS, timeout=FETCH_TIMEOUT, allow_redirects=True
        )
    except requests.Timeout as exc:
        result.update(fetch_status="timeout", fetch_error=f"{type(exc).__name__}: {exc}")
        return result
    except requests.RequestException as exc:
        result.update(fetch_status="request_error", fetch_error=f"{type(exc).__name__}: {exc}")
        return result

    try:
        result["final_url"] = response.url or url
        result["http_status"] = int(response.status_code)
        result["http_status_label"] = _status_label(int(response.status_code))
        body = response.content or b""
        result["html_bytes"] = len(body)
        if response.status_code >= 400:
            result.update(
                fetch_status="http_error",
                fetch_error=f"HTTP {response.status_code}",
            )
            return result
        if not body.strip():
            result.update(fetch_status="empty_body", fetch_error="HTTP response body is empty")
            return result

        content_type = str(response.headers.get("Content-Type") or "").lower()
        if content_type and not any(
            token in content_type for token in ("text/html", "application/xhtml")
        ):
            result.update(
                fetch_status="invalid_content_type",
                fetch_error=f"Unexpected Content-Type: {content_type}",
            )
            return result

        html_text = response.text
        if not html_text or not html_text.strip():
            result.update(fetch_status="empty_html", fetch_error="Decoded HTML is empty")
            return result

        try:
            parsed = parse_product_html(html_text, result["final_url"], query)
        except Exception as exc:  # parser errors are audit data, not silent skips
            result.update(
                fetch_status="parse_error",
                fetch_error=f"{type(exc).__name__}: {exc}",
            )
            return result

        if not parsed:
            result.update(fetch_status="parse_miss", fetch_error="Product parser returned no product")
            return result

        result.update(fetch_status="fetched_and_parsed", parsed=parsed)
        return result
    finally:
        response.close()


def main() -> int:
    discovery_session = requests.Session()
    try:
        candidates, discovery_errors, discovery_verified = discover(discovery_session, QUERY)
    except Exception as exc:
        candidates, discovery_errors, discovery_verified = [], [
            {"source": "discovery", "status": "error", "error": f"{type(exc).__name__}: {exc}"}
        ], False
    finally:
        discovery_session.close()

    valid_urls = []
    invalid_urls = []
    seen = set()
    for url in candidates:
        parsed_url = urlsplit(str(url or ""))
        host = (parsed_url.hostname or "").lower().rstrip(".")
        valid = (
            parsed_url.scheme in {"http", "https"}
            and host in {"en.bplatz.de", "www.bplatz.de", "bplatz.de", "www.bplatz.de"}
            and "/products/" in parsed_url.path.lower()
        )
        if not valid:
            invalid_urls.append({"url": url, "reason": "not_an_allowed_Bplatz_product_URL"})
            continue
        normalized = url.split("#", 1)[0]
        if normalized not in seen:
            seen.add(normalized)
            valid_urls.append(normalized)

    fetch_results = []
    with requests.Session() as session:
        for url in valid_urls:
            fetch_results.append(fetch_candidate(session, url, QUERY))

    matcher = NextEngineService.from_catalog_file(BACKEND / "product_catalog.json")
    products = []
    for fetch in fetch_results:
        parsed = fetch.get("parsed")
        if not parsed:
            continue
        record = {
            "raw_name": parsed.get("name"),
            "brand_raw": parsed.get("brand"),
            "size_ml": parsed.get("size_ml"),
            "price": parsed.get("price_num"),
            "currency": parsed.get("currency"),
            "currency_explicit": parsed.get("currency_explicit") is True,
            "product_url": parsed.get("url"),
            "availability": parsed.get("availability"),
            "sku": parsed.get("sku"),
            "gtin": parsed.get("gtin"),
        }
        offer = normalize_offer(record, retailer="Bplatz", currency_default="EUR")
        match_result = matcher.process_offers([offer])
        matched = (
            match_result.matched_offer_count == 1
            and len(match_result.groups) == 1
        )
        product = {
            "name": parsed.get("name"),
            "brand": parsed.get("brand"),
            "size_ml": parsed.get("size_ml"),
            "concentration": parsed.get("concentration"),
            "price": str(offer.price) if offer.price is not None else None,
            "currency": offer.currency,
            "availability": offer.availability,
            "url": offer.product_url,
            "sku": parsed.get("sku"),
            "gtin": parsed.get("gtin"),
            "canonical_match": matched,
        }
        if matched:
            product["canonical_product_id"] = match_result.groups[0].canonical_product_id
            product["canonical_variant_id"] = match_result.groups[0].canonical_variant_id
        products.append(product)

    parsed_count = sum(1 for item in fetch_results if item.get("parsed"))
    matched_count = sum(1 for item in products if item.get("canonical_match"))
    output = {
        "store": "Bplatz",
        "query": QUERY,
        "discovery": {
            "verified": discovery_verified,
            "candidate_count": len(candidates),
            "valid_unique_url_count": len(valid_urls),
            "invalid_urls": invalid_urls,
            "discovery_errors": discovery_errors,
        },
        "fetch": {
            "attempted": len(fetch_results),
            "parsed": parsed_count,
            "failures": [
                {key: item.get(key) for key in (
                    "requested_url", "final_url", "http_status",
                    "http_status_label", "html_bytes", "fetch_status", "fetch_error",
                )}
                for item in fetch_results if not item.get("parsed")
            ],
            "items": [
                {key: item.get(key) for key in (
                    "requested_url", "final_url", "http_status",
                    "http_status_label", "html_bytes", "fetch_status", "fetch_error",
                )}
                for item in fetch_results
            ],
        },
        "products": products,
        "matching": {
            "matched": matched_count,
            "unmatched": max(0, parsed_count - matched_count),
        },
        "safety": {
            "database_written": False,
            "operational_writes": False,
            "deploy_performed": False,
        },
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    print("BPLATZ_LIVE_DISCOVERY=" + json.dumps(output, ensure_ascii=False))

    if not discovery_verified or not valid_urls:
        return 1
    if parsed_count == 0:
        return 2
    if matched_count == 0:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
