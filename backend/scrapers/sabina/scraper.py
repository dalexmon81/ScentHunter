import json
import re
import time
import traceback
from collections import OrderedDict
from urllib.parse import urljoin, urlparse, parse_qs, quote_plus

import requests
from bs4 import BeautifulSoup


STORE = "Sabina"
BASE = "https://www.sabina.com"
TIMEOUT = 12
MAX_BODY = 3_000_000

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
        "Mobile/15E148 Safari/604.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8,fr;q=0.7",
    "Referer": BASE + "/it/",
}

PRICE_RE = re.compile(r"(?<!\d)(\d{1,4}(?:[.,]\d{2}))\s*€")
PRODUCT_PATH_RE = re.compile(
    r"^/(?:it|fr|en|pt)/"
    r"(?!content/|ricerca(?:_old)?(?:/|$)|marchi/|negozi/|contatto|faq|"
    r"carrello|ordine|stato-ordine|il-mio-conto|module/)"
)

STOP_PATHS = (
    "/content/",
    "/ricerca",
    "/ricerca_old",
    "/marchi/",
    "/negozi/",
    "/contatto",
    "/faq",
    "/carrello",
    "/ordine",
    "/stato-ordine",
    "/il-mio-conto",
    "/module/",
)

SEARCH_FORMS = []
SITEMAP_HINTS = (
    "/sitemap.xml",
    "/1_index_sitemap.xml",
    "/sitemap_index.xml",
)

# These are not product URLs and are not tied to one perfume.
# They are only the common native search mechanisms exposed by Sabina's
# own PrestaShop/SellBoost HTML configuration.
COMMON_SEARCH_PATHS = (
    "/it/ricerca",
    "/fr/recherche",
    "/en/search",
    "/pt/pesquisa",
    "/it/ricerca_old",
    "/fr/recherche_old",
    "/en/search_old",
    "/pt/pesquisa_old",
)


