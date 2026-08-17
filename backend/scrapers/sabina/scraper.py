import re, sys, json
from urllib.parse import quote_plus, urljoin
import requests
from bs4 import BeautifulSoup

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

q = " ".join(sys.argv[1:]).strip() or "Liquid brun"
url = BASE + "/it/ricerca_old?s=" + quote_plus(q)

print("SABINA_TEST3 query:", q)
print("SABINA_TEST3 url:", url)

try:
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
    html = r.text
    print("SABINA_TEST3 response:", r.status_code, r.url, len(html))

    low = html.lower()
    q_low = q.lower()

    print("SABINA_TEST3 exact_query_count:", low.count(q_low))
    for word in re.findall(r"[a-z0-9]+", q_low):
        print(f"SABINA_TEST3 word_{word}_count:", low.count(word))

    soup = BeautifulSoup(html, "html.parser")

    # 1. Mostra tutti gli elementi che contengono la query.
    matches = []
    for el in soup.find_all(string=re.compile(re.escape(q), re.I)):
        parent = el.parent
        if parent:
            matches.append(parent)

    print("SABINA_TEST3 text_nodes_with_full_query:", len(matches))
    for i, el in enumerate(matches[:20], 1):
        print(f"SABINA_TEST3 QUERY_MATCH {i}:")
        print(" tag:", el.name)
        print(" class:", " ".join(el.get("class", [])))
        print(" id:", el.get("id", ""))
        print(" text:", re.sub(r"\s+", " ", el.get_text(" ", strip=True))[:1000])
        if el.name == "a":
            print(" href:", el.get("href", ""))

    # 2. Cerca Liquid/Brun in script e attributi.
    for script_i, script in enumerate(soup.find_all("script"), 1):
        txt = script.get_text(" ", strip=False)
        if re.search(r"liquid|brun", txt, re.I):
            print(f"SABINA_TEST3 SCRIPT_MATCH {script_i}: chars={len(txt)}")
            for m in list(re.finditer(r"liquid|brun", txt, re.I))[:10]:
                a = max(0, m.start()-500)
                b = min(len(txt), m.end()+1000)
                print(" --- SCRIPT_CONTEXT ---")
                print(re.sub(r"\s+", " ", txt[a:b])[:1800])

    # 3. Cerca href che contengono liquid/brun.
    href_hits = []
    for a in soup.find_all("a", href=True):
        href = urljoin(BASE, a["href"])
        label = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
        if re.search(r"liquid|brun", href, re.I) or re.search(r"liquid|brun", label, re.I):
            href_hits.append((href, label, a.get("class", [])))

    print("SABINA_TEST3 href_or_label_hits:", len(href_hits))
    for i, (href, label, cls) in enumerate(href_hits[:50], 1):
        print(f"SABINA_TEST3 HREF_HIT {i}:")
        print(" href:", href)
        print(" label:", label[:500])
        print(" class:", " ".join(cls))

    # 4. Cerca strutture che sembrano risultati di prodotto.
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

    seen = set()
    for selector in selectors:
        els = soup.select(selector)
        print(f"SABINA_TEST3 selector {selector}: {len(els)}")
        shown = 0
        for el in els:
            if id(el) in seen:
                continue
            seen.add(id(el))
            txt = re.sub(r"\s+", " ", el.get_text(" ", strip=True))
            if txt and (re.search(r"liquid|brun", txt, re.I) or selector in ("[data-id-product]", "[data-product-id]", "[data-product]")):
                print("  MATCH tag=", el.name,
                      "class=", " ".join(el.get("class", [])),
                      "id=", el.get("id",""),
                      "data-id-product=", el.get("data-id-product",""),
                      "data-product-id=", el.get("data-product-id",""))
                print("  text=", txt[:1200])
                shown += 1
                if shown >= 20:
                    break

    # 5. Estrarre URL canonici presenti in link/script.
    urls = []
    for a in soup.find_all("a", href=True):
        u = urljoin(BASE, a["href"])
        if "/it/" in u and u not in urls:
            urls.append(u)

    print("SABINA_TEST3 unique_it_urls:", len(urls))
    for u in urls:
        if re.search(r"liquid|brun", u, re.I):
            print("SABINA_TEST3 PRODUCT_LIKE_URL:", u)

except Exception as e:
    print("SABINA_TEST3 ERROR:", type(e).__name__, str(e))
