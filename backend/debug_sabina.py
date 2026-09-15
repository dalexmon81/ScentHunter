from __future__ import annotations

import json
import traceback
from urllib.parse import urljoin

from fastapi import APIRouter, Query
from bs4 import BeautifulSoup

try:
    from backend.scrapers.sabina import scraper as sabina
except ModuleNotFoundError:
    from scrapers.sabina import scraper as sabina


router = APIRouter()

KOBRA_URL = (
    "https://www.sabina.com/it/profumi-da-uomo/"
    "56286-kobra-for-him-eau-de-parfum-rasasi.html"
)
RASASI_URL = "https://www.sabina.com/it/631_rasasi"


def _safe(value):
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except Exception:
        return str(value)


def _inspect_data_product(soup):
    rows = []

    for node in soup.select("[data-product]"):
        raw = node.get("data-product") or ""
        low = raw.casefold()

        if not any(
            marker in low
            for marker in ("56286", "kobra", "hawas")
        ):
            continue

        item = {
            "tag": node.name,
            "class": " ".join(node.get("class", [])),
            "id": node.get("id"),
            "raw_length": len(raw),
            "raw_prefix": raw[:1000],
        }

        try:
            data = json.loads(raw)
            item["json_ok"] = True
            item["id_product"] = data.get("id_product")
            item["name"] = data.get("name")
            item["price"] = data.get("price")
            item["price_with_reduction"] = data.get(
                "price_with_reduction"
            )
            item["price_without_reduction"] = data.get(
                "price_without_reduction"
            )
            item["quantity_available"] = data.get(
                "quantity_available"
            )
            item["stock_quantity"] = data.get(
                "stock_quantity"
            )
            item["id_image"] = data.get("id_image")
        except Exception as exc:
            item["json_ok"] = False
            item["json_error"] = str(exc)

        links = []
        for a in node.select("a[href]"):
            href = sabina._clean_product_url(
                urljoin(RASASI_URL, a.get("href") or "")
            )
            if href:
                links.append(href)

        item["links_inside_node"] = list(dict.fromkeys(links))[:20]
        rows.append(item)

    return rows


def _trace_candidate(url, query):
    out = {
        "url": url,
        "query": query,
    }

    try:
        response = sabina.requests.get(
            url,
            headers=sabina.HEADERS,
            timeout=sabina.TIMEOUT,
            allow_redirects=True,
        )
        out["http_status"] = response.status_code
        out["final_url_raw"] = response.url
        html_text = response.text
        out["html_length"] = len(html_text)
        response.close()
    except Exception as exc:
        out["request_error"] = repr(exc)
        return out

    try:
        soup = BeautifulSoup(html_text, "html.parser")
        product = sabina._jsonld_product(soup)
        title = sabina._extract_product_name(product, soup)

        out["title"] = title
        out["query_matches"] = sabina._query_matches(
            title,
            sabina._clean_product_url(response.url) or url,
            query,
        )
        out["non_product_term"] = sabina._contains_non_product_term(
            title,
            sabina._clean_product_url(response.url) or url,
        )

        price, currency, source = (
            sabina._extract_price_and_currency(
                product,
                soup,
                sabina._clean_product_url(response.url) or url,
            )
        )
        out["price"] = price
        out["currency"] = currency
        out["price_source"] = source

        kobra_nodes = []
        for node in soup.select("[data-product]"):
            raw = node.get("data-product") or ""
            if "56286" not in raw:
                continue
            try:
                data = json.loads(raw)
                kobra_nodes.append({
                    "id_product": data.get("id_product"),
                    "name": data.get("name"),
                    "price": data.get("price"),
                    "price_with_reduction": data.get(
                        "price_with_reduction"
                    ),
                    "quantity_available": data.get(
                        "quantity_available"
                    ),
                    "id_image": data.get("id_image"),
                })
            except Exception as exc:
                kobra_nodes.append({
                    "json_error": str(exc),
                    "raw_prefix": raw[:500],
                })

        out["kobra_data_product"] = kobra_nodes

        # This is the decisive question: would the CURRENT scraper accept
        # this URL if discovery handed it to _extract_product_page?
        try:
            parsed = sabina._extract_product_page(url, query)
            out["extract_product_page_count"] = len(parsed)
            out["extract_product_page_rows"] = parsed[:5]
        except Exception as exc:
            out["extract_product_page_error"] = repr(exc)
            out["extract_product_page_traceback"] = traceback.format_exc()

    except Exception as exc:
        out["parse_error"] = repr(exc)
        out["parse_traceback"] = traceback.format_exc()

    return out


