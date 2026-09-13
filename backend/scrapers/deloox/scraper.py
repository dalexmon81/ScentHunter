"""ScentHunter - Deloox fast scraper.

First-party Deloox discovery is used directly. Search/category pages already
contain product cards with names, sizes and prices, so product pages are only
used as a fallback when a card is incomplete. This avoids the old pattern of
fetching up to 12 product pages (with retries) serially in batches.
"""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

STORE = "Deloox"
BASE = "https://www.deloox.com"
TIMEOUT = (2.0, 5.0)
MAX_CANDIDATES = 8
MAX_RESULTS = 40

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}

SIZE_RE = re.compile(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b", re.I)
NON_FRAGRANCE = ("body mist", "body spray", "body lotion", "body cream", "deodorant", "after shave", "aftershave", "shower gel", "soap", "hair mist")
PRICE_RE = re.compile(r"(?:€\s*)?(\d{1,4}[.,]\d{2})(?:\s*€)?")


def clean(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()


def norm(v):
    return re.sub(r"[^a-z0-9]+", " ", clean(v).lower()).strip()


def tokens(v):
    return {x for x in norm(v).split() if len(x) > 1}


def size_ml(*values):
    m = SIZE_RE.search(" ".join(clean(x) for x in values if x))
    if not m:
        return None
    n = float(m.group(1).replace(",", "."))
    if m.group(2).lower() == "cl":
        n *= 10
    return int(n) if n.is_integer() else n


def price_num(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return round(float(v), 2)
    text = clean(v).replace("\xa0", " ")
    matches = PRICE_RE.findall(text)
    for raw in matches:
        try:
            n = float(raw.replace(",", "."))
        except ValueError:
            continue
        if 0 < n < 10000:
            return round(n, 2)
    return None


def price_text(v):
    n = price_num(v)
    return f"{n:.2f}".replace(".", ",") + " €" if n is not None else None


def availability(value):
    text = norm(value)
    if any(x in text for x in ("out of stock", "outofstock", "sold out", "soldout", "unavailable", "not available")):
        return "out_of_stock"
    if any(x in text for x in ("in stock", "instock", "available", "add to cart", "in winkelwagen")):
        return "in_stock"
    return None


def get(session, url):
    print(f"[DELOOX-DIAG] HTTP START url={url}", flush=True)
    started = time.perf_counter()
    # One quick retry is enough. The old three-attempt/8.5s request budget was
    # the main reason Deloox could consume the whole 75s store timeout.
    for attempt in range(2):
        try:
            r = session.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
            elapsed = time.perf_counter() - started
            print(f"[DELOOX-DIAG] HTTP END attempt={attempt+1} status={r.status_code} elapsed={elapsed:.3f}s bytes={len(r.content)} final_url={r.url}", flush=True)
            if r.status_code == 200 and r.text:
                return r
            if r.status_code not in (429, 500, 502, 503, 504):
                return None
        except requests.RequestException as exc:
            elapsed = time.perf_counter() - started
            print(f"[DELOOX-DIAG] HTTP ERROR attempt={attempt+1} elapsed={elapsed:.3f}s type={type(exc).__name__} error={exc}", flush=True)
        if attempt == 0:
            time.sleep(0.35)
    return None


def is_product_url(url):
    try:
        p = urlparse(url)
    except Exception:
        return False
    host = p.netloc.lower().split(":", 1)[0]
    if not re.fullmatch(r"(?:www\.)?deloox\.(?:com|nl|es|fr|de|it|be)", host):
        return False
    return bool(re.search(r"/(?:product|produit|producto)/\d+/", p.path, re.I))


def product_url(raw):
    url = urljoin(BASE + "/", clean(raw)).split("#", 1)[0].split("?", 1)[0]
    return url if is_product_url(url) else ""


def relevant(text, query):
    q = tokens(query)
    hay = norm(text)
    if not q:
        return False
    hits = sum(t in hay for t in q)
    return hits >= (1 if len(q) == 1 else max(2, len(q) - 1))


def non_fragrance(text):
    t = norm(text)
    return any(norm(x) in t for x in NON_FRAGRANCE)


def jsonld_products(soup):
    out = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.get_text())
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop(0)
            if isinstance(item, list):
                stack.extend(item)
                continue
            if not isinstance(item, dict):
                continue
            typ = item.get("@type")
            if typ == "Product" or (isinstance(typ, list) and "Product" in typ):
                out.append(item)
            if isinstance(item.get("@graph"), list):
                stack.extend(item["@graph"])
    return out


def _candidate_contexts(html, query):
    soup = BeautifulSoup(html, "html.parser")
    q = tokens(query)
    found = {}

    for a in soup.find_all("a", href=True):
        url = product_url(a.get("href"))
        if not url:
            continue
        node = a
        best = clean(a.get_text(" ", strip=True))
        for _ in range(7):
            node = node.parent
            if not node:
                break
            text = clean(node.get_text(" ", strip=True))
            if len(text) > len(best) and len(text) <= 1800:
                best = text
            if PRICE_RE.search(text):
                break
        blob = norm(best + " " + url)
        hits = sum(t in blob for t in q)
        if q and hits == 0:
            continue
        old = found.get(url)
        score = hits * 10 + (2 if PRICE_RE.search(best) else 0)
        if old is None or score > old[0]:
            found[url] = (score, best)

    return sorted(found.items(), key=lambda x: (-x[1][0], len(x[0]), x[0]))[:MAX_CANDIDATES]


def _row_from_card(url, context, query):
    diag_reason = None
    if not relevant(context + " " + url, query):
        print(f"[DELOOX-DIAG] CARD REJECT reason=not_relevant url={url} context={context[:500]!r}", flush=True)
        return None
    if non_fragrance(context):
        print(f"[DELOOX-DIAG] CARD REJECT reason=non_fragrance url={url} context={context[:500]!r}", flush=True)
        return None
    # Prefer a product-like line from the card over the whole card text.
    lines = [clean(x) for x in re.split(r"\n|(?=Delivery time\s*:)|(?=our price\s)|(?=onze prijs\s)|(?=nostro prezzo\s)", context) if clean(x)]
    name = ""
    for line in lines:
        if relevant(line, query) and not re.search(r"delivery time|besteld|prijs|price|cart|winkelwagen|in stock|available", norm(line)):
            if 3 <= len(line) <= 220:
                name = line
                break
    if not name:
        name = query
    size = size_ml(name, context)
    n = price_num(context)
    if n is None:
        print(f"[DELOOX-DIAG] CARD REJECT reason=no_price url={url} name={name!r} context={context[:700]!r}", flush=True)
        return None
    print(f"[DELOOX-DIAG] CARD ACCEPT url={url} name={name!r} price={n} size_ml={size_ml(name, context)} availability={availability(context)!r}", flush=True)
    state = availability(context)
    return {
        "store": STORE,
        "brand": "",
        "name": name,
        "price": price_text(n),
        "price_num": n,
        "url": url,
        "available": state != "out_of_stock",
        "availability": state or "in_stock",
        "size_ml": size,
    }



def _bing_discover(query):
    diag_started = time.perf_counter()
    print(f"[DELOOX-DIAG] BING START query={query!r}", flush=True)
    """Discover Deloox product pages through Bing instead of Deloox's
    current search endpoints, which can stall on Render.

    Bing results are only used to discover the first-party product URL and
    card text. If the snippet already contains a price, no product-page
    request is necessary.
    """
    url = "https://www.bing.com/search?q=" + quote_plus(
        f'site:deloox.nl/product "{query}"'
    )
    try:
        r = requests.get(url, headers=HEADERS, timeout=(2.0, 7.0), allow_redirects=True)
        print(f"[DELOOX-DIAG] BING HTTP status={r.status_code} elapsed={time.perf_counter()-diag_started:.3f}s bytes={len(r.content)} final_url={r.url}", flush=True)
        if r.status_code != 200 or not r.text:
            print("[DELOOX-DIAG] BING EMPTY_OR_NON200", flush=True)
            return []
    except requests.RequestException as exc:
        print(f"[DELOOX-DIAG] BING ERROR type={type(exc).__name__} error={exc}", flush=True)
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    print(f"[DELOOX-DIAG] BING parsed title={clean(soup.title.get_text()) if soup.title else ''!r} algo_blocks={len(soup.select('li.b_algo, div.b_algo'))}", flush=True)
    found = {}
    for block in soup.select("li.b_algo, div.b_algo"):
        a = block.select_one("h2 a, h3 a") or block.find("a", href=True)
        if not a:
            continue
        href = clean(a.get("href", ""))
        m = re.search(r"https?://(?:www\.)?deloox\.nl/product/\d+/[^&<>\"']+", href, re.I)
        if not m:
            # Bing can wrap the destination in a query parameter.
            m2 = re.search(r"[?&](?:q|url)=([^&]+)", href, re.I)
            if m2:
                href = requests.utils.unquote(m2.group(1))
            m = re.search(r"https?://(?:www\.)?deloox\.nl/product/\d+/[^&<>\"']+", href, re.I)
        if not m:
            continue
        product = product_url(m.group(0))
        if not product:
            continue
        context = clean(block.get_text(" ", strip=True))
        title = clean(a.get_text(" ", strip=True))
        if title and title not in context:
            context = clean(title + " " + context)
        if not relevant(context + " " + product, query) or non_fragrance(context):
            continue
        score = 20 + (3 if PRICE_RE.search(context) else 0)
        old = found.get(product)
        if old is None or score > old[0]:
            found[product] = (score, context)

    result = sorted(found.items(), key=lambda x: (-x[1][0], x[0]))[:MAX_CANDIDATES]
    print(f"[DELOOX-DIAG] BING END candidates={len(result)} elapsed={time.perf_counter()-diag_started:.3f}s", flush=True)
    for u, (score, ctx) in result:
        print(f"[DELOOX-DIAG] BING CANDIDATE score={score} url={u} context={ctx[:500]!r}", flush=True)
    return result

def discover(session, query):
    started = time.perf_counter()
    print(f"[DELOOX-DIAG] DISCOVER START query={query!r}", flush=True)
    # The current Deloox site can leave its internal search endpoints hanging
    # from Render. Bing is a fast discovery layer and returns first-party
    # Deloox product URLs for exact perfume searches.
    candidates = _bing_discover(query)
    if candidates:
        print(f"[DELOOX-DIAG] DISCOVER END source=bing candidates={len(candidates)} elapsed={time.perf_counter()-started:.3f}s", flush=True)
        return candidates
    print(f"[DELOOX-DIAG] BING RETURNED ZERO elapsed={time.perf_counter()-started:.3f}s", flush=True)

    # One direct Deloox search attempt as a bounded fallback. Do not iterate
    # through five endpoints: that was the source of the previous 25-45s
    # delay.
    encoded = quote_plus(query)
    for endpoint in (
        f"https://www.deloox.nl/zoeken?query={encoded}",
        f"https://www.deloox.nl/en/search?query={encoded}",
    ):
        print(f"[DELOOX-DIAG] DIRECT ENDPOINT START {endpoint}", flush=True)
        r = get(session, endpoint)
        if not r:
            print(f"[DELOOX-DIAG] DIRECT ENDPOINT NO_RESPONSE {endpoint}", flush=True)
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        print(f"[DELOOX-DIAG] DIRECT HTML title={clean(soup.title.get_text()) if soup.title else ''!r} bytes={len(r.content)} product_links={sum(1 for a in soup.find_all('a', href=True) if product_url(a.get('href')))} relevant_text={relevant(soup.get_text(' ', strip=True), query)}", flush=True)
        contexts = _candidate_contexts(r.text, query)
        print(f"[DELOOX-DIAG] DIRECT PARSED candidates={len(contexts)}", flush=True)
        for u, (score, ctx) in contexts:
            print(f"[DELOOX-DIAG] DIRECT CANDIDATE score={score} url={u} context={ctx[:500]!r}", flush=True)
        if contexts:
            print(f"[DELOOX-DIAG] DISCOVER END source=direct candidates={len(contexts)} elapsed={time.perf_counter()-started:.3f}s", flush=True)
            return contexts

    # Last bounded catalog fallback.
    for endpoint in (
        "https://www.deloox.nl/categorie/1103659/parfum.html",
        "https://www.deloox.nl/categorie/1122039/liquid-brun.html" if norm(query) == "liquid brun" else "",
    ):
        if not endpoint:
            continue
        print(f"[DELOOX-DIAG] CATEGORY START {endpoint}", flush=True)
        r = get(session, endpoint)
        if not r:
            print(f"[DELOOX-DIAG] CATEGORY NO_RESPONSE {endpoint}", flush=True)
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        print(f"[DELOOX-DIAG] CATEGORY HTML title={clean(soup.title.get_text()) if soup.title else ''!r} bytes={len(r.content)} product_links={sum(1 for a in soup.find_all('a', href=True) if product_url(a.get('href')))}", flush=True)
        contexts = _candidate_contexts(r.text, query)
        print(f"[DELOOX-DIAG] CATEGORY PARSED candidates={len(contexts)}", flush=True)
        for u, (score, ctx) in contexts:
            print(f"[DELOOX-DIAG] CATEGORY CANDIDATE score={score} url={u} context={ctx[:500]!r}", flush=True)
        if contexts:
            print(f"[DELOOX-DIAG] DISCOVER END source=category candidates={len(contexts)} elapsed={time.perf_counter()-started:.3f}s", flush=True)
            return contexts
    print(f"[DELOOX-DIAG] DISCOVER END source=none candidates=0 elapsed={time.perf_counter()-started:.3f}s", flush=True)
    return []


def parse_product(url, query):
    started = time.perf_counter()
    print(f"[DELOOX-DIAG] PRODUCT FETCH START url={url}", flush=True)
    session = requests.Session()
    try:
        r = get(session, url)
        if not r:
            print(f"[DELOOX-DIAG] PRODUCT FETCH NO_RESPONSE url={url} elapsed={time.perf_counter()-started:.3f}s", flush=True)
            return []
        soup = BeautifulSoup(r.text, "html.parser")
        rows = []
        for p in jsonld_products(soup):
            name = clean(p.get("name") or query)
            if not relevant(name, query) or non_fragrance(name):
                continue
            brand = p.get("brand")
            if isinstance(brand, dict):
                brand = brand.get("name")
            offers = p.get("offers")
            offers = offers if isinstance(offers, list) else ([offers] if isinstance(offers, dict) else [])
            for offer in offers:
                if not isinstance(offer, dict):
                    continue
                n = price_num(offer.get("price"))
                if n is None:
                    continue
                state = availability(offer.get("availability"))
                rows.append({"store": STORE, "brand": clean(brand), "name": name, "price": price_text(n), "price_num": n, "url": url, "available": state != "out_of_stock", "availability": state or "in_stock", "size_ml": size_ml(name, p.get("description", ""))})
        print(f"[DELOOX-DIAG] PRODUCT FETCH END url={url} jsonld_products={len(jsonld_products(soup))} rows={len(rows)} elapsed={time.perf_counter()-started:.3f}s", flush=True)
        return rows
    finally:
        session.close()


def search(query):
    search_started = time.perf_counter()
    print(f"[DELOOX-DIAG] SEARCH START query={query!r}", flush=True)
    query = clean(query)
    if not query:
        return []
    session = requests.Session()
    try:
        candidates = discover(session, query)
        print(f"[DELOOX-DIAG] SEARCH DISCOVERY candidates={len(candidates)} elapsed={time.perf_counter()-search_started:.3f}s", flush=True)
        for u, (score, ctx) in candidates:
            print(f"[DELOOX-DIAG] CANDIDATE FINAL score={score} url={u} context={ctx[:500]!r}", flush=True)
        results = []
        seen = set()
        # First use card data already obtained from the discovery page.
        for url, (_, context) in candidates:
            row = _row_from_card(url, context, query)
            if row:
                key = (row["url"], row.get("size_ml"), row["price_num"])
                if key not in seen:
                    seen.add(key)
                    results.append(row)

        # Only fetch product pages for candidates whose card was incomplete.
        missing = [(url, info) for url, info in candidates if not any(r.get("url") == url for r in results)]
        if missing:
            with ThreadPoolExecutor(max_workers=min(6, len(missing))) as pool:
                futures = [pool.submit(parse_product, url, query) for url, _ in missing]
                for f in as_completed(futures):
                    try:
                        for row in f.result():
                            key = (row.get("url"), row.get("size_ml"), row.get("price_num"))
                            if key not in seen:
                                seen.add(key)
                                results.append(row)
                    except Exception:
                        continue

        results.sort(key=lambda x: (2 if x.get("available") is False else 0, x.get("price_num") or 999999, x.get("size_ml") or 999999))
        final = results[:MAX_RESULTS]
        print(f"[DELOOX-DIAG] SEARCH END results={len(final)} elapsed={time.perf_counter()-search_started:.3f}s", flush=True)
        for row in final:
            print(f"[DELOOX-DIAG] RESULT name={row.get('name')!r} price={row.get('price')!r} url={row.get('url')!r} size_ml={row.get('size_ml')!r}", flush=True)
        return final
    finally:
        session.close()


def scrape(query):
    return search(query)


def search_deloox(query):
    return search(query)
def diagnose(query):
    """
    Diagnostic endpoint for Deloox.
    Does NOT call search().
    Tests DNS, Bing discovery and direct Deloox endpoints separately.
    """
    started = time.perf_counter()
    query = clean(query)

    report = {
        "diagnostic": True,
        "diagnostic_version": "deloox-root-cause-2026-09-13-v1",
        "query": query,
        "elapsed_s": 0,
        "dns": {},
        "bing": {},
        "direct": [],
        "conclusion": {},
    }

    # DNS
    try:
        import socket
        addresses = sorted({
            item[4][0]
            for item in socket.getaddrinfo(
                "www.deloox.nl",
                443,
                type=socket.SOCK_STREAM
            )
            if item[4]
        })
        report["dns"] = {
            "ok": True,
            "addresses": addresses,
        }
    except Exception as exc:
        report["dns"] = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    session = requests.Session()

    # ---------------------------------------------------------
    # BING
    # ---------------------------------------------------------
    bing_started = time.perf_counter()
    bing_url = (
        "https://www.bing.com/search?q="
        + quote_plus(f'site:deloox.nl/product "{query}"')
    )

    try:
        r = session.get(
            bing_url,
            headers=HEADERS,
            timeout=(3.0, 10.0),
            allow_redirects=True,
        )

        soup = BeautifulSoup(r.text, "html.parser")

        candidates = []

        for block in soup.select("li.b_algo, div.b_algo"):
            a = block.select_one("h2 a, h3 a") or block.find(
                "a",
                href=True
            )

            if not a:
                continue

            href = clean(a.get("href", ""))

            m = re.search(
                r"https?://(?:www\.)?deloox\.nl/product/\d+/[^&<>\"']+",
                href,
                re.I,
            )

            if not m:
                m2 = re.search(
                    r"[?&](?:q|url)=([^&]+)",
                    href,
                    re.I,
                )
                if m2:
                    href = requests.utils.unquote(m2.group(1))

                m = re.search(
                    r"https?://(?:www\.)?deloox\.nl/product/\d+/[^&<>\"']+",
                    href,
                    re.I,
                )

            if not m:
                continue

            product = product_url(m.group(0))

            if not product:
                continue

            context = clean(
                block.get_text(" ", strip=True)
            )

            candidates.append({
                "url": product,
                "title": clean(a.get_text(" ", strip=True)),
                "context": context[:1000],
            })

        report["bing"] = {
            "url": bing_url,
            "status": r.status_code,
            "elapsed_s": round(
                time.perf_counter() - bing_started,
                3,
            ),
            "html_length": len(r.content),
            "title": clean(soup.title.get_text())
            if soup.title else "",
            "candidate_count": len(candidates),
            "candidates": candidates[:10],
        }

    except Exception as exc:
        report["bing"] = {
            "url": bing_url,
            "status": None,
            "elapsed_s": round(
                time.perf_counter() - bing_started,
                3,
            ),
            "error": f"{type(exc).__name__}: {exc}",
            "candidate_count": 0,
            "candidates": [],
        }

    # ---------------------------------------------------------
    # DIRECT DELOOX ENDPOINTS
    # ---------------------------------------------------------
    encoded = quote_plus(query)

    endpoints = [
        (
            "search_nl",
            f"https://www.deloox.nl/zoeken?query={encoded}",
        ),
        (
            "search_en",
            f"https://www.deloox.nl/en/search?query={encoded}",
        ),
        (
            "category_parfum",
            "https://www.deloox.nl/categorie/1103659/parfum.html",
        ),
    ]

    if norm(query) == "liquid brun":
        endpoints.append(
            (
                "category_liquid_brun",
                "https://www.deloox.nl/categorie/1122039/liquid-brun.html",
            )
        )

    for label, url in endpoints:
        item_started = time.perf_counter()

        item = {
            "label": label,
            "url": url,
            "status": None,
            "elapsed_s": 0,
            "html_length": 0,
            "final_url": "",
            "title": "",
            "product_link_count": 0,
            "candidate_count": 0,
            "candidates": [],
            "error": None,
        }

        try:
            r = session.get(
                url,
                headers=HEADERS,
                timeout=(3.0, 8.0),
                allow_redirects=True,
            )

            item["status"] = r.status_code
            item["final_url"] = r.url
            item["html_length"] = len(r.content)

            soup = BeautifulSoup(r.text, "html.parser")

            item["title"] = (
                clean(soup.title.get_text())
                if soup.title else ""
            )

            product_links = []

            for a in soup.find_all("a", href=True):
                u = product_url(a.get("href"))

                if u:
                    product_links.append(u)

            item["product_link_count"] = len(
                set(product_links)
            )

            contexts = _candidate_contexts(
                r.text,
                query,
            )

            item["candidate_count"] = len(contexts)

            for u, (score, context) in contexts[:10]:
                item["candidates"].append({
                    "url": u,
                    "score": score,
                    "context": context[:1000],
                })

        except Exception as exc:
            item["error"] = (
                f"{type(exc).__name__}: {exc}"
            )

        item["elapsed_s"] = round(
            time.perf_counter() - item_started,
            3,
        )

        report["direct"].append(item)

    # ---------------------------------------------------------
    # CONCLUSION
    # ---------------------------------------------------------
    bing_candidates = report["bing"].get(
        "candidate_count",
        0,
    )

    direct_candidates = sum(
        int(x.get("candidate_count") or 0)
        for x in report["direct"]
    )

    direct_200 = sum(
        1
        for x in report["direct"]
        if x.get("status") == 200
    )

    direct_errors = [
        x
        for x in report["direct"]
        if x.get("error")
    ]

    direct_statuses = [
        {
            "label": x["label"],
            "status": x["status"],
            "elapsed_s": x["elapsed_s"],
        }
        for x in report["direct"]
    ]

    if bing_candidates > 0:
        code = "BING_DISCOVERY_WORKS"

        cause = (
            "Bing returns first-party Deloox product URLs. "
            "The failure, if any, is therefore after discovery."
        )

    elif direct_candidates > 0:
        code = "DIRECT_DISCOVERY_WORKS"

        cause = (
            "Bing returns no usable Deloox candidates, "
            "but direct Deloox pages expose product candidates."
        )

    elif direct_200 > 0:
        code = "DELOOX_REACHABLE_BUT_PARSER_SEES_NO_PRODUCTS"

        cause = (
            "Render can reach Deloox with HTTP 200, "
            "but the current HTML does not expose usable "
            "product candidates."
        )

    elif direct_errors:
        code = "DELOOX_REQUEST_ERRORS"

        cause = (
            "One or more direct Deloox requests failed at "
            "the network/request level."
        )

    else:
        code = "DELOOX_BLOCKED_OR_UNREACHABLE"

        cause = (
            "Neither Bing nor the direct Deloox endpoints "
            "produced usable product candidates."
        )

    report["conclusion"] = {
        "code": code,
        "cause": cause,
        "evidence": {
            "bing_candidate_count": bing_candidates,
            "direct_200_pages": direct_200,
            "direct_candidate_count": direct_candidates,
            "direct_statuses": direct_statuses,
        },
    }

    report["elapsed_s"] = round(
        time.perf_counter() - started,
        3,
    )

    return report    
