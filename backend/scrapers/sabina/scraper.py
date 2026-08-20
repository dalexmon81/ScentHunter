import json
import re
import html as html_lib
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

STORE = "Sabina"
BASE = "https://www.sabina.com"
TIMEOUT = 6
MAX_CATALOG_PAGES = 40
MAX_CATALOG_CATEGORIES = 8
MAX_SIZE_ENRICH_REQUESTS = 6

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
        "Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Referer": BASE + "/it/",
}

PRICE_RE = re.compile(r"(?<!\d)(\d{1,4}(?:[.,]\d{2}))\s*€")
PRODUCT_URL_RE = re.compile(
    r"^https?://(?:www\.)?sabina\.com/it/(?!"
    r"(?:content|ricerca|ricerca_old|marchi|negozi|contatto|faq|"
    r"carrello|ordine|stato-ordine|il-mio-conto|module)/)"
)

def _clean(value):
    return re.sub(r"\s+", " ", html_lib.unescape(value or "")).strip()

def _price(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return f"{float(value):.2f}".replace(".", ",") + " €"
    text = _clean(str(value))
    m = PRICE_RE.search(text)
    if not m:
        m = re.search(r"(?<!\d)(\d{1,4}(?:[.,]\d{2}))(?!\d)", text)
    if not m:
        return None
    return m.group(1).replace(".", ",") + " €"

def _looks_like_product_url(url):
    return bool(url and PRODUCT_URL_RE.match(url))

def _get(session, url, **kwargs):
    r = session.get(
        url,
        headers=HEADERS,
        timeout=TIMEOUT,
        allow_redirects=True,
        **kwargs,
    )
    if r.status_code in (403, 429):
        r.close()
        return None
    r.raise_for_status()
    return r

def _query_without_size(query):
    return _clean(re.sub(r"(?<!\d)\d{2,4}\s*ml\b", " ", query, flags=re.I))

def _query_words(query):
    return [
        w.lower()
        for w in re.findall(r"[a-z0-9À-ÿ]+", _clean(query).lower())
        if len(w) > 1 and w != "ml" and not w.isdigit()
    ]

def _extract_variants_from_html(text):
    if not text:
        return []

    soup = BeautifulSoup(text, "html.parser")
    variants = {}

    def add(size, price):
        if not size or price in (None, ""):
            return
        p = _price(price)
        if not p:
            return
        number = float(re.search(r"\d+[.,]\d+", p).group(0).replace(",", "."))
        current = variants.get(str(size))
        if current is None or number < current[0]:
            variants[str(size)] = (number, p)

    def current_price(value):
        value = _clean(value)
        matches = list(re.finditer(r"(?<!\d)(\d{1,4}(?:[.,]\d{2}))\s*€", value))
        usable = []
        for m in matches:
            suffix = value[m.end():m.end()+30].lower()
            prefix = value[max(0, m.start()-50):m.start()].lower()
            if re.match(r"\s*(?:/|par|pour)\s*\d+\s*ml\b", suffix):
                continue
            if re.search(r"(?:/|par|pour)\s*\d+\s*ml\s*$", prefix):
                continue
            usable.append(m.group(1))
        if not usable:
            return None
        return min(usable, key=lambda x: float(x.replace(",", ".")))

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.get_text(strip=True))
        except Exception:
            continue

        def walk(obj):
            if isinstance(obj, dict):
                low = {str(k).lower(): v for k, v in obj.items()}
                size = None
                for key in ("size", "volume", "netcontent", "capacity", "contentvolume", "description", "name"):
                    if key in low:
                        m = re.search(r"(?<!\d)(\d{2,4})\s*ml\b", str(low[key]), re.I)
                        if m:
                            size = m.group(1)
                            break
                price = next(
                    (low[k] for k in (
                        "final_price", "finalprice", "sale_price", "saleprice",
                        "price_amount", "priceamount", "price"
                    ) if k in low and low[k] not in (None, "")),
                    None,
                )
                if size and price:
                    add(size, price)
                for value in obj.values():
                    walk(value)
            elif isinstance(obj, list):
                for value in obj:
                    walk(value)

        walk(data)

    for el in soup.find_all(["option", "label", "li", "button", "span", "div"]):
        txt = _clean(el.get_text(" ", strip=True))
        if not txt or len(txt) > 700:
            continue
        sizes = re.findall(r"(?<!\d)(\d{2,4})\s*ml\b", txt, re.I)
        if len(sizes) == 1:
            p = current_price(txt)
            if p:
                add(sizes[0], p)

    visible = _clean(soup.get_text(" ", strip=True))
    for m in re.finditer(r"(?<!\d)(\d{2,4})\s*ml\b", visible, re.I):
        size = m.group(1)
        p = current_price(visible[max(0, m.start()-180):m.start()+220])
        if p:
            add(size, p)

    return [
        {"size_ml": size, "price": price}
        for size, (_, price) in sorted(
            variants.items(),
            key=lambda x: int(x[0]) if x[0].isdigit() else 99999,
        )
    ]

