import re
import json
import html as html_lib
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

STORE = "Sabina"
BASE = "https://www.sabina.com"
TIMEOUT = 4

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
        "Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7,it;q=0.6",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Referer": BASE + "/fr/",
}

PRICE_RE = re.compile(r"(?<!\d)(\d{1,4}(?:[.,]\d{2}))\s*€")
PRODUCT_URL_RE = re.compile(
    r"^https?://(?:www\.)?sabina\.com/(?:fr|it)/"
    r"(?!"
    r"(?:content|recherche|ricerca|ricerca_old|marchi|marques|negozi|stores|contatto|contact|faq|"
    r"carrello|cart|panier|ordine|commande|stato-ordine|il-mio-conto|module)/)"
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
        # JSON/API spesso restituisce il numero senza simbolo €
        m = re.search(r"(?<!\d)(\d{1,4}(?:[.,]\d{2}))(?!\d)", text)
    if not m:
        return None
    return m.group(1).replace(".", ",") + " €"


def _looks_like_product_url(url):
    return bool(url and PRODUCT_URL_RE.match(url))


def _dedupe(rows, query):
    q = _clean(query).lower()
    words = [w for w in re.findall(r"[a-z0-9À-ÿ]+", q) if len(w) > 1]
    out, seen = [], set()

    for row in rows:
        name = _clean(row.get("name"))
        url = row.get("url")
        price = _price(row.get("price"))

        if not name or not url or not price:
            continue

        hay = name.lower()
        # Evita il vecchio problema: risultati cosmetici casuali per "Liquid", ecc.
        if words and not all(w in hay for w in words):
            continue

        key = (name.lower(), url.split("?")[0])
        if key in seen:
            continue
        seen.add(key)

        out.append({
            "store": STORE,
            "name": name,
            "price": price,
            "url": url.split("#")[0],
        })

    return out


def _walk_json(obj, query):
    """Estrae prodotti da JSON anche se SellBoost cambia leggermente i nomi dei campi."""
    rows = []

    def walk(x):
        if isinstance(x, dict):
            low = {str(k).lower(): v for k, v in x.items()}

            name = next(
                (low[k] for k in (
                    "name", "product_name", "productname", "title", "label"
                ) if k in low and isinstance(low[k], (str, int, float))),
                None,
            )
            url = next(
                (low[k] for k in (
                    "url", "link", "product_url", "producturl", "href"
                ) if k in low and isinstance(low[k], str)),
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
            if name and url and _looks_like_product_url(url) and _price(price):
                rows.append({
                    "store": STORE,
                    "name": str(name),
                    "price": price,
                    "url": url,
                })

            for v in x.values():
                walk(v)

        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(obj)
    return _dedupe(rows, query)


def _parse_html(text, query):
    soup = BeautifulSoup(text, "html.parser")
    rows = []

    # 1) JSON-LD: è il dato più pulito quando presente.
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.get_text(strip=True))
            rows.extend(_walk_json(data, query))
        except Exception:
            pass

    # 2) Card / link prodotto. Non dipende da UNA singola classe CSS.
    for a in soup.find_all("a", href=True):
        url = urljoin(BASE, a["href"])
        if not _looks_like_product_url(url):
            continue

        container = a
        for _ in range(7):
            parent = getattr(container, "parent", None)
            if not parent:
                break
            container = parent
            txt = _clean(container.get_text(" ", strip=True))
            if "€" in txt and len(txt) < 1800:
                break

        text_block = _clean(container.get_text(" ", strip=True))
        pm = PRICE_RE.search(text_block)
        if not pm:
            continue

        # Preferenza: title/aria-label/testo link; poi heading nella card.
        candidates = [
            a.get("title"),
            a.get("aria-label"),
            a.get_text(" ", strip=True),
        ]
        for sel in ("h1", "h2", "h3", "h4", ".name", ".product-name", ".product-title"):
            el = container.select_one(sel)
            if el:
                candidates.append(el.get_text(" ", strip=True))

        name = max((_clean(x) for x in candidates if _clean(x)), key=len, default="")
        if not name or name.lower() in {"vedi", "vedi tutto", "acquista", "immagine"}:
            continue

        rows.append({
            "store": STORE,
            "name": name,
            "price": pm.group(1) + " €",
            "url": url,
        })

    return _dedupe(rows, query)


def _get(session, url, **kwargs):
    r = session.get(
        url,
        headers=HEADERS,
        timeout=TIMEOUT,
        allow_redirects=True,
        **kwargs,
    )

    if r.status_code in (403, 429):
        print(f"SABINA BLOCKED: HTTP {r.status_code}")
        r.close()
        return None

    r.raise_for_status()
    return r

def _tokens(query):
    return [w for w in re.findall(r"[a-z0-9À-ÿ]+", _clean(query).lower()) if len(w) > 1]


def _score_link(text, url, query):
    tokens = _tokens(query)
    hay = _clean(f"{text} {url}").lower()
    if not tokens:
        return 0.0
    hits = sum(1 for t in tokens if t in hay)
    return hits / len(tokens)


def _product_links(html, query):
    soup = BeautifulSoup(html, "html.parser")
    found = []
    seen = set()
    for a in soup.find_all("a", href=True):
        url = urljoin(BASE, a.get("href", ""))
        if not _looks_like_product_url(url):
            continue
        text = _clean(a.get("title") or a.get("aria-label") or a.get_text(" ", strip=True))
        score = _score_link(text, url, query)
        if score >= 1.0:
            key = url.split("#")[0].split("?")[0]
            if key not in seen:
                seen.add(key)
                found.append((score, key, text))
    return sorted(found, key=lambda x: (-x[0], x[1]))


def _verify_product(session, url, query):
    try:
        r = _get(session, url)
        if r is None:
            return None
        html = r.text
        final = r.url
        r.close()
        rows = _parse_html(html, query)
        if rows:
            return rows[0]

        # Product pages sometimes expose name/price only in JSON-LD or meta tags.
        soup = BeautifulSoup(html, "html.parser")
        title = _clean((soup.find("h1") or soup.find("title")).get_text(" ", strip=True) if (soup.find("h1") or soup.find("title")) else "")
        words = _tokens(query)
        if not title or (words and not all(w in title.lower() for w in words)):
            return None
        price = None
        for meta in soup.find_all("meta"):
            key = str(meta.get("property") or meta.get("name") or "").lower()
            if key in {"product:price:amount", "product:price", "og:price:amount"}:
                price = _price(meta.get("content"))
                if price:
                    break
        if not price:
            price = _price(soup.get_text(" ", strip=True))
        if not price:
            return None
        return {"store": STORE, "name": title, "price": price, "url": final}
    except Exception:
        return None


def _discover_from_page(session, page_url, query, max_links=120):
    """Discover real products AND pagination/catalogue links from one page.

    Important: the old version only looked for query tokens inside product
    anchors. Sabina category pages can contain the real product card even when
    the anchor/URL signal is weak or absent. Therefore the complete HTML is
    parsed with _parse_html() first, exactly like the normal search path.
    """
    try:
        r = _get(session, page_url)
        if r is None:
            return [], [], []
        html = r.text
        final = r.url
        r.close()
    except Exception:
        return [], [], []

    # PRIMARY: parse the actual product cards on the page.
    direct_rows = _parse_html(html, query)

    # SECONDARY: exact query-looking product URLs.
    matches = _product_links(html, query)

    soup = BeautifulSoup(html, "html.parser")
    discovered = []
    seen = set()
    final_clean = final.split("#", 1)[0]

    for a in soup.find_all("a", href=True):
        u = urljoin(BASE, a.get("href", "")).split("#", 1)[0]
        if not u.startswith(BASE + "/fr/"):
            continue

        low = u.lower()
        if any(x in low for x in (
            "/module/", "/content/", "/contact", "/faq", "/panier",
            "/commande", "/compte", "/blog", "/recherche"
        )):
            continue

        if u == final_clean:
            continue

        # KEEP the query string. This is critical for Sabina pagination:
        # /...?p=19 and /...?p=27 are different catalogue pages.
        key = u
        if key in seen:
            continue

        text = _clean(
            a.get("title") or
            a.get("aria-label") or
            a.get_text(" ", strip=True)
        )

        score = _score_link(text, u, query)

        # Pagination gets a strong priority so deep catalogue pages are not
        # lost behind unrelated navigation links.
        if re.search(r"(?:^|[?&])p=\d+", u):
            score += 20.0

        # Catalogue/fragrance pages are useful generic discovery branches.
        if any(k in low for k in (
            "parfum", "fragrance", "perfume", "arab", "nicho", "niche"
        )):
            score += 5.0

        discovered.append((score, u))
        seen.add(key)

    discovered.sort(key=lambda x: (-x[0], x[1]))

    return direct_rows, matches, [u for _, u in discovered[:max_links]]

def _sitemap_candidates(session, query, limit_maps=20):
    """Generic last-resort discovery. No product names or product URLs are hard-coded."""
    out = []
    try:
        r = _get(session, BASE + "/robots.txt")
        if r is None:
            return out
        robots = r.text
        r.close()
        smaps = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", robots)
    except Exception:
        smaps = []
    if not smaps:
        smaps = [BASE + "/sitemap.xml", BASE + "/fr/sitemap.xml"]

    tokens = _tokens(query)
    for sm in smaps[:limit_maps]:
        try:
            r = _get(session, sm)
            if r is None:
                continue
            text = r.text
            r.close()
            # If this is a sitemap index, inspect child sitemap URLs that contain a query token.
            locs = re.findall(r"<loc>\s*(.*?)\s*</loc>", text, flags=re.I | re.S)
            if not locs:
                continue
            if "<sitemapindex" in text.lower():
                for child in locs[:100]:
                    child_low = child.lower()
                    if tokens and not any(t in child_low for t in tokens):
                        continue
                    cr = _get(session, child)
                    if cr is None:
                        continue
                    ctext = cr.text
                    cr.close()
                    for u in re.findall(r"<loc>\s*(.*?)\s*</loc>", ctext, flags=re.I | re.S):
                        if _looks_like_product_url(u) and all(t in u.lower() for t in tokens):
                            out.append(u)
            else:
                for u in locs:
                    if _looks_like_product_url(u) and all(t in u.lower() for t in tokens):
                        out.append(u)
            if out:
                return list(dict.fromkeys(out))
        except Exception:
            continue
    return list(dict.fromkeys(out))


def search(query):
    """Generic Sabina discovery compatible with main.py.

    Strategy:
      1. Try Sabina's own search routes.
      2. If they do not return products, crawl the French catalogue.
      3. Parse real product cards on every visited catalogue page.
      4. Preserve and prioritize pagination URLs.
      5. Verify discovered product pages before returning them.
      6. Use sitemap only as a final generic fallback.

    No product, brand or product URL is hard-coded.
    """
    query = _clean(query)
    if not query:
        return []

    s = requests.Session()
    s.headers.update(HEADERS)
    results = []

    try:
        # Browser-like session bootstrap.
        for home in (BASE + "/fr/", BASE + "/it/"):
            try:
                _get(s, home)
            except Exception:
                pass

        # 1) Sabina internal search.
        search_urls = [
            BASE + "/fr/recherche?search_query=" + quote_plus(query),
            BASE + "/fr/recherche?s=" + quote_plus(query),
            BASE + "/it/ricerca?search_query=" + quote_plus(query),
            BASE + "/it/ricerca?s=" + quote_plus(query),
        ]

        for u in search_urls:
            try:
                r = _get(s, u)
                if r is None:
                    continue
                html = r.text
                r.close()
                results.extend(_parse_html(html, query))
            except Exception:
                continue

        results = _dedupe(results, query)
        if results:
            print(f"SABINA: SEARCH_MATCH query={query!r} results={len(results)}")
            return results

        # 2) Generic catalogue crawl.
        # Pagination is preserved and prioritized inside _discover_from_page.
        queue = [BASE + "/fr/"]
        queued = set(queue)
        visited = set()
        max_pages = 80

        while queue and len(visited) < max_pages:
            page = queue.pop(0)
            if page in visited:
                continue

            visited.add(page)
            print(
                f"SABINA: DISCOVERY page={len(visited)}/{max_pages} url={page}"
            )

            direct_rows, matches, links = _discover_from_page(
                s, page, query, max_links=120
            )

            # PRIMARY result path: real product cards found on the page.
            if direct_rows:
                results.extend(direct_rows)
                results = _dedupe(results, query)
                print(
                    f"SABINA: DIRECT_CARD_MATCH page={page} "
                    f"results={len(results)}"
                )
                if results:
                    return results

            # SECONDARY result path: query-looking product URLs.
            for _, url, _ in matches[:30]:
                row = _verify_product(s, url, query)
                if row:
                    results.append(row)

            results = _dedupe(results, query)
            if results:
                return results

            # Enqueue newly discovered pages. The order supplied by
            # _discover_from_page keeps pagination ahead of generic links.
            for u in links:
                if u not in queued and u not in visited:
                    queued.add(u)
                    queue.append(u)

        # 3) Generic sitemap fallback.
        for url in _sitemap_candidates(s, query):
            row = _verify_product(s, url, query)
            if row:
                results.append(row)

        return _dedupe(results, query)

    finally:
        s.close()


# Alias compatibili con gli altri scraper del progetto.
def scrape(query):
    return search(query)


def search_sabina(query):
    return search(query)


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]).strip() or "Dior"
    data = search(q)
    print(json.dumps(data, ensure_ascii=False, indent=2))
