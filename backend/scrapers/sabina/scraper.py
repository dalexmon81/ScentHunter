import re
import json
import time
import unicodedata
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode, quote_plus

import requests
from bs4 import BeautifulSoup


BASE = "https://www.sabina.com"
UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)

# Generic public catalog surfaces. No individual product URL is hard-coded.
CATEGORY_ROOTS = (
    BASE + "/fr/7-parfums-pour-homme",
    BASE + "/fr/30-fragrances-pour-femme",
    BASE + "/fr/865-parfums-arabes-pour-hommes",
    BASE + "/fr/864-parfums-arabes-pour-femmes",
    BASE + "/fr/890-parfumerie-de-niche",
    BASE + "/fr/688-parfums-de-niche-pour-femme",
    BASE + "/fr/891-perfumes-nicho-unisex",
)

PAGE_SIZE = 36
MAX_PAGES_PER_CATEGORY = 40
PAGE_BATCH = 8
MAX_DISCOVERY_WORKERS = 8
MAX_PRODUCT_VERIFY = 12

_SITEMAP_CACHE = {"expires": 0.0, "urls": []}


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
    return sum(w in h for w in words) / len(words)


def _product_like(url):
    u = (url or "").lower()
    return (
        "sabina.com/" in u
        and ".html" in u
        and not any(
            x in u
            for x in (
                "/ricerca",
                "/search",
                "/login",
                "/cart",
                "/account",
                "/suivi",
                "/seguimiento",
            )
        )
    )


def _clean_url(url):
    return (url or "").replace("\\/", "/").strip().split("#", 1)[0]


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

    attrs = {
        "data-href",
        "data-url",
        "data-link",
        "data-product-url",
        "data-product-link",
    }
    for tag in soup.find_all(True):
        txt = " ".join(tag.stripped_strings)
        for attr, value in tag.attrs.items():
            if isinstance(value, str) and attr.lower() in attrs:
                add(value, txt)

    absolute_re = re.compile(
        r"https?://(?:www\.)?sabina\.com/[^\"'\s<>\\]+?\.html(?:\?[^\"'\s<>\\]*)?",
        re.I,
    )
    relative_re = re.compile(
        r"/[^\"'\s<>\\]+?\.html(?:\?[^\"'\s<>\\]*)?",
        re.I,
    )

    raw = html.replace("\\/", "/")
    for script in soup.find_all("script"):
        text = script.string or script.get_text() or ""
        if ".html" not in text.lower():
            continue
        for m in absolute_re.finditer(text):
            add(m.group(0))
        for m in relative_re.finditer(text):
            add(m.group(0))

    for m in absolute_re.finditer(raw):
        add(m.group(0))
    for m in relative_re.finditer(raw):
        add(m.group(0))

    return out


def _xml_locs(text):
    try:
        root = ET.fromstring(text.lstrip("\ufeff"))
        out = []
        for el in root.iter():
            tag = str(el.tag).lower()
            if (tag.endswith("}loc") or tag == "loc") and el.text:
                value = str(el.text).strip()
                if value:
                    out.append(value)
        return out
    except Exception:
        return re.findall(r"<loc>\s*([^<]+?)\s*</loc>", text or "", re.I)


def _robots_sitemap(session):
    try:
        r = session.get(BASE + "/robots.txt", timeout=10)
        if r.status_code == 200:
            for line in r.text.splitlines():
                if line.strip().lower().startswith("sitemap:"):
                    value = line.split(":", 1)[1].strip()
                    if "sitemap_index_shop_" in value.lower():
                        return value
    except Exception as e:
        print(f"SABINA_DISCOVERY: ROBOTS_ERROR {type(e).__name__}: {e}")
    return BASE + "/sitemap_index_shop_1.xml"


def _expand_sitemap(session, url, depth=0, max_depth=3):
    """Recursively resolve sitemap indexes until product URLs are reached."""
    if depth > max_depth:
        return []

    try:
        r = session.get(url, timeout=15)
        if r.status_code != 200:
            return []

        locs = _xml_locs(r.text)
        if not locs:
            return []

        product_urls = [u for u in locs if _product_like(u)]
        if product_urls:
            return product_urls

        child_sitemaps = [
            u for u in locs
            if u.lower().endswith(".xml") or "sitemap" in u.lower()
        ]
        if not child_sitemaps:
            return []

        results = []
        with ThreadPoolExecutor(max_workers=min(8, len(child_sitemaps))) as ex:
            futures = [
                ex.submit(_expand_sitemap, session, u, depth + 1, max_depth)
                for u in child_sitemaps
            ]
            for fut in as_completed(futures):
                try:
                    results.extend(fut.result())
                except Exception:
                    pass
        return results
    except Exception:
        return []


