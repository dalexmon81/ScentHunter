# TEST DIAGNOSTICO 6 — SITEMAP / ROBOTS
# Nessuna modifica allo scraper.
# Verifica se Sabina espone una sitemap dalla quale possiamo fare
# discovery generica dei prodotti.

import re
import sys
from urllib.parse import urljoin, quote_plus
import requests
from bs4 import BeautifulSoup

BASE = "https://www.sabina.com"
TIMEOUT = 12

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
        "Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.7",
    "Accept": "application/xml,text/xml,text/html;q=0.9,*/*;q=0.8",
}

def clean(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()

def words(query):
    return [
        x for x in re.findall(r"[a-z0-9À-ÿ]+", query.lower())
        if len(x) > 1
    ]

def run(query):
    query = clean(query)
    qwords = words(query)

    print("SABINA_TEST6 query:", query)
    print("SABINA_TEST6 qwords:", qwords)

    s = requests.Session()
    s.headers.update(HEADERS)

    urls = [
        BASE + "/robots.txt",
        BASE + "/sitemap.xml",
        BASE + "/sitemap_index.xml",
        BASE + "/it/sitemap.xml",
        BASE + "/it/sitemap_index.xml",
    ]

    seen_sitemaps = set()
    sitemap_urls = []

    for url in urls:
        try:
            r = s.get(url, timeout=TIMEOUT, allow_redirects=True)
            print(
                "SABINA_TEST6 REQUEST",
                url,
                "status=", r.status_code,
                "final=", r.url,
                "type=", r.headers.get("content-type"),
                "bytes=", len(r.content),
            )

            if r.status_code != 200:
                continue

            text = r.text

            if url.endswith("robots.txt"):
                for line in text.splitlines():
                    if line.lower().startswith("sitemap:"):
                        sm = line.split(":", 1)[1].strip()
                        if sm:
                            sitemap_urls.append(sm)
                            print("SABINA_TEST6 ROBOTS_SITEMAP:", sm)

            # Extract sitemap references from XML/HTML.
            for m in re.findall(
                r"https?://[^<\s\"']+sitemap[^<\s\"']*",
                text,
                re.I,
            ):
                sitemap_urls.append(m.rstrip("]>,"))
        except Exception as e:
            print("SABINA_TEST6 ERROR", url, type(e).__name__, str(e))

    # Add common candidates once.
    for u in urls[1:]:
        sitemap_urls.append(u)

    queue = []
    for u in sitemap_urls:
        if u not in seen_sitemaps:
            seen_sitemaps.add(u)
            queue.append(u)

    product_hits = []
    scanned = 0

    while queue and scanned < 40:
        sm = queue.pop(0)
        scanned += 1

        try:
            r = s.get(sm, timeout=TIMEOUT, allow_redirects=True)
            print(
                "SABINA_TEST6 SITEMAP",
                sm,
                "status=", r.status_code,
                "final=", r.url,
                "bytes=", len(r.content),
            )

            if r.status_code != 200:
                continue

            text = r.text

            # sitemapindex -> child sitemaps
            child_sitemaps = re.findall(
                r"<loc>\s*(https?://[^<]+)\s*</loc>",
                text,
                re.I,
            )

            for loc in child_sitemaps:
                loc = loc.strip()
                if "sitemap" in loc.lower() and loc not in seen_sitemaps:
                    seen_sitemaps.add(loc)
                    queue.append(loc)

            # URL sitemap -> candidate URLs
            for loc in child_sitemaps:
                loc = loc.strip()

                if "sitemap" in loc.lower():
                    continue

                low = loc.lower().replace("-", " ").replace("_", " ")

                if qwords and all(w in low for w in qwords):
                    product_hits.append(loc)

        except Exception as e:
            print(
                "SABINA_TEST6 SITEMAP_ERROR",
                sm,
                type(e).__name__,
                str(e),
            )

    print("SABINA_TEST6 sitemaps_scanned:", scanned)
    print("SABINA_TEST6 sitemap_queue_remaining:", len(queue))
    print("SABINA_TEST6 product_hits:", len(product_hits))

    for i, u in enumerate(product_hits[:100], 1):
        print(f"SABINA_TEST6 HIT {i}:", u)

    s.close()

def scrape(query):
    run(query)
    return []

def search(query):
    return scrape(query)

def search_sabina(query):
    return scrape(query)
