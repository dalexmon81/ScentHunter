import re
import unicodedata
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
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


_SITEMAP_INDEX_CACHE = {"expires": 0.0, "sitemaps": []}
_SITEMAP_URL_CACHE = {"expires": 0.0, "urls": []}


def _xml_locs(text):
    """Extract <loc> values from XML without depending on a fixed namespace."""
    try:
        root = ET.fromstring(text)
        return [
            str(el.text).strip()
            for el in root.iter()
            if el.tag.lower().endswith("}loc") or el.tag.lower() == "loc"
            if el.text and str(el.text).strip()
        ]
    except Exception:
        # XML may be served with a BOM or other harmless prefix.
        raw = (text or "").replace("\ufeff", "")
        return re.findall(r"<loc>\s*([^<]+?)\s*</loc>", raw, re.I)


def _sitemap_product_urls(session, query):
    """
    True generic discovery through Sabina's own sitemap.

    Sabina publishes its sitemap location in robots.txt. We read the sitemap
    index, fetch its child sitemaps, and match the user's query against the
    product URLs. No brand, product, or individual URL is hard-coded.
    """
    import time

    now = time.time()
    if now >= _SITEMAP_INDEX_CACHE["expires"]:
        robots_url = BASE + "/robots.txt"
        sitemap_index = None
        try:
            rr = session.get(robots_url, timeout=12)
            if rr.status_code == 200:
                for line in rr.text.splitlines():
                    if line.strip().lower().startswith("sitemap:"):
                        candidate = line.split(":", 1)[1].strip()
                        if "sitemap_index_shop_" in candidate.lower():
                            sitemap_index = candidate
                            break
        except Exception as e:
            print(f"SABINA_DISCOVERY: ROBOTS_ERROR {type(e).__name__}: {e}")

        if not sitemap_index:
            sitemap_index = BASE + "/sitemap_index_shop_1.xml"

        try:
            rr = session.get(sitemap_index, timeout=20)
            print(
                f"SABINA_DISCOVERY: SITEMAP_INDEX status={rr.status_code} "
                f"url={sitemap_index} bytes={len(rr.content)}"
            )
            if rr.status_code == 200:
                locs = _xml_locs(rr.text)
                _SITEMAP_INDEX_CACHE["sitemaps"] = [
                    x for x in locs if x.lower().startswith(("http://", "https://"))
                ]
                _SITEMAP_INDEX_CACHE["expires"] = now + 1800
                print(
                    f"SABINA_DISCOVERY: SITEMAPS_FOUND="
                    f"{len(_SITEMAP_INDEX_CACHE['sitemaps'])}"
                )
        except Exception as e:
            print(f"SABINA_DISCOVERY: SITEMAP_INDEX_ERROR {type(e).__name__}: {e}")

    sitemaps = list(_SITEMAP_INDEX_CACHE.get("sitemaps") or [])
    if not sitemaps:
        return []

    # Child sitemaps can be numerous. Cache the product URL list so the
    # first search pays the crawl cost and subsequent searches are fast.
    if now < _SITEMAP_URL_CACHE["expires"] and _SITEMAP_URL_CACHE["urls"]:
        all_urls = _SITEMAP_URL_CACHE["urls"]
    else:
        all_urls = []
        lock = set()

        def fetch_one(sm):
            try:
                r = session.get(sm, timeout=20)
                if r.status_code != 200:
                    return []
                return _xml_locs(r.text)
            except Exception:
                return []

        # Keep concurrency modest: enough to avoid a painfully slow first
        # query without hammering Sabina.
        with ThreadPoolExecutor(max_workers=6) as ex:
            futures = {ex.submit(fetch_one, sm): sm for sm in sitemaps}
            for fut in as_completed(futures):
                try:
                    for u in fut.result():
                        if _product_like(u) and u not in lock:
                            lock.add(u)
                            all_urls.append(u)
                except Exception:
                    pass

        _SITEMAP_URL_CACHE["urls"] = all_urls
        _SITEMAP_URL_CACHE["expires"] = now + 1800
        print(f"SABINA_DISCOVERY: SITEMAP_PRODUCT_URLS={len(all_urls)}")

    qwords = _words(query)
    ranked = []
    for u in all_urls:
        slug = _norm(u.rsplit("/", 1)[-1])
        if not qwords:
            continue
        hits = sum(w in slug for w in qwords)
        if hits == len(qwords):
            ranked.append((u, 1.0))
        elif hits > 0:
            # Partial matches are retained for cases where Sabina's slug
            # drops accents, punctuation, or one generic descriptor.
            ranked.append((u, hits / len(qwords) * 0.8))

    ranked.sort(key=lambda x: (-x[1], x[0]))
    print(f"SABINA_DISCOVERY: SITEMAP_MATCHES={len(ranked)}")
    for u, sc in ranked[:20]:
        print(f"SABINA_DISCOVERY: SITEMAP_CANDIDATE score={sc:.3f} url={u}")
    return ranked[:30]

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

    # Primary discovery: Sabina's own product sitemap. This is the generic
    # path and is independent of any brand or known product.
    for u, sc in _sitemap_product_urls(s, query):
        candidates[u] = max(candidates.get(u, 0), sc)


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

    # Secondary fallback: use Sabina's public category/brand surfaces only
    # if the sitemap did not yield a candidate. We discover those surfaces
    # dynamically from the homepage instead of hard-coding a single brand.
    if not candidates:
        try:
            home = s.get(BASE + "/fr/", timeout=15, allow_redirects=True)
            print(
                f"SABINA_DISCOVERY: HOME_FALLBACK status={home.status_code} "
                f"bytes={len(home.content)}"
            )
            if home.status_code == 200:
                soup = BeautifulSoup(home.text, "html.parser")
                surfaces = []
                seen = set()
                for a in soup.find_all("a", href=True):
                    href = urljoin(home.url, str(a.get("href") or "").strip())
                    if href in seen or not href.startswith(BASE + "/fr/"):
                        continue
                    path = href.split("?", 1)[0].lower()
                    if ".html" in path or "/recherche" in path:
                        continue
                    txt = " ".join(a.stripped_strings)
                    # Generic product/category surfaces only; no named brand.
                    if any(k in path for k in ("parf", "fragrance", "marque", "nouveau", "arab")):
                        seen.add(href)
                        surfaces.append(href)
                for surface in surfaces[:20]:
                    _collect_page(surface, "SURFACE")
                    if candidates:
                        break
        except Exception as e:
            print(f"SABINA_DISCOVERY: HOME_FALLBACK_ERROR {type(e).__name__}: {e}")

    ranked = sorted(candidates.items(), key=lambda x: (-x[1], x[0]))
    print(f"SABINA_DISCOVERY: CANDIDATES={len(ranked)}")
    for u, sc in ranked[:20]:
        print(f"SABINA_DISCOVERY: CANDIDATE score={sc:.3f} url={u}")

    results = []
    for u, sc in ranked[:20]:
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
