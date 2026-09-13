from __future__ import annotations

import html
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

STORE = "Easycosmetic"
MACHINE_STORE = "notino"  # compatibility key: main.py remains untouched
BASE_URL = "https://www.easycosmetic.de"
SEARCH_URL = BASE_URL + "/suche?searchfor={}"
TIMEOUT = 8
SCRAPER_VERSION = "easycosmetic-replacement-2026-09-13-v1"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
}

PRICE_RE = re.compile(r"(?:€\s*)?(\d{1,4}[.,]\d{2})\s*€?", re.I)
SIZE_RE = re.compile(r"\b(\d{1,4}(?:[.,]\d{1,2})?)\s*(ml|cl|l|g|kg)\b", re.I)

NON_PERFUME = {
    "gift set", "geschenkset", "set", "coffret", "bundle", "duo", "trio",
    "shampoo", "duschgel", "body lotion", "körperlotion", "deodorant",
    "deo spray", "after shave", "rasur", "make-up", "makeup", "skincare",
    "hautpflege", "haare", "hair", "accessoire", "zerstäuber",
    "taschenzerstäuber",
}


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _clean(value).lower()).strip()


def _query_tokens(query: str) -> List[str]:
    return [x for x in _norm(query).split() if len(x) > 1]


def _matches(text: str, query: str) -> bool:
    hay = _norm(text)
    tokens = _query_tokens(query)
    return bool(tokens) and all(token in hay for token in tokens)


def _is_non_perfume(text: str) -> bool:
    hay = _norm(text)
    return any(marker in hay for marker in NON_PERFUME)


def _product_url(url: str) -> Optional[str]:
    try:
        absolute = urljoin(BASE_URL, url).split("?")[0].rstrip("/")
        p = urlparse(absolute)
    except Exception:
        return None

    if p.netloc.lower() not in {"easycosmetic.de", "www.easycosmetic.de"}:
        return None

    path = p.path.lower()
    if not path.endswith(".aspx"):
        return None

    parts = [x for x in p.path.split("/") if x]
    if len(parts) < 3:
        return None

    if any(x in path for x in ("/suche", "/sale", "/faq")):
        return None

    return absolute


def _price_number(value: Any) -> Optional[float]:
    text = _clean(value).replace("\xa0", " ")
    matches = list(PRICE_RE.finditer(text))
    if not matches:
        return None

    raw = matches[-1].group(1).replace(".", "").replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def _size_ml(text: str) -> Optional[float]:
    matches = list(SIZE_RE.finditer(_clean(text)))
    if not matches:
        return None

    number, unit = matches[-1].groups()
    try:
        n = float(number.replace(",", "."))
    except ValueError:
        return None

    unit = unit.lower()
    if unit == "cl":
        return n * 10
    if unit == "l":
        return n * 1000
    return n if unit == "ml" else None


def _card_context(anchor) -> str:
    node = anchor
    best = _clean(anchor.get_text(" ", strip=True))

    for _ in range(5):
        node = node.parent
        if not node:
            break

        text = _clean(node.get_text(" ", strip=True))
        if len(text) > len(best) and len(text) < 1800:
            best = text

        if any(x in text.lower() for x in ("€", "ml", "auf lager", "verfügbar")):
            best = text
            break

    return best


def _search_candidates(
    session: requests.Session, query: str
) -> tuple[List[Dict[str, str]], Dict[str, Any]]:

    url = SEARCH_URL.format(quote_plus(query))
    report: Dict[str, Any] = {
        "url": url,
        "status": None,
        "candidate_count": 0,
        "error": None,
    }

    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        report["status"] = response.status_code
        report["final_url"] = response.url
        report["html_length"] = len(response.text or "")
        response.raise_for_status()
    except requests.RequestException as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        return [], report

    soup = BeautifulSoup(response.text or "", "html.parser")
    candidates: Dict[str, Dict[str, str]] = {}

    for anchor in soup.find_all("a", href=True):
        href = _product_url(anchor.get("href", ""))
        if not href:
            continue

        context = _card_context(anchor)

        if not _matches(context, query):
            continue

        if _is_non_perfume(context):
            continue

        title = _clean(anchor.get_text(" ", strip=True))

        if not title or title.lower() in {"zum produkt", "produkt"}:
            title = context

        candidates[href] = {
            "url": href,
            "title": title,
            "context": context,
        }

    report["candidate_count"] = len(candidates)
    return list(candidates.values())[:12], report


