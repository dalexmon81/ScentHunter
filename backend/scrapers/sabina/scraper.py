import re
import unicodedata
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

BASE = "https://www.sabina.com"
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Safari/605.1.15"

def _norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()

def _words(q):
    return [x for x in re.split(r"[^a-z0-9]+", _norm(q)) if x]

def _score(q, text):
    w = _words(q)
    h = _norm(text)
    return sum(x in h for x in w) / len(w) if w else 0.0

def _product_like(url):
    u = (url or "").lower()
    return "sabina.com/" in u and ".html" in u and not any(
        x in u for x in ["/ricerca", "/search", "/login", "/cart", "/account"]
    )

def _links(html, base):
    """
    Generic product-link discovery.

    Sabina can expose product URLs in normal <a href> elements, data
    attributes, or embedded JSON. We collect all generic representations
    without knowing any individual product URL.
    """
    soup = BeautifulSoup(html, "html.parser")
    out = []
    seen = set()

    def add(href, txt=""):
        if not href:
            return
        href = str(href).strip()
        href = href.replace("\\/", "/")
        href = urljoin(base, href)
        href = href.split("#", 1)[0]
        if not _product_like(href) or href in seen:
            return
        seen.add(href)
        out.append((href, " ".join(str(txt or "").split())))

    for a in soup.find_all("a", href=True):
        add(a.get("href"), " ".join(a.stripped_strings))

    url_attrs = {
        "href", "src", "action", "data-href", "data-url",
        "data-link", "data-product-url", "data-product-link"
    }
    for tag in soup.find_all(True):
        txt = " ".join(tag.stripped_strings)
        for attr, value in tag.attrs.items():
            if isinstance(value, str) and attr.lower() in url_attrs:
                add(value, txt)

    product_url_re = re.compile(
        r"https?://(?:www\.)?sabina\.com/[^\"'\s<>\\]+?\.html(?:\?[^\"'\s<>\\]*)?",
        re.I
    )
    relative_url_re = re.compile(
        r"/[^\"'\s<>\\]+?\.html(?:\?[^\"'\s<>\\]*)?",
        re.I
    )

    for script in soup.find_all("script"):
        raw = script.string or script.get_text() or ""
        if ".html" not in raw.lower():
            continue
        raw = raw.replace("\\/", "/")
        for m in product_url_re.finditer(raw):
            add(m.group(0))
        for m in relative_url_re.finditer(raw):
            add(m.group(0))

    if not out:
        raw_html = html.replace("\\/", "/")
        for m in product_url_re.finditer(raw_html):
            add(m.group(0))
        for m in relative_url_re.finditer(raw_html):
            add(m.group(0))

    return out

