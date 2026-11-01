from __future__ import annotations

"""
ScentHunter - Sabina read-only diagnostics.

Endpoints:

1. /diagnose-sabina-real-seeds
2. /diagnose-sabina-real-seeds-batch
3. /diagnose-sabina-surface-compare

All diagnostics are READ-ONLY.

They do not:
- call production search
- call ProductMatcher
- write database
- run catalog resync
- hydrate products
- modify catalog state
"""

import hashlib
import inspect
import re
import string
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import parse_qs, urlencode, urlsplit

from bs4 import BeautifulSoup
from fastapi import APIRouter, Query

router = APIRouter()

TARGET_TOKEN = "41708"

TARGET_URL = (
    "https://www.sabina.com/it/profumi-di-donna/"
    "41708-liquid-brun-limited-edition-extrait-de-parfum.html"
)

SABINA_SEARCH_BASE = "https://www.sabina.com/it/ricerca_old"

NATIVE_S_PROBES = (
    "parfum",
    "perfume",
    "extrait",
    "profumi",
    "fragrance",
    "eau",
)


def _load_engine():
    import catalog_engine as ce
    return ce


def _configured_sabina_seeds(ce):
    candidates = []

    for name in (
        "HTML_DISCOVERY_SEEDS",
        "DISCOVERY_HTML_SEEDS",
        "SABINA_HTML_DISCOVERY_SEEDS",
    ):
        value = getattr(ce, name, None)

        if isinstance(value, dict):
            value = (
                value.get("sabina")
                or value.get("Sabina")
                or value.get("SABINA")
            )

        if isinstance(value, (list, tuple, set)):
            candidates.extend(str(item) for item in value if item)
            if candidates:
                break

    if not candidates:
        candidates = [
            (
                "https://www.sabina.com/it/ricerca_old"
                f"?search_query={letter}"
            )
            for letter in string.ascii_lowercase
        ]

    return [
        url
        for url in candidates
        if "sabina.com" in url.lower()
        and "/ricerca_old" in url.lower()
        and "search_query=" in url.lower()
    ]


def _select_seed(seeds, letter):
    wanted = str(letter).strip().lower()

    for seed in seeds:
        parsed = urlsplit(seed)
        query = parse_qs(
            parsed.query,
            keep_blank_values=True,
        )

        values = query.get("search_query") or []

        for value in values:
            if str(value).strip().lower() == wanted:
                return seed

    return None


def _native_s_url(term):
    return (
        SABINA_SEARCH_BASE
        + "?"
        + urlencode({"s": term})
    )


def _target_urls(product_urls):
    return [
        url
        for url in product_urls
        if TARGET_TOKEN in str(url)
        or TARGET_URL.casefold() in str(url).casefold()
    ]


def _extract_ids(ce, data, page_base):
    helper = getattr(ce, "_sabina_legacy_product_urls", None)

    if helper is None:
        raise RuntimeError(
            "catalog_engine._sabina_legacy_product_urls not found"
        )

    values = helper(data, page_base)

    return sorted(
        str(value)
        for value in values
        if value
    )


def _fetch_surface(ce, url):
    started = time.time()

    response = ce._http_fetch(
        url,
        timeout=25,
    )

    status = response.get("status")
    final_url = response.get("url") or url
    data = response.get("data") or ""

    if isinstance(data, bytes):
        raw = data
        text = data.decode("utf-8", "ignore")
    else:
        text = str(data)
        raw = text.encode("utf-8", "ignore")

    return {
        "requested_url": url,
        "final_url": final_url,
        "status": status,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "content_type": response.get("content_type"),
        "text": text,
        "elapsed_sec": round(time.time() - started, 3),
    }