def _extract_name(container, anchor):
    candidates = []
    for sel in ("h1", "h2", "h3", "h4", ".name", ".product-name", ".product-title"):
        el = container.select_one(sel)
        if el:
            candidates.append(el.get_text(" ", strip=True))
    candidates += [
        anchor.get("title"),
        anchor.get("aria-label"),
        anchor.get_text(" ", strip=True),
    ]
    for value in candidates:
        value = _clean(value)
        if value and value.lower() not in {"vedi", "vedi tutto", "acquista", "immagine"}:
            return value
    return ""

def _parse_html(text, query):
    soup = BeautifulSoup(text, "html.parser")
    rows = []
    words = _query_words(query)

    for anchor in soup.find_all("a", href=True):
        url = urljoin(BASE, anchor["href"])
        if not _looks_like_product_url(url):
            continue

        container = anchor
        for _ in range(8):
            parent = getattr(container, "parent", None)
            if not parent:
                break
            candidate = parent
            block = _clean(candidate.get_text(" ", strip=True))
            if len(block) <= 1800 and ("€" in block or "ML" in block.upper()):
                container = candidate
                break
            container = candidate

        block = _clean(container.get_text(" ", strip=True))
        name = _extract_name(container, anchor)
        if not name:
            continue

        low_name = name.lower()
        if words and not all(word in low_name for word in words):
            continue

        prices = []
        for m in PRICE_RE.finditer(block):
            suffix = block[m.end():m.end()+30].lower()
            if re.match(r"\s*(?:/|par|pour)\s*\d+\s*ml\b", suffix):
                continue
            prices.append(m.group(1) + " €")
        if not prices:
            continue

        size = ""
        msize = re.search(r"(?<!\d)(\d{2,4})\s*ml\b", block, re.I)
        if msize:
            size = msize.group(1)

        rows.append({
            "store": STORE,
            "name": name,
            "price": prices[0],
            "url": url.split("#")[0],
            **({"size_ml": size} if size else {}),
        })

    out, seen = [], set()
    for row in rows:
        key = (
            row["name"].lower(),
            row["url"].split("?")[0],
            row.get("size_ml", ""),
        )
        if key not in seen:
            seen.add(key)
            out.append(row)
    return out

def _walk_json(obj, query):
    rows = []
    words = _query_words(query)

    def walk(value):
        if isinstance(value, dict):
            low = {str(k).lower(): v for k, v in value.items()}
            name = next(
                (low[k] for k in ("name", "product_name", "productname", "title", "label")
                 if k in low and isinstance(low[k], (str, int, float))),
                None,
            )
            url = next(
                (low[k] for k in ("url", "link", "product_url", "producturl", "href")
                 if k in low and isinstance(low[k], str)),
                None,
            )
            price = next(
                (low[k] for k in (
                    "price", "final_price", "finalprice", "sale_price",
                    "saleprice", "price_amount", "priceamount"
                ) if k in low),
                None,
            )
            if url:
                url = urljoin(BASE, url)
            if (
                name and url and _looks_like_product_url(url)
                and _price(price)
                and (not words or all(word in str(name).lower() for word in words))
            ):
                rows.append({
                    "store": STORE,
                    "name": str(name),
                    "price": price,
                    "url": url,
                })
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(obj)
    return rows

