import re
import unicodedata
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://www.sabina.com"
UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)

def _norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()

def _tokens(q):
    return [x for x in re.split(r"[^a-z0-9]+", _norm(q)) if x]

def _is_product_url(url):
    u = (url or "").lower()
    return (
        "sabina.com/" in u
        and not any(x in u for x in (
            "/ricerca", "/search", "/categoria", "/categories/",
            "/marche/", "/brands/", "/blog/", "/login", "/cart",
            "/account", "/contact", "/es/", "/en/"
        ))
        and (".html" in u or "/parfums-" in u or "/parfum-" in u)
    )

def _extract_links(html, source_url):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = urljoin(source_url, a.get("href", "").strip())
        text = " ".join(a.stripped_strings)
        if not href.startswith("https://www.sabina.com"):
            continue
        if href in seen:
            continue
        seen.add(href)
        out.append((href, text))
    return out

def _score(url, text, qwords):
    hay = _norm(url + " " + text)
    if not qwords:
        return 0.0
    hits = sum(1 for w in qwords if w in hay)
    return hits / len(qwords)

def search(query):
    print(f"SABINA_DIAG2: START query={query!r}")
    qwords = _tokens(query)
    print(f"SABINA_DIAG2: TOKENS={qwords}")

    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
        "Referer": BASE + "/",
    })

    # Phase 1: robots only, to discover every sitemap reference without
    # relying on Sabina's search endpoint.
    robots_url = BASE + "/robots.txt"
    try:
        r = s.get(robots_url, timeout=20, allow_redirects=True)
        print(
            f"SABINA_DIAG2: ROBOTS status={r.status_code} "
            f"final={r.url} bytes={len(r.content)}"
        )
        robots = r.text
    except Exception as e:
        print(f"SABINA_DIAG2: ROBOTS_ERROR {type(e).__name__}: {e}")
        return []

    sitemaps = []
    for line in robots.splitlines():
        if line.lower().startswith("sitemap:"):
            sm = line.split(":", 1)[1].strip()
            if sm and sm not in sitemaps:
                sitemaps.append(sm)

    print(f"SABINA_DIAG2: ROBOTS_SITEMAPS={sitemaps}")

    # Phase 2: fetch sitemap references and inspect URLs.
    queue = list(sitemaps)
    seen_sm = set()
    product_urls = []

    while queue and len(seen_sm) < 20:
        sm = queue.pop(0)
        if sm in seen_sm:
            continue
        seen_sm.add(sm)

        try:
            r = s.get(sm, timeout=20, allow_redirects=True)
            print(
                f"SABINA_DIAG2: SITEMAP status={r.status_code} "
                f"url={sm} final={r.url} bytes={len(r.content)}"
            )
            if r.status_code != 200:
                continue
            txt = r.text
        except Exception as e:
            print(f"SABINA_DIAG2: SITEMAP_ERROR url={sm} {type(e).__name__}: {e}")
            continue

        # XML sitemap URL extraction, deliberately independent of sitemap
        # parser assumptions.
        locs = re.findall(r"<loc>\s*(.*?)\s*</loc>", txt, flags=re.I | re.S)
        print(f"SABINA_DIAG2: SITEMAP_LOCS count={len(locs)} url={sm}")

        for loc in locs:
            loc = re.sub(r"\s+", "", loc)
            if loc.lower().endswith(".xml") or "sitemap" in loc.lower():
                if loc not in seen_sm and len(seen_sm) + len(queue) < 100:
                    queue.append(loc)
            elif _is_product_url(loc):
                product_urls.append(loc)

    # Deduplicate while preserving order.
    product_urls = list(dict.fromkeys(product_urls))
    print(f"SABINA_DIAG2: PRODUCT_URLS_TOTAL={len(product_urls)}")

    # Phase 3: score URLs from sitemap data. This is the key test:
    # if Liquid Brun is discoverable generically, it should surface here.
    scored = []
    for u in product_urls:
        sc = _score(u, "", qwords)
        if sc > 0:
            scored.append((sc, u))

    scored.sort(key=lambda x: (-x[0], x[1]))
    print(f"SABINA_DIAG2: URL_MATCHES={len(scored)}")

    for sc, u in scored[:20]:
        print(f"SABINA_DIAG2: URL_CANDIDATE score={sc:.3f} url={u}")

    # Phase 4: verify only the best candidates, not a hard-coded product.
    results = []
    for sc, u in scored[:10]:
        try:
            r = s.get(u, timeout=20, allow_redirects=True)
            print(
                f"SABINA_DIAG2: PRODUCT_REQUEST status={r.status_code} "
                f"url={u} final={r.url} bytes={len(r.content)}"
            )
            if r.status_code != 200:
                continue

            soup = BeautifulSoup(r.text, "html.parser")
            title = ""
            h1 = soup.find("h1")
            if h1:
                title = " ".join(h1.stripped_strings)
            if not title and soup.title:
                title = " ".join(soup.title.stripped_strings)

            page_score = _score(u, title, qwords)
            print(
                f"SABINA_DIAG2: PRODUCT_PAGE title={title!r} "
                f"score={page_score:.3f}"
            )

            if page_score > 0:
                results.append({
                    "name": title,
                    "url": r.url,
                    "price": None,
                })
        except Exception as e:
            print(f"SABINA_DIAG2: PRODUCT_ERROR url={u} {type(e).__name__}: {e}")

    print(f"SABINA_DIAG2: COMPLETE results={len(results)}")
    return results