def _sitemap_product_urls(session):
    now = time.time()
    if now < _SITEMAP_CACHE["expires"] and _SITEMAP_CACHE["urls"]:
        return _SITEMAP_CACHE["urls"]

    index_url = _robots_sitemap(session)
    print(f"SABINA_DISCOVERY: SITEMAP_INDEX_URL={index_url}")

    urls = _expand_sitemap(session, index_url)
    dedup = list(dict.fromkeys(u for u in urls if _product_like(u)))

    _SITEMAP_CACHE["urls"] = dedup
    _SITEMAP_CACHE["expires"] = now + 1800

    print(f"SABINA_DISCOVERY: SITEMAP_PRODUCT_URLS={len(dedup)}")
    return dedup


def _page_url(root, page):
    if page <= 1:
        return root
    parts = urlsplit(root)
    qs = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "p"]
    qs.append(("p", str(page)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(qs), ""))


def _extract_total_pages(html):
    text = _norm(html)

    m = re.search(
        r"(?:showing|affichant|mostrando)\s+\d+\s*[-–]\s*\d+\s+"
        r"(?:of|de)\s+([\d.,\s]+)\s+(?:items|articles|productos)",
        text,
        re.I,
    )
    if m:
        try:
            total = int(re.sub(r"[^\d]", "", m.group(1)))
            if total > 0:
                return min(MAX_PAGES_PER_CATEGORY, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        except Exception:
            pass

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
        r = session.get(page_url, timeout=12, allow_redirects=True)
        if r.status_code != 200:
            return {"ok": False, "matches": [], "pages": 1}

        links = _links(r.text, r.url)
        matches = []
        for u, txt in links:
            sc = _score(query, u + " " + txt)
            if sc > 0:
                matches.append((u, txt, sc))

        return {
            "ok": True,
            "matches": matches,
            "pages": _extract_total_pages(r.text),
            "links": len(links),
        }
    except Exception as e:
        return {
            "ok": False,
            "matches": [],
            "pages": 1,
            "error": f"{type(e).__name__}: {e}",
        }


def _category_fallback(session, query):
    """Bounded fallback only when sitemap discovery gives no candidate."""
    candidates = {}

    for root in CATEGORY_ROOTS:
        first = _collect_catalog_page(session, root, query)
        print(
            f"SABINA_DISCOVERY: CATEGORY root={root} "
            f"status={'OK' if first['ok'] else 'ERR'} "
            f"pages={first.get('pages', 1)} links={first.get('links', 0)}"
        )

        for u, txt, sc in first["matches"]:
            candidates[u] = max(candidates.get(u, 0.0), sc)

        if candidates:
            # We have real product candidates; don't crawl the whole site.
            continue

        total_pages = min(first.get("pages", 1), MAX_PAGES_PER_CATEGORY)
        if total_pages <= 1:
            continue

        remaining = list(range(2, total_pages + 1))
        for start in range(0, len(remaining), PAGE_BATCH):
            batch = remaining[start:start + PAGE_BATCH]
            urls = [_page_url(root, p) for p in batch]

            with ThreadPoolExecutor(max_workers=MAX_DISCOVERY_WORKERS) as ex:
                futs = [
                    ex.submit(_collect_catalog_page, session, u, query)
                    for u in urls
                ]
                for fut in as_completed(futs):
                    result = fut.result()
                    for u, txt, sc in result.get("matches", []):
                        candidates[u] = max(candidates.get(u, 0.0), sc)

            if candidates:
                break

        if candidates:
            break

    return candidates


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


def _extract_price(soup):
    for script in soup.find_all(
        "script", attrs={"type": re.compile(r"application/ld\+json", re.I)}
    ):
        try:
            data = json.loads(script.string or script.get_text())
            stack = data if isinstance(data, list) else [data]

            while stack:
                item = stack.pop()
                if isinstance(item, dict):
                    offers = item.get("offers")

                    if isinstance(offers, dict):
                        p = _clean_price(offers.get("price"))
                        if p:
                            return p

                    if isinstance(offers, list):
                        for offer in offers:
                            if isinstance(offer, dict):
                                p = _clean_price(offer.get("price"))
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
            value = (
                el.get("content")
                or el.get("data-price")
                or el.get_text(" ", strip=True)
            )
            p = _clean_price(value)
            if p:
                return p

    currency_re = re.compile(
        r"(?:€|\$|£)\s*\d{1,4}(?:[.\s]\d{3})*(?:[,.]\d{2})?"
        r"|\d{1,4}(?:[.\s]\d{3})*(?:[,.]\d{2})?\s*(?:€|\$|£)"
    )
    for el in soup.find_all(string=currency_re):
        m = currency_re.search(" ".join(str(el).split()))
        if m:
            p = _clean_price(m.group(0))
            if p:
                return p

    return None


def _verify(session, query, item):
    url, discovery_score = item
    try:
        r = session.get(url, timeout=15, allow_redirects=True)
        print(
            f"SABINA_DISCOVERY: PRODUCT status={r.status_code} "
            f"url={url} final={r.url}"
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

        return {
            "name": title,
            "url": r.url,
            "price": _extract_price(soup),
        }

    except Exception as e:
        print(
            f"SABINA_DISCOVERY: PRODUCT_ERROR {url} "
            f"{type(e).__name__}: {e}"
        )
        return None


def search(query):
    """
    DIAGNOSTIC VERSION

    This version does not add product-specific seeds, URLs or exceptions.
    It tests the existing generic Sabina discovery surfaces separately so we
    can determine exactly where a product disappears:
      1) robots/sitemap
      2) sitemap product URLs
      3) category first pages
      4) category pagination
      5) final product verification

    The returned results use the same product verification logic as before.
    """
    print(f"SABINA_DIAG: START query={query!r}")
    qwords = _words(query)
    print(f"SABINA_DIAG: TOKENS={qwords}")

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        }
    )

    def token_report(label, candidates):
        exact = []
        partial = []
        for u, txt in candidates:
            hay = _norm(u + " " + txt)
            hits = sum(w in hay for w in qwords)
            if qwords and hits == len(qwords):
                exact.append((u, txt))
            elif hits > 0:
                partial.append((u, txt, hits))
        print(
            f"SABINA_DIAG: {label} total={len(candidates)} "
            f"exact={len(exact)} partial={len(partial)}"
        )
        for u, txt in exact[:10]:
            print(f"SABINA_DIAG: {label}_EXACT url={u} text={txt!r}")
        for u, txt, hits in partial[:10]:
            print(
                f"SABINA_DIAG: {label}_PARTIAL hits={hits}/{len(qwords)} "
                f"url={u} text={txt!r}"
            )
        return exact, partial

    # ------------------------------------------------------------
    # TEST 1: robots.txt -> sitemap selection
    # ------------------------------------------------------------
    sitemap_index = _robots_sitemap(session)
    print(f"SABINA_DIAG: ROBOTS_SITEMAP={sitemap_index}")

    # ------------------------------------------------------------
    # TEST 2: sitemap itself
    # ------------------------------------------------------------
    sitemap_urls = []
    sitemap_error = None
    try:
        sitemap_urls = _expand_sitemap(session, sitemap_index)
        sitemap_urls = list(dict.fromkeys(
            u for u in sitemap_urls if _product_like(u)
        ))
    except Exception as e:
        sitemap_error = f"{type(e).__name__}: {e}"

    if sitemap_error:
        print(f"SABINA_DIAG: SITEMAP_ERROR {sitemap_error}")

    print(f"SABINA_DIAG: SITEMAP_PRODUCTS={len(sitemap_urls)}")

    sitemap_candidates = []
    for u in sitemap_urls:
        slug = _norm(u.rsplit("/", 1)[-1])
        hits = sum(w in slug for w in qwords)
        if qwords and hits == len(qwords):
            sitemap_candidates.append((u, slug))

    print(f"SABINA_DIAG: SITEMAP_EXACT_MATCHES={len(sitemap_candidates)}")
    for u, slug in sitemap_candidates[:20]:
        print(f"SABINA_DIAG: SITEMAP_EXACT url={u} slug={slug!r}")

    # Also report single-token hits. This is crucial when a query such as
    # "Liquid Brun" fails because only one word is present in the URL.
    for word in qwords:
        hits = [
            u for u in sitemap_urls
            if word in _norm(u.rsplit("/", 1)[-1])
        ]
        print(f"SABINA_DIAG: SITEMAP_TOKEN word={word!r} hits={len(hits)}")
        for u in hits[:10]:
            print(f"SABINA_DIAG: SITEMAP_TOKEN_URL word={word!r} url={u}")

    # ------------------------------------------------------------
    # TEST 3 + 4: category pages, independently.
    # We deliberately inspect every configured category and its pagination
    # instead of stopping at the first successful category.
    # ------------------------------------------------------------
    category_exact = {}
    category_partial = {}

    for root in CATEGORY_ROOTS:
        print(f"SABINA_DIAG: CATEGORY_START root={root}")

        first = _collect_catalog_page(session, root, query)
        first_links = []

        if first.get("ok"):
            try:
                rr = session.get(root, timeout=12, allow_redirects=True)
                if rr.status_code == 200:
                    first_links = _links(rr.text, rr.url)
            except Exception:
                pass

        exact, partial = token_report(
            f"CATEGORY_FIRST root={root}",
            first_links,
        )

        if exact:
            category_exact[root] = exact
        if partial:
            category_partial[root] = partial

        total_pages = min(
            first.get("pages", 1),
            MAX_PAGES_PER_CATEGORY,
        )

        print(
            f"SABINA_DIAG: CATEGORY_PAGES root={root} "
            f"pages={total_pages}"
        )

        if total_pages <= 1:
            continue

        # Test all remaining pages, in bounded batches.
        for start_page in range(2, total_pages + 1, PAGE_BATCH):
            batch = list(
                range(
                    start_page,
                    min(total_pages, start_page + PAGE_BATCH - 1) + 1
                )
            )

            with ThreadPoolExecutor(
                max_workers=MAX_DISCOVERY_WORKERS
            ) as ex:
                futures = {
                    ex.submit(
                        _collect_catalog_page,
                        session,
                        _page_url(root, p),
                        query,
                    ): p
                    for p in batch
                }

                for fut in as_completed(futures):
                    page = futures[fut]
                    result = fut.result()

                    if not result.get("ok"):
                        print(
                            f"SABINA_DIAG: CATEGORY_PAGE_ERROR "
                            f"root={root} page={page} "
                            f"error={result.get('error')}"
                        )
                        continue

                    matches = result.get("matches", [])
                    if matches:
                        print(
                            f"SABINA_DIAG: CATEGORY_PAGE_MATCH "
                            f"root={root} page={page} "
                            f"matches={len(matches)}"
                        )
                        for u, txt, sc in matches[:20]:
                            print(
                                f"SABINA_DIAG: CATEGORY_PAGE_CANDIDATE "
                                f"root={root} page={page} "
                                f"score={sc:.3f} url={u} text={txt!r}"
                            )

    # ------------------------------------------------------------
    # TEST 5: verification only for candidates found by the generic
    # surfaces. No product URL is introduced here.
    # ------------------------------------------------------------
    candidates = {}

    for u, _ in sitemap_candidates:
        candidates[u] = 1.0

    for matches in category_exact.values():
        for u, txt in matches:
            candidates[u] = max(candidates.get(u, 0.0), 1.0)

    for matches in category_partial.values():
        for u, txt, hits in matches:
            candidates[u] = max(
                candidates.get(u, 0.0),
                hits / max(len(qwords), 1) * 0.8,
            )

    ranked = sorted(
        candidates.items(),
        key=lambda x: (-x[1], x[0]),
    )

    print(f"SABINA_DIAG: FINAL_CANDIDATES={len(ranked)}")
    for u, sc in ranked[:30]:
        print(f"SABINA_DIAG: FINAL_CANDIDATE score={sc:.3f} url={u}")

    verify_list = ranked[:MAX_PRODUCT_VERIFY]
    results = []

    if verify_list:
        with ThreadPoolExecutor(
            max_workers=min(6, len(verify_list))
        ) as ex:
            futures = [
                ex.submit(_verify, session, query, item)
                for item in verify_list
            ]
            for fut in as_completed(futures):
                result = fut.result()
                if result:
                    results.append(result)
                    print(
                        f"SABINA_DIAG: VERIFIED "
                        f"name={result['name']!r} "
                        f"price={result['price']!r} "
                        f"url={result['url']}"
                    )

    dedup = {}
    for result in results:
        dedup[result["url"]] = result

    results = list(dedup.values())
    results.sort(
        key=lambda r: (
            _norm(r["name"]) != _norm(query),
            _norm(r["name"]),
        )
    )

    print(
        f"SABINA_DIAG: COMPLETE query={query!r} "
        f"results={len(results)} "
        f"sitemap_products={len(sitemap_urls)} "
        f"sitemap_exact={len(sitemap_candidates)} "
        f"category_exact={sum(len(v) for v in category_exact.values())} "
        f"final_candidates={len(ranked)}"
    )

    return results

