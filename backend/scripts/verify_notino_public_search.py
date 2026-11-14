"""Verify public Notino searches against the isolated Phase 2 staging app."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.parse
import urllib.request


_JOB_ID = re.compile(r"^[0-9a-f]{32}$")
_TERMINAL_ERRORS = {
    "cancelled",
    "cancelled_with_results",
    "completed_with_store_issues",
    "error",
    "failed",
    "job_not_found",
    "timed_out",
}
_CJ_HOSTS = {
    "www.anrdoezrs.net",
    "www.dpbolvw.net",
    "www.jdoqocy.com",
    "www.kqzyfj.com",
    "www.tkqlhce.com",
}
_NOTINO_HOSTS = {"notino.fr", "www.notino.fr"}


def _request_json(base_url: str, path: str, deadline: float) -> dict:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("public search deadline expired before request")
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        headers={"Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=min(20.0, remaining)) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"public search returned a non-object JSON payload: {payload!r}")
    return payload


def _progress(query: str, job_id: str, status: str, elapsed: float) -> None:
    print(
        f"PUBLIC_SEARCH_PROGRESS query={query!r} job_id={job_id or '-'} "
        f"status={status} duration_sec={elapsed:.1f}",
        flush=True,
    )


def poll_public_search(
    query: str,
    base_url: str,
    overall_deadline: float,
    *,
    store: str = "notino",
    search_timeout: float = 60.0,
    request_json=_request_json,
    clock=time.monotonic,
    sleep=time.sleep,
    progress=_progress,
) -> dict:
    """Wait for one actual completed job, or raise with its terminal state."""
    started = clock()
    deadline = min(overall_deadline, started + search_timeout)
    if deadline <= started:
        raise TimeoutError(f"no time budget remains for public search {query!r}")

    job_id = ""
    payload: dict = {}
    last_progress = 0.0
    last_status = ""

    def report(status: str) -> None:
        nonlocal last_progress, last_status
        elapsed = clock() - started
        if status != last_status or elapsed - last_progress >= 5:
            progress(query, job_id, status, elapsed)
            last_status = status
            last_progress = elapsed

    start_path = "/search-start?" + urllib.parse.urlencode({
        "q": query,
        "store": store,
    })
    while True:
        try:
            payload = request_json(base_url, start_path, deadline)
        except TimeoutError:
            raise TimeoutError(
                f"public /search-start timed out for {query!r} "
                f"after {clock() - started:.1f}s"
            ) from None
        status = str(payload.get("status") or "")
        if status == "busy":
            report("busy")
            if clock() >= deadline:
                raise TimeoutError(
                    f"public /search-start remained busy for {query!r} "
                    f"after {clock() - started:.1f}s"
                )
            retry_ms = payload.get("retry_after_ms", 250)
            try:
                delay = max(0.05, min(1.0, float(retry_ms) / 1000))
            except (TypeError, ValueError):
                delay = 0.25
            sleep(min(delay, max(0.0, deadline - clock())))
            continue
        if not payload.get("job_id"):
            report(status or "missing_job_id")
            raise RuntimeError(
                f"public /search-start returned no job_id for {query!r}: {payload!r}"
            )
        job_id = str(payload["job_id"])
        if not _JOB_ID.fullmatch(job_id):
            report(status or "invalid_job_id")
            raise RuntimeError(
                f"public /search-start returned an invalid job_id for "
                f"{query!r}: {job_id!r}"
            )
        break

    status_path = "/search-status?" + urllib.parse.urlencode({"job_id": job_id})
    while True:
        status = str(payload.get("status") or "")
        report(status or "missing_status")
        returned_job_id = payload.get("job_id")
        if returned_job_id != job_id:
            raise RuntimeError(
                f"public /search-status returned the wrong job for {query!r}: "
                f"expected {job_id!r}, got {returned_job_id!r}"
            )
        errors = payload.get("errors") or {}
        if status in _TERMINAL_ERRORS or errors.get("job") == "job_not_found":
            raise RuntimeError(
                f"public search reached terminal state for {query!r}: "
                f"status={status!r}, errors={errors!r}"
            )
        if status == "completed":
            if payload.get("completed") is not True:
                raise RuntimeError(
                    f"public search reported completed without completed=true "
                    f"for {query!r}: {payload!r}"
                )
            if errors:
                raise RuntimeError(
                    f"public search completed with errors for {query!r}: {errors!r}"
                )
            return payload
        if payload.get("completed") is True:
            raise RuntimeError(
                f"public search has an unrecognized completed status for "
                f"{query!r}: {payload!r}"
            )
        if clock() >= deadline:
            raise TimeoutError(
                f"public search timed out for {query!r}: job_id={job_id}, "
                f"status={status!r}, duration_sec={clock() - started:.1f}, "
                f"errors={errors!r}"
            )
        try:
            payload = request_json(base_url, status_path, deadline)
        except TimeoutError:
            raise TimeoutError(
                f"public /search-status timed out for {query!r}: "
                f"job_id={job_id}, status={status!r}, "
                f"duration_sec={clock() - started:.1f}"
            ) from None
        sleep(min(0.5, max(0.0, deadline - clock())))


def _notino_report(payload: dict, query: str) -> dict:
    report = (payload.get("stores") or {}).get("notino") or {}
    details = report.get("details") or {}
    if details.get("phase2_source") != "persistent_notino_cj_catalog":
        raise AssertionError({"query": query, "notino_details": details})
    if details.get("live_scraping") is not False:
        raise AssertionError({"query": query, "notino_details": details})
    if (details.get("live_fallback") or {}).get("attempted"):
        raise AssertionError({"query": query, "notino_details": details})
    return report


def _notino_offers(payload: dict) -> list[tuple[dict, dict]]:
    return [
        (group, offer)
        for group in payload.get("results") or []
        if isinstance(group, dict)
        for offer in group.get("offers") or []
        if isinstance(offer, dict)
        and str(offer.get("store") or offer.get("shop") or "").strip().casefold() == "notino"
    ]


def _phase2_brand_offers(payload: dict, brand: str) -> list[dict]:
    return [
        offer
        for _group, offer in _notino_offers(payload)
        if offer.get("source") == "cj_notino_fr_feed"
        and str(offer.get("brand") or offer.get("canonical_brand") or "").casefold()
        == brand.casefold()
    ]


def valid_affiliate(value: str) -> bool:
    parsed = urllib.parse.urlsplit(value)
    destinations = urllib.parse.parse_qs(parsed.query).get("url", [])
    if (
        parsed.scheme != "https"
        or parsed.hostname not in _CJ_HOSTS
        or not parsed.path.startswith("/click-")
        or len(destinations) != 1
    ):
        return False
    target = urllib.parse.urlsplit(destinations[0])
    return (
        target.scheme == "https"
        and target.hostname in _NOTINO_HOSTS
        and target.path not in ("", "/")
    )


def _validate_offer(offer: dict, query: str) -> None:
    price = float(offer.get("price") or offer.get("price_num") or 0)
    availability = offer.get("availability")
    available = availability == "in_stock"
    if (
        price <= 0
        or offer.get("currency") != "EUR"
        or availability not in {"in_stock", "out_of_stock"}
        or offer.get("available") is not available
        or offer.get("in_stock") is not available
        or offer.get("source") != "cj_notino_fr_feed"
        or not valid_affiliate(str(offer.get("url") or ""))
    ):
        raise AssertionError({"query": query, "invalid_offer": offer})


def _json_value_from_output(raw: str) -> list:
    start = raw.find("[")
    if start < 0:
        raise ValueError(f"could not find JSON array in staging output: {raw[-1000:]}")
    value, _end = json.JSONDecoder().raw_decode(raw, start)
    if not isinstance(value, list):
        raise ValueError(f"staging output did not contain a JSON array: {value!r}")
    return value


def verify_known_products(base_url: str, deadline: float, page_prices: dict[str, float]) -> None:
    aquatica_query = "Rayhaan Aquatica"
    aquatica_payload = poll_public_search(aquatica_query, base_url, deadline)
    _notino_report(aquatica_payload, aquatica_query)
    aquatica_path = "aquatica-eau-de-parfum-pour-homme/p-16407892"
    aquatica_hits = []
    for group, offer in _notino_offers(aquatica_payload):
        if (
            offer.get("source") == "cj_notino_fr_feed"
            and "aquatica" in str(offer.get("name") or group.get("name") or "").casefold()
            and aquatica_path in urllib.parse.unquote(
                urllib.parse.parse_qs(
                    urllib.parse.urlsplit(str(offer.get("url") or "")).query
                ).get("url", [""])[0]
            )
        ):
            _validate_offer(offer, aquatica_query)
            aquatica_hits.append(offer)
    if not aquatica_hits:
        raise AssertionError({
            "query": aquatica_query,
            "message": "no Phase 2 offer with the expected Notino destination",
            "results": aquatica_payload.get("results"),
        })
    if float(aquatica_hits[0].get("price_num") or aquatica_hits[0].get("price")) != page_prices["Rayhaan Aquatica"]:
        raise AssertionError({"query": aquatica_query, "page_prices": page_prices, "offers": aquatica_hits})
    print("PUBLIC_RAYHAAN_AQUATICA_RETAILER_ONLY_SEARCH=PASS")
    print("PUBLIC_RAYHAAN_AQUATICA_PRICE=" + str(
        aquatica_hits[0].get("price") or aquatica_hits[0].get("price_num")
    ))
    print("PUBLIC_RAYHAAN_AQUATICA_URL=" + str(aquatica_hits[0].get("url")))

    hawas_query = "Rasasi Hawas Ice Eau de Parfum 100 ml"
    hawas_payload = poll_public_search(hawas_query, base_url, deadline)
    _notino_report(hawas_payload, hawas_query)
    hawas_hits = []
    hawas_variant_offers = []
    for group, offer in _notino_offers(hawas_payload):
        name = str(offer.get("name") or group.get("name") or "").casefold()
        if (
            "hawas ice" in name
            and abs(float(offer.get("size_ml") or group.get("size_ml") or 0) - 100) < 0.01
        ):
            hawas_variant_offers.append(offer)
        destination = urllib.parse.parse_qs(
            urllib.parse.urlsplit(str(offer.get("url") or "")).query
        ).get("url", [""])[0]
        target = urllib.parse.urlsplit(destination)
        if (
            offer.get("source") == "cj_notino_fr_feed"
            and str(offer.get("brand") or "").casefold() == "rasasi"
            and abs(float(offer.get("size_ml") or 0) - 100) < 0.01
            and str(offer.get("variant") or "").casefold() in {
                "edp", "eau de parfum",
            }
            and target.hostname in _NOTINO_HOSTS
            and "/p-16242201/" in target.path
            and "hawas-ice" in target.path.casefold()
            and "coffret" not in target.path.casefold()
        ):
            _validate_offer(offer, hawas_query)
            if offer.get("price_stale") is not False:
                raise AssertionError({
                    "query": hawas_query,
                    "message": "Hawas Ice price is not marked fresh",
                    "offer": offer,
                })
            hawas_hits.append(offer)
    if len(hawas_hits) != 1 or len(hawas_variant_offers) != 1:
        raise AssertionError({
            "query": hawas_query,
            "message": "expected exactly one verified Hawas Ice 100 ml offer",
            "results": hawas_payload.get("results"),
        })
    if float(hawas_hits[0].get("price_num") or hawas_hits[0].get("price")) != page_prices["Rasasi Hawas Ice"]:
        raise AssertionError({"query": hawas_query, "page_prices": page_prices, "offers": hawas_hits})
    print("PUBLIC_RASASI_HAWAS_ICE_100ML_SEARCH=PASS")
    print("PUBLIC_RASASI_HAWAS_ICE_PRICE=" + str(
        hawas_hits[0].get("price") or hawas_hits[0].get("price_num")
    ))
    print("PUBLIC_RASASI_HAWAS_ICE_URL=" + str(hawas_hits[0].get("url")))

    liquid_query = "Liquid Brun"
    liquid_payload = poll_public_search(liquid_query, base_url, deadline)
    _notino_report(liquid_payload, liquid_query)
    liquid_hits = []
    for group, offer in _notino_offers(liquid_payload):
        if "liquid brun" in str(
            offer.get("name") or group.get("name") or ""
        ).casefold():
            _validate_offer(offer, liquid_query)
            liquid_hits.append(offer)
    if not liquid_hits:
        raise AssertionError({
            "query": liquid_query,
            "message": "no valid Phase 2 Liquid Brun offer",
            "results": liquid_payload.get("results"),
        })
    print("PUBLIC_LIQUID_BRUN_CATALOG_FIRST_SEARCH=PASS")
    print("PUBLIC_LIQUID_BRUN_PRICE=" + str(
        liquid_hits[0].get("price") or liquid_hits[0].get("price_num")
    ))
    print("PUBLIC_LIQUID_BRUN_CURRENCY=" + str(liquid_hits[0].get("currency")))
    print("PUBLIC_LIQUID_BRUN_URL=" + str(liquid_hits[0].get("url")))


def verify_multiple_brands(
    base_url: str,
    overall_deadline: float,
    brands_raw: str,
    retailer_only_raw: str,
) -> None:
    brands = _json_value_from_output(brands_raw)
    if len(brands) < 5 or any(not isinstance(brand, str) or not brand.strip() for brand in brands):
        raise AssertionError({"feed_brands": brands})

    verified = []
    for brand in brands:
        query = brand.strip()
        payload = poll_public_search(query, base_url, overall_deadline)
        _notino_report(payload, query)
        matching = []
        for offer in _phase2_brand_offers(payload, query):
            _validate_offer(offer, query)
            if offer.get("availability") == "in_stock":
                matching.append(offer)
        if matching:
            verified.append({"brand": query, "notino_offers": len(matching)})
            print(
                f"PUBLIC_BRAND_VERIFIED brand={query!r} "
                f"offers={len(matching)} price={matching[0].get('price') or matching[0].get('price_num')}",
                flush=True,
            )
        if len(verified) == 5:
            break
    if len(verified) < 5:
        raise AssertionError({
            "message": "fewer than five feed brands had valid public Phase 2 offers",
            "brands_tested": brands,
            "brands_verified": verified,
        })
    print("PUBLIC_NOTINO_MULTI_BRAND_SEARCH=PASS")
    print(json.dumps(verified, ensure_ascii=False))

    sample = _json_value_from_output(retailer_only_raw)
    if len(sample) != 3 or any(not value for value in sample):
        raise ValueError(f"invalid retailer-only sample from staging DB: {sample!r}")
    brand, title, external_id = (str(value) for value in sample)
    query = brand + " " + title
    expected_catalog_id = "notino-feed-" + hashlib.sha256(
        external_id.encode("utf-8")
    ).hexdigest()[:24]
    payload = poll_public_search(query, base_url, overall_deadline)
    _notino_report(payload, query)
    hits = [
        (group, offer)
        for group, offer in _notino_offers(payload)
        if group.get("retailer_only") is True
        and group.get("catalog_id") == expected_catalog_id
    ]
    if not hits:
        raise AssertionError({
            "query": query,
            "external_id": external_id,
            "message": "retailer-only offer was not published as retailer-only",
        })
    _validate_offer(hits[0][1], query)
    print("PUBLIC_NOTINO_RETAILER_ONLY_SEARCH=PASS")
    print(json.dumps({
        "brand": brand,
        "external_id": external_id,
        "query": query,
    }, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--overall-timeout-seconds", type=float, default=480)
    parser.add_argument("--brands-json")
    parser.add_argument("--retailer-only-json")
    parser.add_argument("--known-products", action="store_true")
    parser.add_argument("--page-prices-json")
    args = parser.parse_args()
    if bool(args.brands_json) != bool(args.retailer_only_json):
        parser.error("--brands-json and --retailer-only-json must be supplied together")
    if not args.known_products and not args.brands_json:
        parser.error("select --known-products and/or supply multi-brand samples")
    if args.known_products and not args.page_prices_json:
        parser.error("--known-products requires --page-prices-json from product-page hydration")

    deadline = time.monotonic() + args.overall_timeout_seconds
    if args.known_products:
        verify_known_products(args.base_url, deadline, json.loads(args.page_prices_json))
    if args.brands_json:
        verify_multiple_brands(
            args.base_url,
            deadline,
            args.brands_json,
            args.retailer_only_json,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