def _surface_structure(ce, fetched):
    text = fetched["text"]
    final_url = fetched["final_url"]

    soup = BeautifulSoup(
        text,
        "html.parser",
    )

    title = None

    if soup.title:
        title = soup.title.get_text(
            " ",
            strip=True,
        )

    canonical = None

    canonical_node = soup.find(
        "link",
        rel=lambda value: (
            value
            and "canonical" in (
                value
                if isinstance(value, list)
                else [str(value)]
            )
        ),
    )

    if canonical_node:
        canonical = canonical_node.get("href")

    hidden_values = []

    for node in soup.find_all(
        attrs={
            "id": re.compile(
                r"^af_controller_product_ids$",
                re.I,
            )
        }
    ):
        value = (
            node.get("value")
            or node.get_text(" ", strip=True)
            or ""
        )

        hidden_values.append(value)

    for node in soup.find_all(
        attrs={
            "name": re.compile(
                r"^af_controller_product_ids$",
                re.I,
            )
        }
    ):
        value = (
            node.get("value")
            or node.get_text(" ", strip=True)
            or ""
        )

        hidden_values.append(value)

    hidden_ids = set()

    for value in hidden_values:
        for product_id in re.findall(
            r"(?<!\d)\d+(?!\d)",
            value,
        ):
            hidden_ids.add(product_id)

    anchor_urls = []
    resolver_urls = []

    for node in soup.find_all(
        "a",
        href=True,
    ):
        href = str(node.get("href") or "")

        if not href:
            continue

        if TARGET_TOKEN in href:
            anchor_urls.append(href)

        if (
            "controller=product" in href.lower()
            and "id_product=" in href.lower()
        ):
            resolver_urls.append(href)

    literal_target_positions = []

    start = 0

    while True:
        position = text.find(
            TARGET_TOKEN,
            start,
        )

        if position < 0:
            break

        literal_target_positions.append(position)
        start = position + len(TARGET_TOKEN)

        if len(literal_target_positions) >= 20:
            break

    target_contexts = []

    for position in literal_target_positions:
        left = max(0, position - 300)
        right = min(
            len(text),
            position + 500,
        )

        target_contexts.append(
            text[left:right]
        )

    data_layer_target = []

    for match in re.finditer(
        r"dataLayer|dataLayer\.push",
        text,
        re.I,
    ):
        left = max(0, match.start() - 100)
        right = min(
            len(text),
            match.start() + 1200,
        )

        fragment = text[left:right]

        if TARGET_TOKEN in fragment:
            data_layer_target.append(fragment)

        if len(data_layer_target) >= 10:
            break

    search_query_values = []

    parsed = urlsplit(final_url)

    final_query = parse_qs(
        parsed.query,
        keep_blank_values=True,
    )

    for key in (
        "search_query",
        "s",
        "q",
    ):
        for value in final_query.get(key, []):
            search_query_values.append(
                {
                    "key": key,
                    "value": value,
                }
            )

    helper_ids = _extract_ids(
        ce,
        text,
        final_url,
    )

    return {
        "title": title,
        "canonical": canonical,
        "final_url": final_url,

        "query_parameters": search_query_values,

        "raw": {
            "target_literal_present": TARGET_TOKEN in text,
            "target_literal_occurrences": len(
                literal_target_positions
            ),
            "target_positions": literal_target_positions,
        },

        "legacy_controller_field": {
            "field_found": bool(hidden_values),
            "field_instances": len(hidden_values),
            "raw_values_lengths": [
                len(value)
                for value in hidden_values
            ],
            "unique_ids": len(hidden_ids),
            "contains_41708": TARGET_TOKEN in hidden_ids,
            "first_20_ids": sorted(
                hidden_ids,
                key=lambda value: int(value),
            )[:20],
            "last_20_ids": sorted(
                hidden_ids,
                key=lambda value: int(value),
            )[-20:],
        },

        "production_legacy_helper": {
            "returned_url_count": len(helper_ids),
            "contains_41708": any(
                TARGET_TOKEN in value
                for value in helper_ids
            ),
            "target_urls": _target_urls(helper_ids),
            "first_20_urls": helper_ids[:20],
            "last_20_urls": helper_ids[-20:],
        },

        "anchors": {
            "target_matching_anchors": anchor_urls[:50],
            "target_matching_anchor_count": len(
                anchor_urls
            ),
            "resolver_anchor_count": len(
                resolver_urls
            ),
            "resolver_target_urls": [
                value
                for value in resolver_urls
                if TARGET_TOKEN in value
            ][:50],
        },

        "target_contexts": target_contexts,

        "data_layer_target_contexts": data_layer_target,

        "html": {
            "sha256": fetched["sha256"],
            "bytes": fetched["bytes"],
        },
    }


