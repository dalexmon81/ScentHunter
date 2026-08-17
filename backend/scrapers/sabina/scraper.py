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
    soup = BeautifulSoup(html, "html.parser")
    out = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(base, a["href"].strip())
        if not _product_like(href) or href in seen:
            continue
        seen.add(href)
        txt = " ".join(a.stripped_strings)
        out.append((href, txt))
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

    # Generic category/brand discovery. No product URL is hard-coded.
    seeds = [
        BASE + "/fr/601_french-avenue",
        BASE + "/fr/865-parfums-arabes-pour-homme",
        BASE + "/fr/864-parfums-arabes-pour-femme",
    ]

    candidates = {}
    for seed in seeds:
        try:
            r = s.get(seed, timeout=20, allow_redirects=True)
            print(f"SABINA_DISCOVERY: SEED status={r.status_code} url={seed} final={r.url} bytes={len(r.content)}")
            if r.status_code != 200:
                continue
            for u, txt in _links(r.text, r.url):
                sc = _score(query, u + " " + txt)
                if sc > 0:
                    candidates[u] = max(candidates.get(u, 0), sc)
        except Exception as e:
            print(f"SABINA_DISCOVERY: SEED_ERROR {seed} {type(e).__name__}: {e}")

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

            price = None
            for el in soup.find_all(string=re.compile(r"[€$£]|\\d+[,.]\\d{2}")):
                t = " ".join(str(el).split())
                m = re.search(r"(?:€|\\$|£)\\s*([0-9]+[,.][0-9]{2})|([0-9]+[,.][0-9]{2})\\s*(?:€|\\$|£)", t)
                if m:
                    price = (m.group(1) or m.group(2)).replace(",", ".")
                    break

            results.append({"name": title, "url": r.url, "price": price})
            print(f"SABINA_DISCOVERY: FOUND name={title!r} price={price!r} url={r.url}")
        except Exception as e:
            print(f"SABINA_DISCOVERY: PRODUCT_ERROR {u} {type(e).__name__}: {e}")

    print(f"SABINA_DISCOVERY: COMPLETE results={len(results)}")
    return results