@router.get("/diagnose-sabina-kobra")
def diagnose_sabina_kobra(
    q: str = Query("Hawas"),
):
    result = {
        "diagnostic": "Sabina Kobra end-to-end discovery trace",
        "query": q,
        "module_file": getattr(
            sabina,
            "__file__",
            None,
        ),
        "max_candidates": getattr(
            sabina,
            "MAX_CANDIDATES",
            None,
        ),
        "kobra_url": KOBRA_URL,
        "rasasi_url": RASASI_URL,
    }

    session = sabina.requests.Session()
    session.headers.update(sabina.HEADERS)

    try:
        # 1. Run the EXACT discovery function currently used by ScentHunter.
        try:
            discovered = sabina._discover_from_first_party(
                session,
                q,
            )
            result["current_discovery"] = {
                "count": len(discovered),
                "urls": discovered,
                "kobra_in_urls": any(
                    "56286-" in str(x).lower()
                    or "kobra-for-him" in str(x).lower()
                    for x in discovered
                ),
            }
        except Exception as exc:
            result["current_discovery_error"] = repr(exc)
            result["current_discovery_traceback"] = traceback.format_exc()

        # 2. Fetch RASASI category and inspect the authoritative
        # data-product payload and links around product 56286.
        try:
            response = session.get(
                RASASI_URL,
                timeout=sabina.TIMEOUT,
                allow_redirects=True,
            )
            result["rasasi_http_status"] = response.status_code
            result["rasasi_final_url"] = response.url
            html_text = response.text
            result["rasasi_html_length"] = len(html_text)
            response.close()

            soup = BeautifulSoup(html_text, "html.parser")
            result["rasasi_kobra_data_products"] = (
                _inspect_data_product(soup)
            )

            # Compare Sabina's generic query-link extractor with a direct
            # search for Kobra inside the same category HTML.
            try:
                generic_links = (
                    sabina._extract_product_links_from_html(
                        html_text,
                        q,
                    )
                )
                result["rasasi_generic_hawas_links"] = generic_links
                result["rasasi_generic_contains_kobra"] = any(
                    "56286-" in str(x).lower()
                    or "kobra-for-him" in str(x).lower()
                    for x in generic_links
                )
            except Exception as exc:
                result["rasasi_generic_extractor_error"] = repr(exc)

        except Exception as exc:
            result["rasasi_request_error"] = repr(exc)
            result["rasasi_traceback"] = traceback.format_exc()

        # 3. Force the confirmed URL through the CURRENT parser.
        # If this succeeds while step 1 lacks Kobra, discovery is the
        # definitive bottleneck.
        result["forced_url_trace"] = _trace_candidate(
            KOBRA_URL,
            q,
        )

        # 4. Explicitly test the exact query gate conditions.
        try:
            final_url = KOBRA_URL
            title = "RASASI Kobra For Him"
            result["gate_test"] = {
                "query_norm": sabina._norm(q),
                "url_norm": sabina._norm(final_url),
                "query_matches": sabina._query_matches(
                    title,
                    final_url,
                    q,
                ),
                "contains_kobra_slug": (
                    "56286-kobra-for-him"
                    in sabina._norm(final_url)
                ),
            }
        except Exception as exc:
            result["gate_test_error"] = repr(exc)

    finally:
        session.close()

    return _safe(result)