@router.get("/diagnose-sabina-real-seeds")
def diagnose_sabina_real_seeds(
    letter: str = Query(
        "l",
        min_length=1,
        max_length=1,
    ),
    max_pages: int = Query(
        1,
        ge=1,
        le=1,
    ),
    max_depth: int = Query(
        0,
        ge=0,
        le=0,
    ),
):
    started = time.time()

    ce = _load_engine()

    fn = getattr(
        ce,
        "_discover_html_catalog",
        None,
    )

    priority = getattr(
        ce,
        "_html_discovery_priority",
        None,
    )

    if fn is None:
        return {
            "diagnostic": "sabina-real-seed-v2",
            "ok": False,
            "error": (
                "catalog_engine._discover_html_catalog "
                "not found"
            ),
            "read_only": True,
        }

    source = inspect.getsource(fn)

    priority_source = (
        inspect.getsource(priority)
        if priority
        else ""
    )

    seeds = _configured_sabina_seeds(ce)

    selected_seed = _select_seed(
        seeds,
        letter,
    )

    if selected_seed is None:
        return {
            "diagnostic": "sabina-real-seed-v2",
            "ok": False,
            "error": (
                "requested production seed not found"
            ),
            "requested_letter": letter,
            "available_seeds": seeds,
            "read_only": True,
            "production_search_called": False,
            "product_matcher_called": False,
            "database_written": False,
            "catalog_resync_called": False,
        }

    old_pages = getattr(
        ce,
        "HTML_MAX_PAGES",
        None,
    )

    old_depth = getattr(
        ce,
        "HTML_MAX_DEPTH",
        None,
    )

    try:
        ce.HTML_MAX_PAGES = int(
            max_pages
        )

        ce.HTML_MAX_DEPTH = int(
            max_depth
        )

        seed_started = time.time()

        result = fn(
            "sabina",
            [selected_seed],
            time.time() + 45,
        )

        elapsed_seed = round(
            time.time() - seed_started,
            3,
        )

    except Exception as exc:
        return {
            "diagnostic": "sabina-real-seed-v2",
            "ok": False,
            "requested_letter": letter,
            "seed": selected_seed,
            "error": (
                f"{type(exc).__name__}:{exc}"
            ),
            "read_only": True,
            "production_search_called": False,
            "product_matcher_called": False,
            "database_written": False,
            "catalog_resync_called": False,
            "elapsed_sec": round(
                time.time() - started,
                3,
            ),
        }

    finally:
        if old_pages is not None:
            ce.HTML_MAX_PAGES = old_pages

        if old_depth is not None:
            ce.HTML_MAX_DEPTH = old_depth

    product_urls = sorted(
        (result.get("product_urls") or {}).keys()
    )

    target_urls = _target_urls(
        product_urls
    )

    return {
        "diagnostic": "sabina-real-seed-v2",
        "ok": True,

        "target": {
            "product_id": TARGET_TOKEN,
            "canonical_url": TARGET_URL,
        },

        "requested_seed": {
            "letter": letter,
            "seed": selected_seed,
        },

        "limits": {
            "max_pages": max_pages,
            "max_depth": max_depth,
        },

        "source_flags": {
            "discover_html_catalog_exists": True,
            "discover_calls_legacy_helper": (
                "_sabina_legacy_product_urls"
                in source
            ),
            "priority_exists": bool(priority),
            "priority_mentions_ricerca_old": (
                "ricerca_old"
                in priority_source
            ),
        },

        "discovery_result": {
            "visited": result.get(
                "visited"
            ),
            "successes": result.get(
                "successes"
            ),
            "error_count": len(
                result.get("errors") or []
            ),
            "errors": (
                result.get("errors") or []
            )[:10],
            "product_url_count": len(
                product_urls
            ),
            "target_urls": target_urls,
            "target_found": bool(
                target_urls
            ),
        },

        "sample_product_urls": product_urls[:50],

        "read_only": True,
        "production_search_called": False,
        "product_matcher_called": False,
        "database_written": False,
        "catalog_resync_called": False,

        "elapsed_seed_sec": elapsed_seed,
        "elapsed_sec": round(
            time.time() - started,
            3,
        ),
    }