def _jsonld_product(soup: BeautifulSoup) -> Optional[Dict[str, Any]]:
    for script in soup.find_all(
        "script", attrs={"type": "application/ld+json"}
    ):
        raw = script.string or script.get_text()

        if not raw:
            continue

        try:
            data = json.loads(raw)
        except Exception:
            continue

        objects = data if isinstance(data, list) else [data]

        for obj in objects:
            if not isinstance(obj, dict):
                continue

            if str(obj.get("@type", "")).lower() == "product":
                return obj

            graph = obj.get("@graph")
            if isinstance(graph, list):
                for item in graph:
                    if (
                        isinstance(item, dict)
                        and str(item.get("@type", "")).lower() == "product"
                    ):
                        return item

    return None


def _extract_brand(
    name: str, data: Optional[Dict[str, Any]], url: str
) -> str:

    if data:
        brand = data.get("brand")

        if isinstance(brand, dict):
            brand = brand.get("name")

        if brand:
            return _clean(brand)

    parts = [x for x in urlparse(url).path.split("/") if x]

    if parts:
        return _clean(parts[0].replace("-", " "))

    return _clean(name.split(" ", 1)[0] if name else "")


def _product_page(
    session: requests.Session,
    candidate: Dict[str, str],
    query: str,
) -> Optional[Dict[str, Any]]:

    url = candidate["url"]

    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )

        if not response.ok or not response.text:
            return None

    except requests.RequestException:
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    data = _jsonld_product(soup)

    h1 = soup.find("h1")

    name = (
        _clean((data or {}).get("name") if data else "")
        or _clean(h1.get_text(" ", strip=True) if h1 else "")
        or candidate["title"]
    )

    if not _matches(name + " " + candidate.get("context", ""), query):
        return None

    if _is_non_perfume(name):
        return None

    offers = (data or {}).get("offers") if data else None

    if isinstance(offers, list):
        offers = offers[0] if offers else None

    price = None
    availability = ""

    if isinstance(offers, dict):
        price = _price_number(offers.get("price"))
        availability = _clean(offers.get("availability"))

    page_text = _clean(soup.get_text(" ", strip=True))

    if price is None:
        price = _price_number(page_text)

    size = _size_ml(name + " " + page_text[:2000])

    available = bool(
        price is not None
        and (
            "instock" in availability.lower()
            or "auf lager" in page_text.lower()
            or "in den warenkorb" in page_text.lower()
        )
    )

    if (
        "outofstock" in availability.lower()
        or "nicht verfügbar" in page_text.lower()
    ):
        available = False

    brand = _extract_brand(name, data, url)

    return {
        "store": MACHINE_STORE,
        "shop": STORE,
        "brand": brand,
        "name": name,
        "price": (
            f"{price:.2f}".replace(".", ",") + " €"
            if price is not None
            else ""
        ),
        "price_num": price,
        "size_ml": size,
        "url": url,
        "available": available,
        "source": "easycosmetic-search",
    }


def search(query: str) -> List[Dict[str, Any]]:
    query = _clean(query)

    if not query:
        return []

    session = requests.Session()

    try:
        candidates, _report = _search_candidates(session, query)
    finally:
        session.close()

    if not candidates:
        return []

    def fetch(candidate: Dict[str, str]) -> Optional[Dict[str, Any]]:
        local = requests.Session()

        try:
            return _product_page(local, candidate, query)
        finally:
            local.close()

    results: List[Dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=min(6, len(candidates))) as pool:
        futures = [pool.submit(fetch, candidate) for candidate in candidates]

        for future in as_completed(futures):
            try:
                row = future.result()
            except Exception:
                row = None

            if isinstance(row, dict):
                results.append(row)

    unique: Dict[str, Dict[str, Any]] = {}

    for row in results:
        unique[row["url"]] = row

    results = list(unique.values())

    results.sort(
        key=lambda x: (
            x.get("price_num")
            if isinstance(x.get("price_num"), (int, float))
            else 999999
        )
    )

    return results[:8]


def _browser_search(query: str):
    # Compatibility stub for the existing debug_notino import.
    return [], {
        "engine": "easycosmetic-requests",
        "status": None,
        "candidate_count": 0,
        "error": "browser_path_not_used",
        "elapsed_s": 0.0,
    }


def diagnose(query: str) -> Dict[str, Any]:
    query = _clean(query)
    started = time.monotonic()

    session = requests.Session()

    try:
        candidates, discovery = _search_candidates(session, query)
    finally:
        session.close()

    return {
        "diagnostic": True,
        "diagnostic_version": SCRAPER_VERSION,
        "query": query,
        "elapsed_s": round(time.monotonic() - started, 3),
        "discovery": discovery,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }


def diagnose_ab(query: str) -> Dict[str, Any]:
    return diagnose(query)