def search(query):
    print(f"SABINA_DISCOVERY: START query={query!r}")
    qwords = _words(query)
    print(f"SABINA_DISCOVERY: TOKENS={qwords}")

    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    })

    # Generic discovery. No individual product URL is hard-coded.
    # First try Sabina's own generic search endpoint. If it does not expose
    # product links, fall back to broad category/brand surfaces and their
    # pagination.
    candidates = {}
    visited_pages = set()

    def _collect_page(page_url, label):
        if page_url in visited_pages:
            return []
        visited_pages.add(page_url)
        try:
            r = s.get(page_url, timeout=12, allow_redirects=True)
            print(
                f"SABINA_DISCOVERY: {label} status={r.status_code} "
                f"url={page_url} final={r.url} bytes={len(r.content)}"
            )
            if r.status_code != 200:
                return []

            discovered_links = _links(r.text, r.url)
            print(f"SABINA_DISCOVERY: LINKS_FOUND={len(discovered_links)}")
            matched_here = 0
            for u, txt in discovered_links:
                sc = _score(query, u + " " + txt)
                if sc > 0:
                    matched_here += 1
                    candidates[u] = max(candidates.get(u, 0), sc)
                    if matched_here <= 10:
                        print(
                            f"SABINA_DISCOVERY: MATCH score={sc:.3f} "
                            f"url={u} text={txt[:160]!r}"
                        )
            print(f"SABINA_DISCOVERY: PAGE_MATCHES={matched_here}")

            # Collect pagination links without depending on a particular
            # page-number URL format.
            soup = BeautifulSoup(r.text, "html.parser")
            pagination = []
            seen = set()
            for a in soup.find_all("a", href=True):
                href = urljoin(r.url, str(a.get("href") or "").strip())
                if not href or href in seen:
                    continue
                href_l = href.lower()
                txt = _norm(" ".join(a.stripped_strings))
                rel = " ".join(a.get("rel") or []).lower()
                cls = " ".join(a.get("class") or []).lower()
                if (
                    "page=" in href_l
                    or "p=" in href_l
                    or "pagination" in cls
                    or "next" in rel
                    or txt in {"2", "3", "4", "5", "suivante", "prochaine", "next"}
                ):
                    seen.add(href)
                    pagination.append(href)
            return pagination
        except Exception as e:
            print(f"SABINA_DISCOVERY: PAGE_ERROR {page_url} {type(e).__name__}: {e}")
            return []

    # 1) Sabina's native search. We do not assume that one particular
    # endpoint works forever, so the alternatives are tried only until real
    # product links are obtained.
    from urllib.parse import quote_plus
    encoded_q = quote_plus(query)
    search_pages = [
        BASE + f"/fr/recherche?controller=search&s={encoded_q}",
        BASE + f"/fr/recherche?s={encoded_q}",
        BASE + f"/fr/recherche?search_query={encoded_q}",
    ]

    for search_url in search_pages:
        _collect_page(search_url, "SEARCH")
        if candidates:
            break

    # 2) Generic fallback surfaces. These are category/brand entry points,
    # not individual products. Follow a few pagination pages so a product
    # does not need to be in the first 20-30 links to be discoverable.
    if not candidates:
        seeds = [
            BASE + "/fr/601_french-avenue",
            BASE + "/fr/865-parfums-arabes-pour-homme",
            BASE + "/fr/864-parfums-arabes-pour-femme",
        ]

        MAX_PAGES_PER_SEED = 5
        for seed in seeds:
            queue = [seed]
            pages_for_seed = 0

            while queue and pages_for_seed < MAX_PAGES_PER_SEED:
                page_url = queue.pop(0)
                before = len(candidates)
                next_pages = _collect_page(
                    page_url,
                    "SEED" if pages_for_seed == 0 else "PAGE",
                )
                pages_for_seed += 1

                if len(candidates) > before:
                    break

                for nxt in next_pages:
                    if nxt not in visited_pages and nxt not in queue:
                        queue.append(nxt)

    ranked = sorted(candidates.items(), key=lambda x: (-x[1], x[0]))
    print(f"SABINA_DISCOVERY: CANDIDATES={len(ranked)}")
    for u, sc in ranked[:20]:
        print(f"SABINA_DISCOVERY: CANDIDATE score={sc:.3f} url={u}")

    results = []
    for u, sc in ranked[:10]:
        try:
            r = s.get(u, timeout=20, allow_redirects=True)
            print(f"SABINA_DISCOVERY: PRODUCT status={r.status_code} url={u} final={r.url}")
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            h1 = soup.find("h1")
            title = " ".join(h1.stripped_strings) if h1 else ""
            if not title and soup.title:
                title = " ".join(soup.title.stripped_strings)

            ps = _score(query, title)
            print(f"SABINA_DISCOVERY: VERIFY title={title!r} score={ps:.3f}")

            if ps <= 0:
                continue

            # Robust price extraction: structured data first, then common
            # HTML price fields, then visible currency text.
            price = None

            def _clean_price(value):
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

            # 1) Schema.org Product/Offer JSON-LD.
            for script in soup.find_all(
                "script", attrs={"type": re.compile(r"application/ld\+json", re.I)}
            ):
                try:
                    import json
                    data = json.loads(script.string or script.get_text())
                    stack = data if isinstance(data, list) else [data]

                    while stack and not price:
                        item = stack.pop()

                        if isinstance(item, dict):
                            offers = item.get("offers")

                            if isinstance(offers, dict):
                                p = offers.get("price")
                                if p is not None:
                                    price = _clean_price(p)

                            elif isinstance(offers, list):
                                for offer in offers:
                                    if isinstance(offer, dict) and offer.get("price") is not None:
                                        price = _clean_price(offer["price"])
                                        if price:
                                            break

                            for value in item.values():
                                if isinstance(value, (dict, list)):
                                    stack.append(value)

                        elif isinstance(item, list):
                            stack.extend(item)

                except Exception:
                    continue

            # 2) Common meta/HTML price fields.
            if not price:
                for selector in [
                    'meta[property="product:price:amount"]',
                    'meta[itemprop="price"]',
                    '[itemprop="price"]',
                    "[data-price]",
                    '[class*="price"]',
                ]:
                    for el in soup.select(selector):
                        value = (
                            el.get("content")
                            or el.get("data-price")
                            or el.get_text(" ", strip=True)
                        )
                        price = _clean_price(value)
                        if price:
                            break
                    if price:
                        break

            # 3) Visible currency text fallback.
            if not price:
                currency_re = re.compile(
                    r"(?:€|\$|£)\s*\d{1,4}(?:[.\s]\d{3})*(?:[,.]\d{2})?"
                    r"|\d{1,4}(?:[.\s]\d{3})*(?:[,.]\d{2})?\s*(?:€|\$|£)"
                )
                for el in soup.find_all(string=currency_re):
                    match = currency_re.search(" ".join(str(el).split()))
                    if match:
                        price = _clean_price(match.group(0))
                        if price:
                            break

            results.append({"name": title, "url": r.url, "price": price})
            print(f"SABINA_DISCOVERY: FOUND name={title!r} price={price!r} url={r.url}")
        except Exception as e:
            print(f"SABINA_DISCOVERY: PRODUCT_ERROR {u} {type(e).__name__}: {e}")

    print(f"SABINA_DISCOVERY: COMPLETE results={len(results)}")
    return results