def clean(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()


def norm(v):
    s = clean(v).lower()
    s = re.sub(r"[\u2018\u2019\u201c\u201d]", "'", s)
    s = re.sub(r"[^a-z0-9à-ÿ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def tokens(query):
    return [x for x in norm(query).split() if len(x) > 1]


def price(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return f"{float(v):.2f}".replace(".", ",") + " €"
    m = PRICE_RE.search(clean(v))
    if m:
        return m.group(1).replace(".", ",") + " €"
    m = re.search(r"(?<!\d)(\d{1,4}[.,]\d{2})(?!\d)", clean(v))
    return (m.group(1).replace(".", ",") + " €") if m else None


def product_url(url):
    if not url:
        return False
    u = urljoin(BASE, url).split("#")[0]
    p = urlparse(u)
    if p.netloc.lower() not in {"sabina.com", "www.sabina.com"}:
        return False
    return bool(PRODUCT_PATH_RE.match(p.path))


def query_match(text, query, require_all=True):
    t = norm(text)
    ts = tokens(query)
    if not ts:
        return False
    if require_all:
        return all(x in t for x in ts)
    return any(x in t for x in ts)


def request(session, label, url, method="GET", **kwargs):
    started = time.perf_counter()
    print(f"SABINA_FORENSIC: HTTP_START label={label} method={method} url={url}", flush=True)
    try:
        r = session.request(
            method,
            url,
            timeout=TIMEOUT,
            allow_redirects=True,
            **kwargs,
        )
        elapsed = time.perf_counter() - started
        body = r.content[:MAX_BODY]
        ctype = r.headers.get("content-type", "")
        print(
            f"SABINA_FORENSIC: HTTP_END label={label} status={r.status_code} "
            f"elapsed={elapsed:.3f}s final={r.url} bytes={len(r.content)} type={ctype!r}",
            flush=True,
        )
        return r, {
            "label": label,
            "method": method,
            "requested_url": url,
            "final_url": r.url,
            "status": r.status_code,
            "elapsed": round(elapsed, 3),
            "bytes": len(r.content),
            "content_type": ctype,
            "server": r.headers.get("server"),
            "location": r.headers.get("location"),
            "body": body.decode(r.encoding or "utf-8", errors="replace"),
        }
    except Exception as exc:
        elapsed = time.perf_counter() - started
        print(
            f"SABINA_FORENSIC: HTTP_ERROR label={label} elapsed={elapsed:.3f}s "
            f"error={type(exc).__name__}: {exc}",
            flush=True,
        )
        return None, {
            "label": label,
            "method": method,
            "requested_url": url,
            "status": None,
            "elapsed": round(elapsed, 3),
            "error": f"{type(exc).__name__}: {exc}",
        }


def detect_block(body, status):
    low = norm(body)
    markers = (
        "captcha",
        "cloudflare",
        "access denied",
        "too many requests",
        "robot check",
        "verify you are human",
        "challenge",
    )
    hits = [m for m in markers if m in low]
    return {
        "blocked": status in (403, 429) or bool(hits),
        "markers": hits,
    }


def extract_product_links(html):
    soup = BeautifulSoup(html or "", "html.parser")
    found = OrderedDict()

    for a in soup.find_all("a", href=True):
        u = urljoin(BASE, a.get("href"))
        if not product_url(u):
            continue
        text = clean(a.get_text(" ", strip=True))
        title = clean(a.get("title"))
        aria = clean(a.get("aria-label"))
        context = " | ".join(x for x in (text, title, aria) if x)
        found[u.split("#")[0]] = context

    # JSON/JS may contain escaped absolute or relative product links.
    patterns = [
        r'https?://(?:www\.)?sabina\.com/(?:it|fr|en|pt)/[^"\'<>\s]+',
        r'["\']((?:/(?:it|fr|en|pt)/)[^"\']+)["\']',
    ]
    for pat in patterns:
        for m in re.findall(pat, html or "", re.I):
            raw = m if isinstance(m, str) else m[0]
            u = urljoin(BASE, raw).split("#")[0]
            if product_url(u):
                found.setdefault(u, "")

    return found


def extract_search_forms(html):
    soup = BeautifulSoup(html or "", "html.parser")
    forms = []
    for form in soup.find_all("form"):
        action = form.get("action")
        method = (form.get("method") or "get").lower()
        if not action:
            continue
        inputs = []
        for inp in form.find_all(["input", "select"]):
            name = inp.get("name")
            if name:
                inputs.append({
                    "name": name,
                    "value": inp.get("value", ""),
                    "type": inp.get("type", ""),
                })
        text = clean(form.get_text(" ", strip=True))
        forms.append({
            "action": urljoin(BASE, action),
            "method": method,
            "inputs": inputs,
            "text": text[:300],
        })
    return forms


def extract_native_config(html):
    text = html or ""
    out = {}

    patterns = {
        "ece_ajaxurl": r"""ece_ajaxurl\s*=\s*['"]([^'"]+)['"]""",
        "ece_search_page": r"""ece_search_page\s*=\s*['"]([^'"]+)['"]""",
        "ecc_ajaxlink": r"""ecc_ajaxlink\s*=\s*['"]([^'"]+)['"]""",
        "af_ajax_path": r"""af_ajax_path\s*=\s*['"]([^'"]+)['"]""",
        "sellboost_api": r"""apiUrl\s*:\s*['"]([^'"]+)['"]""",
        "sellboost_failover": r"""failoverUrl\s*:\s*['"]([^'"]+)['"]""",
        "sellboost_shopdata": r"""shopDataUrl\s*:\s*['"]([^'"]+)['"]""",
        "search_input_name": r"""id=["']search_query_top["'][^>]*name=["']([^"']+)["']""",
    }
    for key, pat in patterns.items():
        m = re.search(pat, text, re.I)
        if m:
            out[key] = urljoin(BASE, m.group(1))

    # The HTML can contain an exact failover/search URL template.
    for key in ("ece_search_page", "sellboost_failover", "sellboost_shopdata"):
        if key in out:
            out[key] = out[key].replace("\\/", "/")

    return out


def extract_sitemaps_from_html(html):
    out = []
    soup = BeautifulSoup(html or "", "html.parser")
    for a in soup.find_all("a", href=True):
        href = urljoin(BASE, a["href"])
        if "sitemap" in href.lower():
            out.append(href)
    for raw in re.findall(r'https?://[^"\']*sitemap[^"\']*', html or "", re.I):
        out.append(raw.replace("\\/", "/"))
    return list(dict.fromkeys(out))


def parse_search_result(html, query):
    soup = BeautifulSoup(html or "", "html.parser")
    candidates = []
    links = extract_product_links(html)

    # Keep every candidate first; final product-page validation is separate.
    for u, context in links.items():
        candidates.append({
            "url": u,
            "context": context,
            "query_in_context": query_match(context + " " + u, query, True),
        })

    # JSON-LD / embedded JSON can expose product names even if anchor text is empty.
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.get_text(strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue

        def walk(x):
            if isinstance(x, dict):
                name = x.get("name") or x.get("title")
                u = x.get("url") or x.get("@id")
                if name and u:
                    uu = urljoin(BASE, str(u))
                    if product_url(uu):
                        candidates.append({
                            "url": uu.split("#")[0],
                            "context": clean(name),
                            "query_in_context": query_match(
                                clean(name) + " " + uu, query, True
                            ),
                        })
                for v in x.values():
                    walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)

        walk(data)

    ded = OrderedDict()
    for c in candidates:
        ded.setdefault(c["url"], c)
    return list(ded.values())


def parse_product_page(html, url, query):
    soup = BeautifulSoup(html or "", "html.parser")
    title = ""
    h1 = soup.find("h1")
    if h1:
        title = clean(h1.get_text(" ", strip=True))
    if not title and soup.title:
        title = clean(soup.title.get_text(" ", strip=True))

    brand = ""
    for sel in ('meta[itemprop="brand"]', 'meta[property="product:brand"]'):
        el = soup.select_one(sel)
        if el and el.get("content"):
            brand = clean(el.get("content"))
            break

    prices = []
    for el in soup.select(
        '[itemprop="price"], .price, .current-price, .product-price, '
        '[data-price], meta[property="product:price:amount"]'
    ):
        val = el.get("content") or el.get_text(" ", strip=True)
        p = price(val)
        if p:
            prices.append(p)

    # JSON-LD product data.
    jsonld_products = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.get_text(strip=True))
        except Exception:
            continue

        def walk(x):
            if isinstance(x, dict):
                typ = str(x.get("@type", "")).lower()
                if "product" in typ or "offer" in typ:
                    jsonld_products.append(x)
                for v in x.values():
                    walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)

        walk(data)

    for item in jsonld_products:
        if not title and item.get("name"):
            title = clean(item["name"])
        b = item.get("brand")
        if not brand and isinstance(b, dict):
            brand = clean(b.get("name"))
        elif not brand and isinstance(b, str):
            brand = clean(b)

        offer = item.get("offers")
        if isinstance(offer, dict):
            p = price(offer.get("price"))
            if p:
                prices.append(p)
        elif isinstance(offer, list):
            for off in offer:
                if isinstance(off, dict):
                    p = price(off.get("price"))
                    if p:
                        prices.append(p)

    body_text = clean(soup.get_text(" ", strip=True))
    match_all = query_match(title + " " + brand + " " + body_text[:100000], query, True)

    return {
        "url": url,
        "title": title,
        "brand": brand,
        "prices": list(dict.fromkeys(prices))[:10],
        "query_match": match_all,
        "has_product_jsonld": bool(jsonld_products),
        "body_has_tokens": {
            t: t in norm(body_text) for t in tokens(query)
        },
        "bytes": len(html or ""),
    }


def walk_sitemap(session, sitemap_url, query, report, depth=0, seen=None):
    if seen is None:
        seen = set()
    if depth > 2 or sitemap_url in seen:
        return []
    seen.add(sitemap_url)

    r, meta = request(session, f"SITEMAP_{len(seen)}", sitemap_url)
    report["http"].append({k: v for k, v in meta.items() if k != "body"})
    if not r or r.status_code != 200:
        return []

    text = meta.get("body", "")
    soup = BeautifulSoup(text, "xml")
    locs = [clean(x.get_text()) for x in soup.find_all("loc")]
    product_urls = []

    for loc in locs:
        if product_url(loc):
            if query_match(loc, query, False):
                product_urls.append(loc)
        elif "sitemap" in loc.lower() and depth < 2:
            product_urls.extend(
                walk_sitemap(session, loc, query, report, depth + 1, seen)
            )

    return list(dict.fromkeys(product_urls))


def diagnose_search(query):
    query = clean(query)
    started = time.perf_counter()

    report = {
        "query": query,
        "tokens": tokens(query),
        "status": "RUNNING",
        "steps": [],
        "http": [],
        "discovery": {
            "forms": [],
            "native_config": {},
            "search_attempts": [],
            "candidate_urls": [],
            "candidate_matches": [],
            "sitemap_matches": [],
        },
        "validation": [],
        "integration": {},
        "diagnosis": "",
        "definitive_reason": "",
    }

    print("=" * 78, flush=True)
    print(f"SABINA_FORENSIC: START query={query!r}", flush=True)
    print(f"SABINA_FORENSIC: TOKENS={tokens(query)}", flush=True)

    if not query:
        report["status"] = "ERROR"
        report["definitive_reason"] = "Query vuota."
        return report

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        # STEP 1 — Establish real browser-like session and inspect home.
        for lang, path in (("it", "/it/"), ("fr", "/fr/"), ("en", "/en/"), ("pt", "/pt/")):
            r, meta = request(session, f"HOME_{lang.upper()}", BASE + path)
            report["http"].append({k: v for k, v in meta.items() if k != "body"})
            if r and r.status_code == 200:
                body = meta.get("body", "")
                report["discovery"]["forms"].extend(extract_search_forms(body))
                report["discovery"]["native_config"].update(extract_native_config(body))
                if not report["discovery"].get("sitemaps_from_home"):
                    report["discovery"]["sitemaps_from_home"] = extract_sitemaps_from_html(body)
                break

        # STEP 2 — Inspect the exact native search form/config.
        forms = report["discovery"]["forms"]
        report["discovery"]["forms"] = list({
            (x["action"], x["method"], tuple(i["name"] for i in x["inputs"])): x
            for x in forms
        }.values())

        config = report["discovery"]["native_config"]
        search_actions = []

        for f in report["discovery"]["forms"]:
            action = f["action"]
            names = {i["name"] for i in f["inputs"]}
            if "search_query" in names or "s" in names or "q" in names:
                search_actions.append((action, f["method"], names))

        for action in COMMON_SEARCH_PATHS:
            search_actions.append((urljoin(BASE, action), "get", {"search_query", "s", "q"}))

        if config.get("ece_search_page"):
            search_actions.append((config["ece_search_page"], "get", {"search_query"}))
        if config.get("sellboost_failover"):
            search_actions.append((config["sellboost_failover"], "get", {"search_query"}))

        ded_actions = []
        seen_actions = set()
        for a, m, names in search_actions:
            key = (a, m)
            if key not in seen_actions:
                seen_actions.add(key)
                ded_actions.append((a, m, names))

        # STEP 3 — Test native search mechanisms with the real query.
        for idx, (action, method, names) in enumerate(ded_actions, 1):
            parsed = urlparse(action)
            path = parsed.path.lower()

            if method == "post":
                data = {"search_query": query, "s": query, "q": query}
                r, meta = request(
                    session,
                    f"NATIVE_SEARCH_{idx}",
                    action,
                    method="POST",
                    data=data,
                    headers={**HEADERS, "X-Requested-With": "XMLHttpRequest"},
                )
            else:
                # Use the parameter that the actual action/form exposes first.
                param = "search_query"
                if "search_query" not in names and "s" in names:
                    param = "s"
                elif "search_query" not in names and "q" in names:
                    param = "q"
                url = action
                sep = "&" if "?" in url else "?"
                url = f"{url}{sep}{param}={quote_plus(query)}"
                r, meta = request(session, f"NATIVE_SEARCH_{idx}", url)

            entry = {k: v for k, v in meta.items() if k != "body"}
            body = meta.get("body", "")
            entry["block_detection"] = detect_block(body, meta.get("status"))
            entry["query_tokens_in_body"] = {
                t: t in norm(body) for t in tokens(query)
            }

            candidates = []
            if r and meta.get("status") == 200:
                candidates = parse_search_result(body, query)
                entry["product_links_total"] = len(extract_product_links(body))
                entry["query_candidates"] = len(candidates)
                entry["matching_candidates"] = [
                    c for c in candidates if c["query_in_context"]
                ]
                for c in candidates:
                    report["discovery"]["candidate_urls"].append(c["url"])
                    if c["query_in_context"]:
                        report["discovery"]["candidate_matches"].append(c)

            report["discovery"]["search_attempts"].append(entry)

        # STEP 4 — Discover sitemap(s) from HTML/config.
        sitemap_urls = []
        sitemap_urls.extend(report["discovery"].get("sitemaps_from_home", []))
        for hint in SITEMAP_HINTS:
            sitemap_urls.append(urljoin(BASE, hint))
        sitemap_urls = list(dict.fromkeys(sitemap_urls))

        for sm in sitemap_urls:
            matches = walk_sitemap(session, sm, query, report)
            report["discovery"]["sitemap_matches"].extend(matches)

        # STEP 5 — Add candidates found by native search + sitemap.
        all_candidates = list(dict.fromkeys(
            report["discovery"]["candidate_urls"]
            + report["discovery"]["sitemap_matches"]
        ))
        report["discovery"]["candidate_urls"] = all_candidates[:60]

        # STEP 6 — Validate REAL product pages, never trust discovery alone.
        for idx, url in enumerate(all_candidates[:24], 1):
            r, meta = request(session, f"PRODUCT_{idx}", url)
            entry = {k: v for k, v in meta.items() if k != "body"}
            if r and meta.get("status") == 200:
                parsed = parse_product_page(meta.get("body", ""), meta.get("final_url", url), query)
                entry["parsed"] = parsed
                if parsed["query_match"] and parsed["prices"]:
                    report["validation"].append(entry)
            else:
                report["validation"].append(entry)

        # STEP 7 — Test the current deployed scraper interface, if importable.
        # This does not decide discovery; it identifies integration loss separately.
        try:
            from importlib import import_module
            module = import_module("scrapers.sabina.scraper")
            report["integration"]["module_import"] = "OK"
            report["integration"]["has_search"] = hasattr(module, "search")
            report["integration"]["has_scrape"] = hasattr(module, "scrape")
            report["integration"]["has_diagnose_search"] = hasattr(module, "diagnose_search")

            if hasattr(module, "search"):
                try:
                    started_search = time.perf_counter()
                    real_results = module.search(query) or []
                    report["integration"]["search_count"] = len(real_results)
                    report["integration"]["search_elapsed"] = round(
                        time.perf_counter() - started_search, 3
                    )
                    report["integration"]["search_results"] = real_results[:10]
                except Exception as exc:
                    report["integration"]["search_error"] = (
                        f"{type(exc).__name__}: {exc}"
                    )
        except Exception as exc:
            report["integration"]["module_import"] = (
                f"{type(exc).__name__}: {exc}"
            )

        # STEP 8 — Definitive classification.
        native_ok = any(
            x.get("status") == 200
            and x.get("matching_candidates")
            for x in report["discovery"]["search_attempts"]
        )
        sitemap_ok = bool(report["discovery"]["sitemap_matches"])
        validated = [
            x for x in report["validation"]
            if isinstance(x.get("parsed"), dict)
            and x["parsed"].get("query_match")
            and x["parsed"].get("prices")
        ]
        integration_count = report["integration"].get("search_count")

        if validated:
            if isinstance(integration_count, int) and integration_count == 0:
                reason = (
                    "DEFINITIVE: SABINA ESPONE E VALID A IL PRODOTTO, "
                    "MA L'INTEGRAZIONE DELLO SCRAPER LO PERDE. "
                    "Il problema è nel search()/parsing/filtro finale, non nella discovery del sito."
                )
            else:
                reason = (
                    "DEFINITIVE: DISCOVERY E VALIDAZIONE DELLA PAGINA PRODOTTO FUNZIONANO. "
                    "Il prodotto è raggiungibile e verificabile."
                )
        elif native_ok or sitemap_ok:
            reason = (
                "DEFINITIVE: DISCOVERY FUNZIONA MA LA VALIDAZIONE DELLA PAGINA PRODOTTO FALLISCE. "
                "Abbiamo trovato URL candidati, ma nessuno supera titolo/prezzo/contenuto."
            )
        else:
            blocked = any(
                x.get("block_detection", {}).get("blocked")
                for x in report["discovery"]["search_attempts"]
            )
            if blocked:
                reason = (
                    "DEFINITIVE: SABINA BLOCCA/ALTERA LA DISCOVERY HTTP "
                    "(403/429/challenge). Il problema è a monte del parser."
                )
            else:
                statuses = [
                    x.get("status")
                    for x in report["discovery"]["search_attempts"]
                    if x.get("status") is not None
                ]
                reason = (
                    "DEFINITIVE: NESSUN MECCANISMO DI DISCOVERY TESTATO HA RESTITUITO "
                    "UN CANDIDATO VALIDABILE. "
                    f"Status osservati={statuses}. "
                    "Il punto di rottura è nella discovery nativa/sitemap, prima della pagina prodotto."
                )

        report["definitive_reason"] = reason
        report["diagnosis"] = {
            "native_search_candidate_found": native_ok,
            "sitemap_candidate_found": sitemap_ok,
            "validated_product_pages": len(validated),
            "integration_search_count": integration_count,
            "candidate_count": len(all_candidates),
        }
        report["status"] = "DONE"

    except Exception as exc:
        report["status"] = "ERROR"
        report["definitive_reason"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()
        traceback.print_exc()
    finally:
        session.close()

    report["elapsed_total"] = round(time.perf_counter() - started, 3)

    print("=" * 78, flush=True)
    print(f"SABINA_FORENSIC: FINAL {report['definitive_reason']}", flush=True)
    print(f"SABINA_FORENSIC: REPORT={json.dumps(report, ensure_ascii=False)}", flush=True)
    print("=" * 78, flush=True)

    return report


def search(query):
    """
    Compatibilità con ScentHunter.

    Esegue una singola diagnosi completa e restituisce solo i prodotti
    realmente trovati e validati. Non contiene seed o URL di un singolo
    profumo.
    """
    report = diagnose_search(query)
    out = []

    for entry in report.get("validation", []):
        parsed = entry.get("parsed")
        if not isinstance(parsed, dict):
            continue
        if not parsed.get("query_match"):
            continue
        if not parsed.get("prices"):
            continue

        out.append({
            "store": STORE,
            "name": parsed.get("title") or "Sabina",
            "price": parsed["prices"][0],
            "url": parsed.get("url") or entry.get("final_url"),
        })

    # Deduplicate by URL/name.
    seen = set()
    final = []
    for item in out:
        key = (norm(item.get("name")), item.get("url", "").split("#")[0])
        if key in seen:
            continue
        seen.add(key)
        final.append(item)

    return final


def diagnose(query):
    return diagnose_search(query)


def scrape(query):
    return search(query)


def search_sabina(query):
    return search(query)


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]).strip() or "Liquid Brun"
    result = diagnose_search(q)
    print(json.dumps(result, ensure_ascii=False, indent=2))
