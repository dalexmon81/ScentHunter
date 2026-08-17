import re
import html as html_lib
from urllib.parse import urljoin, urlsplit, parse_qs, urlencode

import requests
from bs4 import BeautifulSoup

BASE = "https://www.sabina.com"
TIMEOUT = 15

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
        "Mobile/15E148 Safari/604.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Referer": BASE + "/fr/",
}

ROOTS = (
    BASE + "/fr/7-parfums-pour-homme",
    BASE + "/fr/31-fragrances-pour-homme",
    BASE + "/fr/6-parfums-pour-femme",
    BASE + "/fr/30-fragrances-pour-femme",
    BASE + "/fr/864-parfums-arabes-pour-femmes",
    BASE + "/fr/865-parfums-arabes-pour-hommes",
    BASE + "/fr/890-parfumerie-de-niche",
    BASE + "/fr/688-parfums-de-niche-pour-femme",
    BASE + "/fr/891-perfumes-nicho-unisex",
)

def clean(v):
    return re.sub(r"\s+", " ", html_lib.unescape(str(v or ""))).strip()

def norm(v):
    v = clean(v).lower()
    v = re.sub(r"[^a-z0-9]+", " ", v)
    return re.sub(r"\s+", " ", v).strip()

def tokens(q):
    return [x for x in re.split(r"[^a-z0-9]+", norm(q)) if len(x) > 1]

def product_url(url):
    try:
        p = urlsplit(url)
        if p.netloc.lower() not in ("sabina.com", "www.sabina.com"):
            return False
        return bool(re.search(r"/fr/.*/\d+[-/][^?#]*\.html$", p.path, re.I))
    except Exception:
        return False

def exact(text, query):
    n = norm(text)
    return bool(tokens(query)) and all(t in n for t in tokens(query))

def show_response(label, response, query):
    final = response.url
    ctype = response.headers.get("content-type", "")
    body = response.text
    print(f"DIAG: {label}")
    print(f"DIAG: STATUS={response.status_code}")
    print(f"DIAG: FINAL={final}")
    print(f"DIAG: TYPE={ctype}")
    print(f"DIAG: BYTES={len(response.content)}")
    print(f"DIAG: QUERY_IN_HTML={norm(query) in norm(body)}")
    print(f"DIAG: TOKEN_HITS=" + str({
        t: norm(body).count(t) for t in tokens(query)
    }))

    soup = BeautifulSoup(body, "html.parser")
    product_links = []
    exact_links = []

    for a in soup.find_all("a", href=True):
        u = urljoin(final, a["href"])
        if not product_url(u):
            continue
        u = u.split("#")[0]
        if u not in product_links:
            product_links.append(u)
        text = clean(a.get_text(" ", strip=True))
        if exact(text + " " + u, query) and u not in exact_links:
            exact_links.append(u)

    print(f"DIAG: PRODUCT_LINKS={len(product_links)}")
    print(f"DIAG: EXACT_PRODUCT_LINKS={len(exact_links)}")
    for u in exact_links[:10]:
        print(f"DIAG: EXACT_URL={u}")

    return soup, product_links, exact_links

def main():
    query = " ".join(__import__("sys").argv[1:]).strip() or "Liquid brun"
    print(f"DIAG: START query={query!r}")

    s = requests.Session()
    s.headers.update(HEADERS)

    # TEST 1 — inspect the site's actual search form.
    try:
        r = s.get(BASE + "/fr/", timeout=TIMEOUT)
        print(f"DIAG: HOME status={r.status_code} final={r.url} bytes={len(r.content)}")
        soup = BeautifulSoup(r.text, "html.parser")
        forms = []
        for form in soup.find_all("form"):
            action = urljoin(r.url, form.get("action") or "")
            method = (form.get("method") or "get").upper()
            fields = []
            for inp in form.find_all(["input", "select"]):
                name = inp.get("name")
                if name:
                    fields.append((name, inp.get("value") or ""))
            marker = clean(form.get_text(" ", strip=True))
            forms.append((action, method, fields, marker[:120]))

        print(f"DIAG: SEARCH_FORMS_TOTAL={len(forms)}")
        for i, (action, method, fields, marker) in enumerate(forms, 1):
            joined = " ".join(x[0].lower() for x in fields)
            if any(x in joined for x in ("search", "recherche", "query", "s")):
                print(f"DIAG: SEARCH_FORM_{i} action={action} method={method} fields={fields} text={marker!r}")

    except Exception as e:
        print(f"DIAG: HOME_ERROR={e!r}")

    # TEST 2 — try the search routes suggested by the site's form structure.
    # These are discovery mechanisms, not product seeds.
    candidates = [
        (BASE + "/fr/recherche", {"s": query}),
        (BASE + "/fr/recherche", {"controller": "search", "s": query}),
        (BASE + "/fr/search", {"s": query}),
        (BASE + "/fr/search", {"q": query}),
    ]

    seen = set()
    for i, (base, params) in enumerate(candidates, 1):
        try:
            u = base + "?" + urlencode(params)
            if u in seen:
                continue
            seen.add(u)
            r = s.get(u, timeout=TIMEOUT)
            soup, products, exacts = show_response(f"SEARCH_{i}", r, query)
        except Exception as e:
            print(f"DIAG: SEARCH_{i}_ERROR={e!r}")

    # TEST 3 — one generic perfume category, then follow only its own
    # pagination. This tells us whether the existing fallback can actually
    # discover product URLs and where matching breaks.
    for i, root in enumerate(ROOTS[:4], 1):
        try:
            r = s.get(root, timeout=TIMEOUT)
            soup, products, exacts = show_response(f"CATEGORY_{i}", r, query)
            pagination = []
            for a in soup.find_all("a", href=True):
                u = urljoin(r.url, a["href"])
                if "?" in u and re.search(r"[?&](?:p|page)=\d+", u, re.I):
                    if u not in pagination:
                        pagination.append(u)
            print(f"DIAG: CATEGORY_{i}_PAGINATION={len(pagination)}")
            for u in pagination[:5]:
                print(f"DIAG: PAGE_URL={u}")
        except Exception as e:
            print(f"DIAG: CATEGORY_{i}_ERROR={e!r}")

    print("DIAG: DONE")

if __name__ == "__main__":
    main()
