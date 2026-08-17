import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode
import requests
from bs4 import BeautifulSoup

BASE = "https://www.sabina.com"
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Safari/605.1.15"

# Sabina's public fragrance catalog roots. These are CATEGORY pages, not
# product/brand seeds. The products themselves are discovered from the
# paginated catalog.
CATEGORY_ROOTS = (
    BASE + "/fr/31-fragrances-pour-homme",
    BASE + "/fr/30-fragrances-pour-femme",
    BASE + "/fr/865-parfums-arabes-pour-hommes",
    BASE + "/fr/864-parfums-arabes-pour-femmes",
    BASE + "/fr/890-parfumerie-de-niche",
    BASE + "/fr/688-parfums-de-niche-pour-femme",
    BASE + "/fr/891-perfumes-nicho-unisex",
)

PAGE_SIZE = 36
MAX_PAGES_PER_CATEGORY = 50
PAGE_BATCH = 8
MAX_DISCOVERY_WORKERS = 8
MAX_PRODUCT_VERIFY = 20

def _norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()

def _words(q):
    return [x for x in re.split(r"[^a-z0-9]+", _norm(q)) if x]

def _score(q, text):
    words = _words(q)
    h = _norm(text)
    if not words:
        return 0.0
    hits = sum(w in h for w in words)
    return hits / len(words)

def _product_like(url):
    u = (url or "").lower()
    return (
        "sabina.com/" in u
        and ".html" in u
        and not any(x in u for x in (
            "/ricerca", "/search", "/login", "/cart", "/account",
            "/suivi", "/seguimiento"
        ))
    )

def _clean_url(url):
    url = (url or "").replace("\\/", "/").strip()
    return url.split("#", 1)[0]

def _links(html, base):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    seen = set()

    def add(href, txt=""):
        if not href:
            return
        href = _clean_url(urljoin(base, str(href)))
        if not _product_like(href) or href in seen:
            return
        seen.add(href)
        out.append((href, " ".join(str(txt or "").split())))

    for a in soup.find_all("a", href=True):
        add(a.get("href"), " ".join(a.stripped_strings))

    # Some catalog cards expose their destination through data-* attributes.
    attrs = {
        "data-href", "data-url", "data-link",
        "data-product-url", "data-product-link"
    }
    for tag in soup.find_all(True):
        txt = " ".join(tag.stripped_strings)
        for attr, value in tag.attrs.items():
            if isinstance(value, str) and attr.lower() in attrs:
                add(value, txt)

    # Embedded JSON can contain product links too.
    absolute_re = re.compile(
        r"https?://(?:www\.)?sabina\.com/[^\"'\s<>\\]+?\.html(?:\?[^\"'\s<>\\]*)?",
        re.I
    )
    relative_re = re.compile(
        r"/[^\"'\s<>\\]+?\.html(?:\?[^\"'\s<>\\]*)?",
        re.I
    )
    raw = html.replace("\\/", "/")
    for m in absolute_re.finditer(raw):
        add(m.group(0))
    for m in relative_re.finditer(raw):
        add(m.group(0))

    return out

def _page_url(root, page):
    if page <= 1:
        return root
    parts = urlsplit(root)
    qs = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "p"]
    qs.append(("p", str(page)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(qs), ""))

