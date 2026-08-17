
# TEST DIAGNOSTICO 4
# Questo file NON modifica la discovery di Sabina.
# È pensato per essere caricato da ScentHunter come scraper:
# il test usa la query ricevuta da main, non sys.argv.

import re
from urllib.parse import quote_plus, urljoin
import requests
from bs4 import BeautifulSoup

STORE = "Sabina"
BASE = "https://www.sabina.com"
TIMEOUT = 10

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

def _clean(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()

def scrape(query):
    query = _clean(query)
    print(f"SABINA_TEST4 query_received: {query!r}")

    if not query:
        print("SABINA_TEST4 empty_query")
        return []

    url = BASE + "/it/ricerca_old?s=" + quote_plus(query)
    print("SABINA_TEST4 request:", url)

    try:
        r = requests.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        print(
            "SABINA_TEST4 response:",
            f"status={r.status_code}",
            f"final_url={r.url}",
            f"bytes={len(r.content)}",
            f"content_type={r.headers.get('content-type')}",
        )

        html = r.text
        soup = BeautifulSoup(html, "html.parser")
        low = html.lower()

        print("SABINA_TEST4 query_exact_count:", low.count(query.lower()))

        for word in re.findall(r"[a-z0-9À-ÿ]+", query.lower()):
            print(
                f"SABINA_TEST4 word_{word}_count:",
                low.count(word),
            )

        # Cerca la query nei nodi testuali.
        text_hits = []
        for node in soup.find_all(string=re.compile(re.escape(query), re.I)):
            parent = node.parent
            if parent:
                text_hits.append(parent)

        print("SABINA_TEST4 full_query_text_nodes:", len(text_hits))

        for i, el in enumerate(text_hits[:20], 1):
            print(f"SABINA_TEST4 QUERY_MATCH {i}")
            print(" tag:", el.name)
            print(" class:", " ".join(el.get("class", [])))
            print(" id:", el.get("id", ""))
            print(" text:", _clean(el.get_text(" ", strip=True))[:1200])

            if el.name == "a":
                print(" href:", el.get("href", ""))

        # Cerca Liquid/Brun anche quando non sono consecutivi.
        href_hits = []
        for a in soup.find_all("a", href=True):
            href = urljoin(BASE, a["href"])
            label = _clean(a.get_text(" ", strip=True))

            if (
                re.search(r"liquid|brun", href, re.I)
                or re.search(r"liquid|brun", label, re.I)
            ):
                href_hits.append((href, label))

        print("SABINA_TEST4 href_or_label_hits:", len(href_hits))

        for i, (href, label) in enumerate(href_hits[:50], 1):
            print(f"SABINA_TEST4 HREF_HIT {i}")
            print(" href:", href)
            print(" label:", label[:800])

        # Cerca JSON/script contenenti la query.
        script_hits = 0
        for i, script in enumerate(soup.find_all("script"), 1):
            txt = script.get_text(" ", strip=False)

            if re.search(r"liquid|brun", txt, re.I):
                script_hits += 1
                print(
                    f"SABINA_TEST4 SCRIPT_MATCH {i}: chars={len(txt)}"
                )

                for m in list(re.finditer(r"liquid|brun", txt, re.I))[:5]:
                    a = max(0, m.start() - 700)
                    b = min(len(txt), m.end() + 1500)
                    context = _clean(txt[a:b])
                    print(" --- SCRIPT_CONTEXT ---")
                    print(context[:2200])

        print("SABINA_TEST4 script_hits:", script_hits)

        # Conta strutture che potrebbero essere card/prodotti.
        selectors = [
            '[class*="product"]',
            '[class*="item"]',
            '[class*="result"]',
            '[id*="product"]',
            '[id*="result"]',
            '[data-id-product]',
            '[data-product-id]',
            '[data-product]',
        ]

        for selector in selectors:
            els = soup.select(selector)
            print(
                f"SABINA_TEST4 selector {selector}: {len(els)}"
            )

            shown = 0
            for el in els:
                txt = _clean(el.get_text(" ", strip=True))

                if (
                    re.search(r"liquid|brun", txt, re.I)
                    or selector.startswith("[data-")
                ):
                    print(
                        "  MATCH",
                        "tag=", el.name,
                        "class=", " ".join(el.get("class", [])),
                        "id=", el.get("id", ""),
                        "data-id-product=", el.get("data-id-product", ""),
                        "data-product-id=", el.get("data-product-id", ""),
                    )
                    print("  text=", txt[:1500])
                    shown += 1

                    if shown >= 15:
                        break

        # Questo test non deve produrre risultati falsi.
        # Restituisce [] intenzionalmente.
        print("SABINA_TEST4 END: diagnostic_only")
        return []

    except Exception as e:
        print(
            "SABINA_TEST4 ERROR:",
            type(e).__name__,
            str(e),
        )
        return []

def search(query):
    return scrape(query)

def search_sabina(query):
    return scrape(query)