def _enrich_product_sizes(session, rows, query):
    requested = ""
    m = re.search(r"(?<!\d)(\d{2,4})\s*ml\b", query, re.I)
    if m:
        requested = m.group(1)

    cache = {}
    requests_used = 0
    out = []

    for row in rows:
        item = dict(row)
        url = item.get("url", "")
        existing = re.search(r"\b(\d{1,4})\s*ml\b", item.get("name", ""), re.I)

        if existing and not requested:
            item["size_ml"] = existing.group(1)
            out.append(item)
            continue

        if url not in cache and requests_used < MAX_SIZE_ENRICH_REQUESTS:
            requests_used += 1
            try:
                r = _get(session, url)
                cache[url] = _extract_variants_from_html(r.text) if r else []
                if r:
                    r.close()
            except Exception:
                cache[url] = []

        variants = cache.get(url, [])
        if requested:
            selected = next((v for v in variants if v["size_ml"] == requested), None)
            if not selected:
                continue
            item["size_ml"] = selected["size_ml"]
            item["price"] = selected["price"]
        elif variants:
            item["size_ml"] = variants[0]["size_ml"]
            item["price"] = variants[0]["price"]

        out.append(item)

    return out

def _category_page_urls(session):
    urls = []
    seen = set()
    try:
        r = _get(session, BASE + "/it/")
        if r is None:
            return []
        html = r.text
        r.close()
    except Exception:
        return []

    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        url = urljoin(BASE, a["href"])
        low = url.lower()
        if "/it/" not in low:
            continue
        if "profum" not in low and "perfume" not in low:
            continue
        if _looks_like_product_url(url):
            continue
        path = url.split("?", 1)[0].rstrip("/")
        if path not in seen:
            seen.add(path)
            urls.append(path)

    return urls[:MAX_CATALOG_CATEGORIES]

def _catalog_fallback(session, query):
    categories = _category_page_urls(session)
    if not categories:
        return []

    # Fetch category pages in small batches. We stop as soon as the requested
    # product is found; no product-specific seed or exception is used.
    def fetch_page(url):
        local = requests.Session()
        local.headers.update(HEADERS)
        try:
            r = _get(local, url)
            if r is None:
                return url, "", False
            text = r.text
            r.close()
            return url, text, True
        except Exception:
            return url, "", False
        finally:
            local.close()

    for category in categories:
        for start in range(1, MAX_CATALOG_PAGES + 1, 6):
            urls = [
                category if page == 1 else category + ("&" if "?" in category else "?") + f"p={page}"
                for page in range(start, min(start + 6, MAX_CATALOG_PAGES + 1))
            ]
            with ThreadPoolExecutor(max_workers=6) as pool:
                futures = [pool.submit(fetch_page, u) for u in urls]
                for future in as_completed(futures):
                    _, html, ok = future.result()
                    if not ok or not html:
                        continue
                    rows = _parse_html(html, query)
                    if rows:
                        return _enrich_product_sizes(session, rows, query)

    return []

def search(query):
    query = _clean(query)
    if not query:
        return []

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        try:
            r = _get(session, BASE + "/it/")
            if r:
                r.close()
        except Exception:
            pass

        queries = [query]
        without_size = _query_without_size(query)
        if without_size and without_size.casefold() != query.casefold():
            queries.append(without_size)

        urls = []
        for q in queries:
            encoded = quote_plus(q)
            urls.extend([
                BASE + "/it/ricerca?search_query=" + encoded,
                BASE + "/it/ricerca?s=" + encoded,
                BASE + "/it/ricerca?controller=search&s=" + encoded,
                BASE + "/it/ricerca_old?s=" + encoded,
                BASE + "/it/ricerca_old?search_query=" + encoded,
                BASE + "/it/search?controller=search&s=" + encoded,
            ])

        for url in urls:
            try:
                r = _get(session, url)
                if r is None:
                    continue
                text = r.text
                r.close()

                try:
                    data = json.loads(text)
                    rows = _walk_json(data, query)
                except Exception:
                    rows = _parse_html(text, query)

                if rows:
                    return _enrich_product_sizes(session, rows, query)
            except Exception:
                continue

        return _catalog_fallback(session, query)

    finally:
        session.close()

def scrape(query):
    return search(query)

def search_sabina(query):
    return search(query)

if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]).strip() or "Dior"
    print(json.dumps(search(q), ensure_ascii=False, indent=2))