def _extract_total_pages(html):
    # Current Sabina catalog pages expose e.g. "Showing 1 - 36 of 1303 items".
    m = re.search(
        r"(?:showing|affichant|mostrando)\s+\d+\s*[-–]\s*\d+\s+"
        r"(?:of|de)\s+([\d.,\s]+)\s+(?:items|articles|productos)",
        _norm(html),
        re.I,
    )
    if m:
        try:
            total = int(re.sub(r"[^\d]", "", m.group(1)))
            if total > 0:
                return min(MAX_PAGES_PER_CATEGORY, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        except Exception:
            pass

    # Fallback: inspect pagination links for the largest explicit p= number.
    soup = BeautifulSoup(html, "html.parser")
    pages = []
    for a in soup.find_all("a", href=True):
        href = urljoin(BASE, a.get("href"))
        mm = re.search(r"(?:[?&])p=(\d+)", href)
        if mm:
            pages.append(int(mm.group(1)))
    return min(MAX_PAGES_PER_CATEGORY, max(pages or [1]))

def _collect_catalog_page(session, page_url, query):
    try:
        r = session.get(page_url, timeout=15, allow_redirects=True)
        if r.status_code != 200:
            return {"url": page_url, "ok": False, "matches": [], "pages": 1}
        links = _links(r.text, r.url)
        matches = []
        for u, txt in links:
            sc = _score(query, u + " " + txt)
            if sc > 0:
                matches.append((u, txt, sc))
        total_pages = _extract_total_pages(r.text)
        return {
            "url": page_url,
            "ok": True,
            "matches": matches,
            "pages": total_pages,
            "links": len(links),
        }
    except Exception as e:
        return {
            "url": page_url,
            "ok": False,
            "matches": [],
            "pages": 1,
            "error": f"{type(e).__name__}: {e}",
        }

def _discover_from_catalog(session, query):
    candidates = {}
    qwords = _words(query)
    if not qwords:
        return candidates

    for root in CATEGORY_ROOTS:
        first = _collect_catalog_page(session, root, query)
        print(
            f"SABINA_DISCOVERY: CATEGORY root={root} "
            f"status={'OK' if first['ok'] else 'ERR'} "
            f"pages={first.get('pages', 1)} links={first.get('links', 0)}"
        )

        for u, txt, sc in first["matches"]:
            candidates[u] = max(candidates.get(u, 0.0), sc)
            if sc == 1.0:
                print(
                    f"SABINA_DISCOVERY: MATCH score=1.000 "
                    f"url={u} text={txt[:160]!r}"
                )

        total_pages = min(first.get("pages", 1), MAX_PAGES_PER_CATEGORY)
        if total_pages <= 1:
            continue

        # Crawl the remaining catalog pages in bounded batches. We do not
        # assume where a product lives; every page is eligible.
        remaining = list(range(2, total_pages + 1))
        for start in range(0, len(remaining), PAGE_BATCH):
            batch = remaining[start:start + PAGE_BATCH]
            urls = [_page_url(root, p) for p in batch]
            with ThreadPoolExecutor(max_workers=MAX_DISCOVERY_WORKERS) as ex:
                futs = {
                    ex.submit(_collect_catalog_page, session, u, query): u
                    for u in urls
                }
                for fut in as_completed(futs):
                    result = fut.result()
                    for u, txt, sc in result.get("matches", []):
                        candidates[u] = max(candidates.get(u, 0.0), sc)
                        if sc == 1.0 and len(candidates) <= 20:
                            print(
                                f"SABINA_DISCOVERY: MATCH score=1.000 "
                                f"url={u} text={txt[:160]!r}"
                            )

            # If exact candidates have already been found, continue through
            # this category only if there may be more exact variants. Once
            # every page of the category has been scanned, move on.
    return candidates

def _extract_price(soup):
    def clean(value):
        if value is None:
            return None
        value = str(value).strip()
        m = re.search(
            r"(?<!\d)(\d{1,4}(?:[.\s]\d{3})*(?:,\d{2})|\d+(?:[.,]\d{2}))(?!\d)",
            value,
        )
        if not m:
            return None
        v = m.group(1).replace(" ", "")
        if "," in v and "." in v:
            if v.rfind(",") > v.rfind("."):
                v = v.replace(".", "").replace(",", ".")
            else:
                v = v.replace(",", "")
        elif "," in v:
            v = v.replace(",", ".")
        return v

    # JSON-LD first.
    for script in soup.find_all(
        "script", attrs={"type": re.compile(r"application/ld\+json", re.I)}
    ):
        try:
            import json
            data = json.loads(script.string or script.get_text())
            stack = data if isinstance(data, list) else [data]
            while stack:
                item = stack.pop()
                if isinstance(item, dict):
                    offers = item.get("offers")
                    if isinstance(offers, dict):
                        p = clean(offers.get("price"))
                        if p:
                            return p
                    elif isinstance(offers, list):
                        for offer in offers:
                            if isinstance(offer, dict):
                                p = clean(offer.get("price"))
                                if p:
                                    return p
                    for value in item.values():
                        if isinstance(value, (dict, list)):
                            stack.append(value)
                elif isinstance(item, list):
                    stack.extend(item)
        except Exception:
            pass

    for selector in (
        'meta[property="product:price:amount"]',
        'meta[itemprop="price"]',
        '[itemprop="price"]',
        "[data-price]",
        '[class*="price"]',
    ):
        for el in soup.select(selector):
            value = el.get("content") or el.get("data-price") or el.get_text(" ", strip=True)
            p = clean(value)
            if p:
                return p

    currency_re = re.compile(
        r"(?:€|\$|£)\s*\d{1,4}(?:[.\s]\d{3})*(?:[,.]\d{2})?"
        r"|\d{1,4}(?:[.\s]\d{3})*(?:[,.]\d{2})?\s*(?:€|\$|£)"
    )
    for el in soup.find_all(string=currency_re):
        m = currency_re.search(" ".join(str(el).split()))
        if m:
            p = clean(m.group(0))
            if p:
                return p
    return None

def _verify(session, query, item):
    u, discovery_score = item
    try:
        r = session.get(u, timeout=20, allow_redirects=True)
        print(
            f"SABINA_DISCOVERY: PRODUCT status={r.status_code} "
            f"url={u} final={r.url}"
        )
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, "html.parser")
        h1 = soup.find("h1")
        title = " ".join(h1.stripped_strings) if h1 else ""
        if not title and soup.title:
            title = " ".join(soup.title.stripped_strings)

        verify_score = _score(query, title)
        print(
            f"SABINA_DISCOVERY: VERIFY title={title!r} "
            f"score={verify_score:.3f}"
        )
        if verify_score <= 0:
            return None

        price = _extract_price(soup)
        return {"name": title, "url": r.url, "price": price}
    except Exception as e:
        print(f"SABINA_DISCOVERY: PRODUCT_ERROR {u} {type(e).__name__}: {e}")
        return None