@router.get(
    "/diagnose-sabina-real-seeds-batch"
)
def diagnose_sabina_real_seeds_batch(
    include_native: bool = Query(True),
    workers: int = Query(
        6,
        ge=1,
        le=8,
    ),
):
    started = time.time()

    ce = _load_engine()

    seeds = _configured_sabina_seeds(
        ce
    )

    configured_by_letter = {}

    for letter in string.ascii_lowercase:
        configured_by_letter[letter] = (
            _select_seed(
                seeds,
                letter,
            )
        )

    production_surfaces = [
        seed
        for seed in configured_by_letter.values()
        if seed
    ]

    native_surfaces = []

    if include_native:
        native_surfaces = [
            _native_s_url(term)
            for term in NATIVE_S_PROBES
        ]

    all_surfaces = []

    for url in (
        production_surfaces
        + native_surfaces
    ):
        if url not in all_surfaces:
            all_surfaces.append(url)

    def run_one(url):
        try:
            fetched = _fetch_surface(
                ce,
                url,
            )

            ids = _extract_ids(
                ce,
                fetched["text"],
                fetched["final_url"],
            )

            return {
                "url": url,
                "status": fetched["status"],
                "bytes": fetched["bytes"],
                "final_url": fetched["final_url"],
                "id_count": len(ids),
                "target_found": bool(
                    _target_urls(ids)
                ),
                "target_urls": _target_urls(
                    ids
                ),
                "ids": ids,
                "elapsed_sec": fetched[
                    "elapsed_sec"
                ],
            }

        except Exception as exc:
            return {
                "url": url,
                "status": None,
                "bytes": 0,
                "final_url": None,
                "id_count": 0,
                "target_found": False,
                "target_urls": [],
                "ids": [],
                "elapsed_sec": None,
                "error": (
                    f"{type(exc).__name__}:{exc}"
                ),
            }

    results = {}

    with ThreadPoolExecutor(
        max_workers=min(
            workers,
            max(1, len(all_surfaces)),
        )
    ) as executor:

        futures = {
            executor.submit(
                run_one,
                url,
            ): url
            for url in all_surfaces
        }

        for future in as_completed(
            futures
        ):
            url = futures[future]
            results[url] = future.result()

    union_ids = set()

    ordered = []

    for url in all_surfaces:
        result = results[url]

        parsed = urlsplit(url)

        query = parse_qs(
            parsed.query,
            keep_blank_values=True,
        )

        kind = (
            "production_search_query"
            if "search_query" in query
            else "native_s"
        )

        ordered.append(
            {
                "kind": kind,
                "letter": (
                    query.get(
                        "search_query",
                        [None],
                    )[0]
                ),
                "term": (
                    query.get(
                        "s",
                        [None],
                    )[0]
                ),
                "url": url,
                "final_url": result.get(
                    "final_url"
                ),
                "status": result.get(
                    "status"
                ),
                "bytes": result.get(
                    "bytes"
                ),
                "id_count": result.get(
                    "id_count"
                ),
                "target_found": result.get(
                    "target_found"
                ),
                "target_urls": result.get(
                    "target_urls"
                ),
                "error": result.get(
                    "error"
                ),
                "elapsed_sec": result.get(
                    "elapsed_sec"
                ),
            }
        )

        for value in result.get(
            "ids"
        ) or []:
            union_ids.add(value)

    union_target_urls = _target_urls(
        sorted(union_ids)
    )

    target_surfaces = [
        item
        for item in ordered
        if item["target_found"]
    ]

    return {
        "diagnostic":
            "sabina-real-seeds-batch-v1",

        "ok": True,

        "target": {
            "product_id": TARGET_TOKEN,
            "canonical_url": TARGET_URL,
        },

        "configured_production_seeds": {
            "total_configured_ricerca_old_seeds":
                len(seeds),
            "expected_letters":
                list(string.ascii_lowercase),
            "found_letters": [
                letter
                for letter, seed
                in configured_by_letter.items()
                if seed
            ],
            "missing_letters": [
                letter
                for letter, seed
                in configured_by_letter.items()
                if not seed
            ],
            "seeds":
                configured_by_letter,
        },

        "native_s_probes": {
            "enabled": bool(
                include_native
            ),
            "terms": (
                list(NATIVE_S_PROBES)
                if include_native
                else []
            ),
            "urls":
                native_surfaces,
        },

        "limits": {
            "workers": workers,
            "surfaces_tested":
                len(all_surfaces),
        },

        "summary": {
            "surfaces_tested":
                len(all_surfaces),
            "successful_http":
                sum(
                    1
                    for item in ordered
                    if (
                        isinstance(
                            item["status"],
                            int,
                        )
                        and item["status"] < 400
                    )
                ),
            "failed_http":
                sum(
                    1
                    for item in ordered
                    if not (
                        isinstance(
                            item["status"],
                            int,
                        )
                        and item["status"] < 400
                    )
                ),
            "production_search_query_surfaces_tested":
                len(production_surfaces),
            "native_s_surfaces_tested":
                len(native_surfaces),
            "unique_ids_union":
                len(union_ids),
            "target_found_in_union":
                bool(union_target_urls),
            "target_union_urls":
                union_target_urls,
            "target_surfaces_total":
                len(target_surfaces),
            "target_production_search_query_surfaces":
                sum(
                    1
                    for item in target_surfaces
                    if item["kind"]
                    == "production_search_query"
                ),
            "target_native_s_surfaces":
                sum(
                    1
                    for item in target_surfaces
                    if item["kind"]
                    == "native_s"
                ),
        },

        "target_surfaces":
            target_surfaces,

        "surfaces":
            ordered,

        "read_only": True,
        "production_search_called": False,
        "product_matcher_called": False,
        "database_written": False,
        "catalog_resync_called": False,
        "hydration_called": False,

        "elapsed_sec": round(
            time.time() - started,
            3,
        ),
    }


