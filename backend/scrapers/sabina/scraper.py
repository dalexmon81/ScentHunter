import json, re, sys
from urllib.parse import quote_plus, urljoin
import requests
from bs4 import BeautifulSoup

STORE = "Sabina"
BASE = "https://www.sabina.com"
TIMEOUT = 8
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
}

def log(msg):
    print(f"SABINA_DIAG: {msg}", flush=True)

def clean(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()

def norm(v):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", clean(v).lower())).strip()

def toks(v):
    return [x for x in norm(v).split() if len(x) > 1]

def matches(text, q):
    qt = set(toks(q))
    return bool(qt) and qt.issubset(set(toks(text)))

def parse_price(v):
    text = clean(v)
    if re.fullmatch(r"\d+(?:[.,]\d{1,2})?", text):
        return float(text.replace(",", "."))
    m = re.search(
        r"(?<![\d.,])(\d{1,4}(?:[.,]\d{2}))\s*(?:€|EUR)|"
        r"(?:€|EUR)\s*(\d{1,4}(?:[.,]\d{2}))",
        text, re.I
    )
    if not m:
        return None
    return float(next(x for x in m.groups() if x).replace(",", "."))

def product_from_html(url, query, html):
    soup = BeautifulSoup(html, "html.parser")

    h1 = soup.find("h1")
    name = clean(h1.get_text(" ", strip=True)) if h1 else ""

    log(f"PRODUCT_PAGE url={url}")
    log(f"PRODUCT_H1 name={name!r}")
    log(f"PRODUCT_QUERY_MATCH={matches(name, query)}")

    if not name:
        log("PRODUCT_REJECT reason=no_h1")
        return None

    if not matches(name, query):
        log("PRODUCT_REJECT reason=h1_query_mismatch")
        return None

    price = None
    jsonld_blocks = soup.select('script[type="application/ld+json"]')
    log(f"PRODUCT_JSONLD_BLOCKS={len(jsonld_blocks)}")

    for script in jsonld_blocks:
        try:
            data = json.loads(script.get_text(strip=True))
        except Exception:
            continue

        stack = data if isinstance(data, list) else [data]

        while stack:
            x = stack.pop(0)

            if isinstance(x, list):
                stack.extend(x)
                continue
            if not isinstance(x, dict):
                continue

            offers = x.get("offers")
            offers = offers if isinstance(offers, list) else [offers]

            for offer in offers:
                if isinstance(offer, dict):
                    candidate = parse_price(offer.get("price"))
                    log(
                        f"JSONLD_OFFER price_raw={offer.get('price')!r} "
                        f"parsed={candidate!r}"
                    )
                    if candidate is not None:
                        price = candidate
                        break

            if price is not None:
                break

    if price is None:
        page_text = soup.get_text(" ", strip=True)
        price = parse_price(page_text)
        log(f"PAGE_TEXT_PRICE parsed={price!r}")

    if price is None:
        log("PRODUCT_REJECT reason=no_price")
        return None

    log(f"PRODUCT_ACCEPT name={name!r} price={price:.2f}")

    return {
        "store": STORE,
        "source": {
            "source_name": name,
            "source_brand": None,
            "url": url,
            "image": None,
        },
        "identity": {
            "gtin": None,
            "mpn": None,
            "sku": None,
            "store_product_id": None,
            "store_variant_id": None,
        },
        "attributes": {},
        "offer": {
            "price": round(price, 2),
            "currency": "EUR",
            "availability": "unknown",
        },
        "provenance": {
            "source_page": url,
            "name_source": "h1",
            "price_source": "jsonld_or_page",
        },
        "raw_data": {},
        "name": name,
        "price": f"{price:.2f}".replace(".", ",") + " €",
        "url": url,
        "available": True,
    }

def search(query):
    query = clean(query)
    log(f"START query={query!r}")
    log(f"QUERY_TOKENS={toks(query)}")

    if not query:
        log("STOP reason=empty_query")
        return []

    session = requests.Session()
    results = []
    seen = set()

    search_urls = [
        BASE + "/it/ricerca?search_query=" + quote_plus(query),
        BASE + "/it/ricerca_old?s=" + quote_plus(query),
    ]

    try:
        for search_url in search_urls:
            log(f"SEARCH_REQUEST url={search_url}")

            try:
                r = session.get(search_url, headers=HEADERS, timeout=TIMEOUT)
            except requests.RequestException as e:
                log(f"SEARCH_ERROR type={type(e).__name__} error={e}")
                continue

            log(
                f"SEARCH_RESPONSE status={r.status_code} "
                f"final_url={r.url} content_type={r.headers.get('content-type','')} "
                f"bytes={len(r.content)}"
            )

            if r.status_code >= 400:
                log("SEARCH_SKIP reason=http_error")
                continue

            soup = BeautifulSoup(r.text, "html.parser")
            anchors = soup.select("a[href]")
            log(f"SEARCH_ANCHORS total={len(anchors)}")

            raw_urls = []
            matched_urls = []

            for a in anchors:
                href = clean(a.get("href"))
                if not href:
                    continue

                url = urljoin(BASE, href).split("?")[0]
                anchor_text = clean(a.get_text(" ", strip=True))
                haystack = anchor_text + " " + url

                if url in seen:
                    continue

                raw_urls.append(url)

                if matches(haystack, query):
                    matched_urls.append((url, anchor_text))
                else:
                    if len(raw_urls) <= 20:
                        log(
                            f"ANCHOR_REJECT_QUERY url={url} "
                            f"text={anchor_text!r}"
                        )

            log(f"SEARCH_UNIQUE_URLS={len(raw_urls)}")
            log(f"SEARCH_QUERY_MATCH_URLS={len(matched_urls)}")

            for url, anchor_text in matched_urls[:30]:
                seen.add(url)
                log(f"CANDIDATE_ACCEPT url={url} anchor={anchor_text!r}")

                try:
                    p = session.get(url, headers=HEADERS, timeout=TIMEOUT)
                except requests.RequestException as e:
                    log(
                        f"PRODUCT_REQUEST_ERROR url={url} "
                        f"type={type(e).__name__} error={e}"
                    )
                    continue

                log(
                    f"PRODUCT_RESPONSE status={p.status_code} "
                    f"final_url={p.url} bytes={len(p.content)}"
                )

                if p.status_code != 200:
                    log(f"PRODUCT_SKIP reason=http_{p.status_code}")
                    continue

                item = product_from_html(url, query, p.text)
                if item:
                    results.append(item)

                if len(results) >= 20:
                    break

            if results:
                break

        log(f"COMPLETE results={len(results)}")

        if not results:
            log(
                "DIAGNOSIS_NO_RESULT: "
                "se il log mostra SEARCH_QUERY_MATCH_URLS=0, "
                "il problema è nella discovery della pagina ricerca; "
                "se >0 ma PRODUCT_REJECT, il problema è nella pagina prodotto/"
                "validazione; se SEARCH_ERROR/HTTP_ERROR, è accesso a Sabina."
            )

        return results

    finally:
        session.close()

def scrape(query):
    return search(query)

if __name__ == "__main__":
    query = " ".join(sys.argv[1:]).strip() or "Liquid brun"
    result = search(query)
    print(json.dumps(result, ensure_ascii=False, indent=2))