def search(query):
    print(f"SABINA_DISCOVERY: START query={query!r}")
    print(f"SABINA_DISCOVERY: TOKENS={_words(query)}")

    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    })

    candidates = _discover_from_catalog(s, query)
    ranked = sorted(candidates.items(), key=lambda x: (-x[1], x[0]))

    print(f"SABINA_DISCOVERY: CANDIDATES={len(ranked)}")
    for u, sc in ranked[:20]:
        print(f"SABINA_DISCOVERY: CANDIDATE score={sc:.3f} url={u}")

    results = []
    # Verify all strong matches, while retaining weaker partial candidates
    # only when there are few/no exact matches.
    exact = [x for x in ranked if x[1] >= 1.0]
    verify_list = exact if exact else ranked
    verify_list = verify_list[:MAX_PRODUCT_VERIFY]

    with ThreadPoolExecutor(max_workers=min(6, max(1, len(verify_list)))) as ex:
        futs = [ex.submit(_verify, s, query, item) for item in verify_list]
        for fut in as_completed(futs):
            result = fut.result()
            if result:
                results.append(result)
                print(
                    f"SABINA_DISCOVERY: FOUND name={result['name']!r} "
                    f"price={result['price']!r} url={result['url']}"
                )

    # Deduplicate only by final URL. Distinct product pages remain distinct.
    dedup = {}
    for result in results:
        dedup[result["url"]] = result
    results = list(dedup.values())

    # Stable ordering: best query match first, then name.
    results.sort(key=lambda r: (_norm(r["name"]) != _norm(query), _norm(r["name"])))
    print(f"SABINA_DISCOVERY: COMPLETE results={len(results)}")
    return results