@router.get(
    "/diagnose-sabina-surface-compare"
)
def diagnose_sabina_surface_compare(
    query: str = Query(
        "p",
        min_length=1,
        max_length=100,
    ),
    native: str = Query(
        "parfum",
        min_length=1,
        max_length=100,
    ),
):
    """
    Compare the raw Sabina HTML returned by:

        /ricerca_old?search_query=<query>

    versus:

        /ricerca_old?s=<native>

    No discovery graph is involved.
    No database is touched.
    """

    started = time.time()

    ce = _load_engine()

    search_query_url = (
        SABINA_SEARCH_BASE
        + "?"
        + urlencode(
            {
                "search_query": query,
            }
        )
    )

    native_url = (
        SABINA_SEARCH_BASE
        + "?"
        + urlencode(
            {
                "s": native,
            }
        )
    )

    urls = {
        "search_query": search_query_url,
        "native_s": native_url,
    }

    surfaces = {}

    for name, url in urls.items():

        try:
            fetched = _fetch_surface(
                ce,
                url,
            )

            structure = _surface_structure(
                ce,
                fetched,
            )

            surfaces[name] = {
                "request": {
                    "url": url,
                    "query_type": name,
                },

                "response": {
                    "status":
                        fetched["status"],
                    "final_url":
                        fetched["final_url"],
                    "bytes":
                        fetched["bytes"],
                    "sha256":
                        fetched["sha256"],
                    "content_type":
                        fetched["content_type"],
                    "elapsed_sec":
                        fetched["elapsed_sec"],
                },

                "structure":
                    structure,
            }

        except Exception as exc:
            surfaces[name] = {
                "request": {
                    "url": url,
                    "query_type": name,
                },
                "error": (
                    f"{type(exc).__name__}:{exc}"
                ),
            }

    sq = surfaces.get(
        "search_query",
        {},
    )

    ns = surfaces.get(
        "native_s",
        {},
    )

    sq_structure = sq.get(
        "structure",
        {},
    )

    ns_structure = ns.get(
        "structure",
        {},
    )

    sq_legacy = sq_structure.get(
        "legacy_controller_field",
        {},
    )

    ns_legacy = ns_structure.get(
        "legacy_controller_field",
        {},
    )

    sq_helper = sq_structure.get(
        "production_legacy_helper",
        {},
    )

    ns_helper = ns_structure.get(
        "production_legacy_helper",
        {},
    )

    sq_raw = sq_structure.get(
        "raw",
        {},
    )

    ns_raw = ns_structure.get(
        "raw",
        {},
    )

    return {
        "diagnostic":
            "sabina-surface-compare-v1",

        "ok": True,

        "target": {
            "product_id": TARGET_TOKEN,
            "canonical_url": TARGET_URL,
        },

        "inputs": {
            "search_query":
                query,
            "native_s":
                native,
        },

        "surfaces":
            surfaces,

        "direct_comparison": {
            "search_query": {
                "status":
                    sq.get(
                        "response",
                        {},
                    ).get("status"),
                "bytes":
                    sq.get(
                        "response",
                        {},
                    ).get("bytes"),
                "sha256":
                    sq.get(
                        "response",
                        {},
                    ).get("sha256"),
                "target_literal_present":
                    sq_raw.get(
                        "target_literal_present"
                    ),
                "target_literal_occurrences":
                    sq_raw.get(
                        "target_literal_occurrences"
                    ),
                "legacy_field_found":
                    sq_legacy.get(
                        "field_found"
                    ),
                "legacy_unique_ids":
                    sq_legacy.get(
                        "unique_ids"
                    ),
                "legacy_contains_41708":
                    sq_legacy.get(
                        "contains_41708"
                    ),
                "helper_returned_urls":
                    sq_helper.get(
                        "returned_url_count"
                    ),
                "helper_contains_41708":
                    sq_helper.get(
                        "contains_41708"
                    ),
            },

            "native_s": {
                "status":
                    ns.get(
                        "response",
                        {},
                    ).get("status"),
                "bytes":
                    ns.get(
                        "response",
                        {},
                    ).get("bytes"),
                "sha256":
                    ns.get(
                        "response",
                        {},
                    ).get("sha256"),
                "target_literal_present":
                    ns_raw.get(
                        "target_literal_present"
                    ),
                "target_literal_occurrences":
                    ns_raw.get(
                        "target_literal_occurrences"
                    ),
                "legacy_field_found":
                    ns_legacy.get(
                        "field_found"
                    ),
                "legacy_unique_ids":
                    ns_legacy.get(
                        "unique_ids"
                    ),
                "legacy_contains_41708":
                    ns_legacy.get(
                        "contains_41708"
                    ),
                "helper_returned_urls":
                    ns_helper.get(
                        "returned_url_count"
                    ),
                "helper_contains_41708":
                    ns_helper.get(
                        "contains_41708"
                    ),
            },

            "same_html_sha256": (
                sq.get(
                    "response",
                    {},
                ).get("sha256")
                == ns.get(
                    "response",
                    {},
                ).get("sha256")
            ),

            "same_byte_length": (
                sq.get(
                    "response",
                    {},
                ).get("bytes")
                == ns.get(
                    "response",
                    {},
                ).get("bytes")
            ),
        },

        "read_only": True,

        "production_search_called": False,
        "product_matcher_called": False,
        "database_written": False,
        "catalog_resync_called": False,
        "hydration_called": False,

        "elapsed_sec": round(
            time.time() - started,
            3,
        ),
    }
