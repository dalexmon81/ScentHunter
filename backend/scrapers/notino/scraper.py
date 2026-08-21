from __future__ import annotations

import difflib
import html as html_lib
import json
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


STORE = "Notino"
BASE_URL = "https://www.notino.fr"
SEARCH_URL = BASE_URL + "/search.asp"
SITEMAP_URL = BASE_URL + "/sitemap.xml"
READER_BASE = "https://r.jina.ai/"
TIMEOUT = 8
READER_TIMEOUT = 7
SCRAPER_VERSION = "notino-FR-generic-discovery-2026-08-21-v17-diagnostic"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
}
READER_HEADERS = {"User-Agent": "ScentHunter/1.0", "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7"}

SIZE_RE = re.compile(r"\b(\d{1,4}(?:[.,]\d{1,2})?)\s*(ml|cl|dl|l|oz|fl\s*oz|g|kg)\b", re.I)
PRICE_RE = re.compile(r"(?:€\s*(\d{1,4}[.,]\d{2})|(\d{1,4}[.,]\d{2})\s*€)", re.I)
PRODUCT_ID_RE = re.compile(r"/p-\d+(?:/|$)", re.I)

NON_PERFUME = {
    "gift set","set regalo","set","discovery set","fragrance set","perfume set",
    "parfum set","coffret","bundle","pack","travel set","kit","duo","trio",
    "mystery box","gift box","tester","testeur","sample","shampoo","shower gel",
    "body wash","body lotion","body cream","body milk","deodorant","deo spray",
    "aftershave","after shave","body spray","hair mist","makeup","cosmetics",
    "cosmetic","skincare","skin care","cosmetici",
}
EXCLUDED_PREFIXES = ("/search", "/avis/", "/erfahrungen/", "/magazine/", "/blog/",
                     "/panier", "/cart", "/login", "/compte", "/account")


def _clean(v: Any) -> str:
    s = str(v or "")
    if any(x in s for x in ("Ã©", "Ã¨", "Ã´", "Ã¹", "â‚¬", "Â€")):
        try:
            s = s.encode("cp1252").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return re.sub(r"\s+", " ", s).strip()


def _norm(v: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", _clean(v).lower())).strip()


def _tokens(v: Any, query=False) -> List[str]:
    s = _clean(v)
    if query:
        s = SIZE_RE.sub(" ", s)
    return [x for x in re.findall(r"[a-z0-9]+", s.lower()) if len(x) > 1]


def _non_perfume(v: Any) -> bool:
    text = set(_norm(v).split())
    return any(set(_norm(x).split()).issubset(text) for x in NON_PERFUME)


def _non_perfume_product(name: Any, url: Any = "", title: Any = "") -> bool:
    return _non_perfume(name) or _non_perfume(title) or _non_perfume(unquote(urlparse(str(url)).path))


def _fuzzy(name: Any, query: Any) -> Tuple[bool, Dict[str, bool], int]:
    nt = set(_tokens(name, True))
    qt = _tokens(query, True)
    if not nt or not qt:
        return False, {}, 0
    hits = {}
    fuzzy = 0
    for q in qt:
        if q in nt:
            hits[q] = True
            continue
        best = max(
            ((difflib.SequenceMatcher(None, q, n).ratio(), len(n)) for n in nt),
            default=(0.0, 0),
        )
        hits[q] = best[0] >= 0.80 and abs(len(q) - best[1]) <= 2
        fuzzy += int(hits[q])
    return all(hits.values()), hits, fuzzy


def _requested_sizes(v: Any) -> List[Tuple[str, str]]:
    return [(m.group(1).replace(",", "."), re.sub(r"\s+", "", m.group(2).lower()))
            for m in SIZE_RE.finditer(_clean(v))]


def _size_matches(text: Any, size: Tuple[str, str]) -> bool:
    n, u = size
    np = re.escape(n).replace(r"\.", r"[.,]")
    up = re.escape(u).replace("floz", r"fl\s*oz")
    return bool(re.search(rf"\b{np}\s*{up}\b", _clean(text), re.I))


def _size_valid(text: Any, query: Any) -> bool:
    req = _requested_sizes(query)
    return not req or any(_size_matches(text, x) for x in req)


def _price(v: Any) -> str:
    m = PRICE_RE.search(_clean(v))
    if not m:
        m = re.search(r"\b(\d{1,4}[.,]\d{2})\s*€", _clean(v))
    if not m:
        return ""
    try:
        n = float((m.group(1) or m.group(2)).replace(",", "."))
        return f"{n:.2f}".replace(".", ",") + "€" if n > 0 else ""
    except ValueError:
        return ""


def _product_price(text: Any) -> str:
    s = _clean(text)
    for m in reversed(list(re.finditer(r"prix\s+actuel\s+(?:de\s+)?(\d{1,4}[.,]\d{2})\s*€", s, re.I))):
        after = s[m.end():m.end()+40]
        if not re.match(r"\s*/\s*100\s*(?:ml|g)", after, re.I):
            return _price(m.group(0))
    # Prefer prices tied to a bottle size.
    vals = re.findall(r"\b\d+(?:[.,]\d+)?\s*(?:ml|cl|dl|l|oz|fl\s*oz)\s+(?:de\s+)?(\d{1,4}[.,]\d{2})\s*€", s, re.I)
    if vals:
        return _price(vals[-1] + " €")
    vals = []
    for m in PRICE_RE.finditer(s):
        after = s[m.end():m.end()+40]
        if not re.match(r"\s*/\s*100\s*(?:ml|g)", after, re.I):
            vals.append(m.group(0))
    return _price(vals[-1]) if vals else ""


def _canonical(url: str) -> str:
    try:
        p = urlparse(str(url).split("?")[0].strip())
        if p.netloc.lower() not in {"notino.fr", "www.notino.fr"}:
            return ""
        path = p.path.rstrip("/")
        parts = [x for x in path.split("/") if x]
        if parts and re.fullmatch(r"p-\d+", parts[-1], re.I):
            parts = parts[:-1]
            path = "/" + "/".join(parts)
        return "https://" + p.netloc.lower() + path
    except Exception:
        return ""


def _product_url(url: str) -> bool:
    u = _canonical(url)
    if not u:
        return False
    path = urlparse(u).path.rstrip("/").lower()
    if not path or any(path.startswith(x) for x in EXCLUDED_PREFIXES):
        return False
    parts = [x for x in path.split("/") if x]
    return len(parts) >= 2


def _slug(url: str) -> str:
    path = unquote(urlparse(_canonical(url)).path).strip("/")
    parts = [x for x in path.split("/") if x]
    if not parts:
        return ""
    s = parts[-1]
    if re.fullmatch(r"p-\d+", s, re.I) and len(parts) >= 2:
        s = parts[-2]
    s = re.sub(r"-\d{5,}$", "", s)
    return _clean(re.sub(r"[-_]+", " ", s))


def _brand(url: str) -> str:
    path = unquote(urlparse(_canonical(url)).path).strip("/")
    parts = [x for x in path.split("/") if x]
    return _clean(parts[0].replace("-", " ")) if len(parts) >= 2 else ""


def _name_from_url(url: str) -> str:
    s, b = _slug(url), _brand(url)
    return _clean(f"{b} {s}" if b else s)


def _reader_url(raw: Any) -> Optional[str]:
    v = html_lib.unescape(str(raw or "")).strip().replace("\\/", "/").replace("\\u002F", "/")
    if v.startswith("//"):
        v = "https:" + v
    elif v.startswith("/"):
        v = urljoin(BASE_URL, v)
    return _canonical(v) if _product_url(v) else None


def _card_text(link) -> str:
    best = _clean(link.get_text(" ", strip=True))
    node = link
    for _ in range(8):
        node = getattr(node, "parent", None)
        if node is None:
            break
        t = _clean(node.get_text(" ", strip=True))
        if len(t) > len(best):
            best = t
        if 30 <= len(t) <= 1200 and _product_price(t):
            return t
    return best


def _candidate(url: str, anchor: str, card: str, query: str, source: str) -> Optional[Dict[str, Any]]:
    url = _canonical(url)
    if not _product_url(url):
        return None
    anchor, card = _clean(anchor), _clean(card)
    slug_name = _slug(url)
    url_name = _name_from_url(url)

    # Discovery must not reject a URL solely because its slug/brand parser is imperfect.
    # Prefer the real search-card text; use URL-derived identity only as fallback.
    names = [anchor, card, url_name, slug_name]
    name = next((x for x in names if x and not _non_perfume(x) and _fuzzy(x, query)[0]), "")
    if not name:
        return None
    if _non_perfume_product(name, url, anchor):
        return None

    matched, hits, fuzzy = _fuzzy(name, query)
    if not matched:
        return None

    context = f"{anchor} {card} {url_name}"
    req = _requested_sizes(query)
    size_hit = not req or any(_size_matches(context, x) for x in req)
    score = sum(hits.values()) * 5 + fuzzy * 2 + (6 if size_hit else 0)
    if _product_price(context):
        score += 1
    if name == url_name:
        score += 1

    return {
        "url": url, "anchor_text": anchor or name, "card_text": card or anchor or name,
        "name": name, "score": score, "token_hits": hits,
        "contains_all_query_tokens": matched, "requested_size": bool(req),
        "size_match_in_search_context": size_hit, "source": source,
    }


def _extract_candidates_html(html: str, query: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html or "", "html.parser")
    found = {}
    for link in soup.find_all("a", href=True):
        url = urljoin(BASE_URL, _clean(link.get("href"))).split("?")[0]
        c = _candidate(url, link.get_text(" ", strip=True), _card_text(link), query, "direct-search")
        if c and (c["url"] not in found or c["score"] > found[c["url"]]["score"]):
            found[c["url"]] = c
    return sorted(found.values(), key=lambda x: (-x["score"], x["url"]))


def _reader_candidates(text: str, query: str) -> List[Dict[str, Any]]:
    raw = html_lib.unescape(str(text or "")).replace("\\/", "/").replace("\\u002F", "/")
    found = {}
    md = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
    lines = raw.splitlines()
    for i, line in enumerate(lines):
        for m in md.finditer(line):
            url = _reader_url(m.group(2))
            if not url:
                continue
            anchor = _clean(m.group(1))
            context = "\n".join(lines[max(0, i-80):i+1])
            c = _candidate(url, anchor, context, query, "reader-markdown")
            if c:
                found[url] = c if url not in found or c["score"] > found[url]["score"] else found[url]

    patterns = [
        r"https?://(?:www\.)?notino\.fr/[^\s<>)\]\"']+",
        r"(?:https?:)?//(?:www\.)?notino\.fr/[^\s<>)\]\"']+",
    ]
    for pat in patterns:
        for m in re.finditer(pat, raw, re.I):
            url = _reader_url(m.group(0))
            if not url:
                continue
            c = _candidate(url, _name_from_url(url), _name_from_url(url), query, "reader-url")
            if c:
                found[url] = c if url not in found or c["score"] > found[url]["score"] else found[url]
    return sorted(found.values(), key=lambda x: (-x["score"], x["url"]))


def _request(s, url):
    r = s.get(url, timeout=TIMEOUT, allow_redirects=True)
    r.raise_for_status()
    return r


def _reader(s, url):
    r = s.get(READER_BASE + url, headers=READER_HEADERS, timeout=READER_TIMEOUT, allow_redirects=True)
    r.raise_for_status()
    return r


def _search_urls(query: str) -> List[str]:
    q = quote_plus(query)
    return [f"{SEARCH_URL}?exps={q}", f"{BASE_URL}/search?query={q}"]


def _reader_discovery(query: str, session) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    variants = []
    for v in (query, " ".join(reversed(_tokens(query, True)))):
        v = _clean(v)
        if v and v not in variants:
            variants.append(v)

    allc, pages = {}, []
    for variant in variants:
        u = f"{BASE_URL}/search?query={quote_plus(variant)}"
        try:
            r = _reader(session, u)
            found = _reader_candidates(r.text, query)
            for c in found:
                old = allc.get(c["url"])
                if old is None or c["score"] > old["score"]:
                    allc[c["url"]] = c
            pages.append({"url": u, "query": variant, "status": r.status_code,
                          "html_length": len(r.text or ""), "candidate_count": len(found), "reader": True})
        except requests.RequestException as exc:
            pages.append({"url": u, "query": variant, "error": f"{type(exc).__name__}: {exc}", "reader": True})

    ordered = sorted(allc.values(), key=lambda x: (-x["score"], x["url"]))
    return ordered, {
        "query": query, "discovery_queries": variants,
        "search_urls": [f"{BASE_URL}/search?query={quote_plus(x)}" for x in variants],
        "pages": pages, "raw_product_urls": len(ordered),
        "candidate_urls": len(ordered), "fallback": "jina-reader",
    }


def _sitemap_discovery(query: str, session) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    # Sitemap is a fallback only; keep it generic and bounded.
    try:
        r = _request(session, SITEMAP_URL)
        text = r.text
    except requests.RequestException:
        return [], {"sitemap": "unavailable"}

    locs = re.findall(r"<loc>\s*(.*?)\s*</loc>", text, re.I | re.S)
    candidates = {}
    for raw in locs[:20000]:
        u = _reader_url(html_lib.unescape(raw.strip()))
        if not u:
            continue
        c = _candidate(u, _name_from_url(u), _name_from_url(u), query, "sitemap")
        if c:
            candidates[u] = c
    ordered = sorted(candidates.values(), key=lambda x: (-x["score"], x["url"]))
    return ordered, {"sitemap": SITEMAP_URL, "candidate_urls": len(ordered)}


def _discover(query: str, session) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    candidates, report = _reader_discovery(query, session)

    # Direct Notino search is attempted first. If blocked, Jina remains the primary fallback.
    direct_pages = []
    direct = {}
    for u in _search_urls(query):
        try:
            r = _request(session, u)
            found = _extract_candidates_html(r.text, query)
            direct_pages.append({"url": u, "status": r.status_code, "candidate_count": len(found),
                                 "cloudflare": any(x in r.text.lower() for x in ("just a moment", "cf-chl-", "challenge-platform"))})
            for c in found:
                old = direct.get(c["url"])
                if old is None or c["score"] > old["score"]:
                    direct[c["url"]] = c
            if found:
                break
        except requests.RequestException as exc:
            direct_pages.append({"url": u, "error": f"{type(exc).__name__}: {exc}"})

    merged = {c["url"]: c for c in candidates}
    for c in direct.values():
        old = merged.get(c["url"])
        if old is None or c["score"] > old["score"]:
            merged[c["url"]] = c

    if not merged:
        sitemap, sm_report = _sitemap_discovery(query, session)
        for c in sitemap:
            merged.setdefault(c["url"], c)
        report["sitemap"] = sm_report

    ordered = sorted(merged.values(), key=lambda x: (-x["score"], x["url"]))
    report["direct_pages"] = direct_pages
    report["raw_product_urls"] = len(ordered)
    report["candidate_urls"] = len(ordered)
    return ordered, report


def _jsonld_products(soup):
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                if isinstance(item.get("@graph"), list):
                    stack.extend(item["@graph"])
                typ = item.get("@type", [])
                typ = typ if isinstance(typ, list) else [typ]
                if "Product" in typ:
                    yield item


def _offer_price(offers):
    if isinstance(offers, dict):
        offers = [offers]
    for offer in offers or []:
        if not isinstance(offer, dict):
            continue
        av = _norm(offer.get("availability"))
        if any(x in av for x in ("outofstock", "soldout", "discontinued")):
            continue
        p = offer.get("price") or offer.get("lowPrice")
        if p is not None:
            return _price(str(p) + " €")
    return ""


def _reader_product(text: str, candidate: Dict[str, Any], query: str) -> Optional[Dict[str, Any]]:
    raw = html_lib.unescape(str(text or "")).replace("\\/", "/").replace("\\u002F", "/")
    if not raw:
        return None
    url = candidate["url"]
    soup = BeautifulSoup(raw, "html.parser")
    name = ""
    price = ""

    for p in _jsonld_products(soup):
        pn = _clean(p.get("name"))
        brand = p.get("brand")
        brand = _clean(brand.get("name")) if isinstance(brand, dict) else _clean(brand)
        if pn and _fuzzy(f"{brand} {pn}", query)[0]:
            name = pn
            price = _offer_price(p.get("offers"))
            if price:
                break

    if not name:
        h1 = soup.find("h1")
        if h1:
            h = _clean(h1.get_text(" ", strip=True))
            if _fuzzy(h, query)[0]:
                name = h

    if not name:
        title = soup.find("title")
        if title:
            t = _clean(title.get_text(" ", strip=True)).split("|")[0]
            if _fuzzy(t, query)[0]:
                name = t

    if not name:
        name = _name_from_url(url)
        if not _fuzzy(name, query)[0]:
            return None

    if _non_perfume_product(name, url):
        return None
    if not _size_valid(raw, query):
        return None

    if not price:
        for pat in (
            r'"(?:price|lowPrice)"\s*:\s*"?(\d{1,4}[.,]\d{2})',
            r"prix\s+actuel\s+(?:de\s+)?(\d{1,4}[.,]\d{2})\s*€",
        ):
            m = re.search(pat, raw, re.I)
            if m:
                price = _price(m.group(1) + " €")
                break
    if not price:
        price = _product_price(raw)
    if not price:
        price = _product_price(candidate.get("card_text", ""))

    if not price:
        return None

    low = _norm(raw)
    if any(x in low for x in ("rupture de stock", "indisponible", "outofstock", "soldout")) and not any(x in low for x in ("en stock", "ajouter au panier", "disponible")):
        return None
    return {"store": STORE, "name": name, "price": price, "url": url}


def _product_details(session, candidate, query):
    url = candidate["url"]
    try:
        r = _request(session, url)
        if any(x in r.text.lower() for x in ("just a moment", "cf-chl-", "challenge-platform")):
            raise requests.RequestException("Notino challenge")
        soup = BeautifulSoup(r.text, "html.parser")
        page_text = _clean(soup.get_text(" ", strip=True))
        if not _size_valid(page_text, query):
            return None
        name, price = "", ""
        for p in _jsonld_products(soup):
            pn = _clean(p.get("name"))
            brand = p.get("brand")
            brand = _clean(brand.get("name")) if isinstance(brand, dict) else _clean(brand)
            if pn and _fuzzy(f"{brand} {pn}", query)[0]:
                name = pn
                price = _offer_price(p.get("offers"))
                if price:
                    break
        if not name:
            h1 = soup.find("h1")
            if h1 and _fuzzy(h1.get_text(" ", strip=True), query)[0]:
                name = _clean(h1.get_text(" ", strip=True))
        if not name:
            title = soup.find("title")
            if title and _fuzzy(title.get_text(" ", strip=True).split("|")[0], query)[0]:
                name = _clean(title.get_text(" ", strip=True).split("|")[0])
        if not name:
            return _card_result(candidate, query)
        if _non_perfume_product(name, url):
            return None
        if not price:
            price = _product_price(page_text) or _product_price(candidate.get("card_text", ""))
        if not price:
            return None
        low = _norm(page_text)
        if any(x in low for x in ("rupture de stock", "indisponible")) and not any(x in low for x in ("en stock", "ajouter au panier", "disponible")):
            return None
        return {"store": STORE, "name": name, "price": price, "url": _canonical(r.url)}
    except requests.RequestException:
        try:
            rr = _reader(session, url)
            result = _reader_product(rr.text, candidate, query)
            return result or _card_result(candidate, query)
        except requests.RequestException:
            return _card_result(candidate, query)


def _card_result(candidate, query):
    url = candidate["url"]
    name = candidate.get("name") or _name_from_url(url)
    if not name or not _fuzzy(name, query)[0] or _non_perfume_product(name, url):
        return None
    if not _size_valid(f"{candidate.get('anchor_text','')} {candidate.get('card_text','')}", query):
        return None
    price = _product_price(candidate.get("anchor_text", "")) or _product_price(candidate.get("card_text", "")) or _price(candidate.get("anchor_text", ""))
    return {"store": STORE, "name": name, "price": price, "url": url} if price else None


def _rank(candidates: List[Dict[str, Any]], limit: int = 8) -> List[Dict[str, Any]]:
    # Ranking is applied only after discovery. It must never truncate discovery itself.
    ordered = sorted(candidates, key=lambda x: (-int(x.get("score") or 0), x.get("url", "")))
    return ordered[:max(1, int(limit))]


def search(query: str) -> List[Dict[str, Any]]:
    query = _clean(query)
    if not query:
        return []
    s = requests.Session()
    s.headers.update(HEADERS)
    try:
        candidates, _ = _discover(query, s)
        results, seen = [], set()
        # Use a larger page budget because discovery is cheap compared with product-page retrieval.
        for c in _rank(candidates, 8):
            result = _product_details(s, c, query)
            if not result:
                continue
            key = (result["url"] + "|" + result["name"]).lower()
            if key not in seen:
                seen.add(key)
                results.append(result)
            if len(results) >= 10:
                break
        return results
    finally:
        s.close()


def scrape(query: str) -> List[Dict[str, Any]]:
    return search(query)


def debug_search(query: str) -> Dict[str, Any]:
    query = _clean(query)
    if not query:
        return {"ok": False, "store": "notino", "query": "", "error": "empty_query"}
    s = requests.Session()
    s.headers.update(HEADERS)
    try:
        candidates, discovery = _discover(query, s)
        ranked = _rank(candidates, 8)
        products = []
        for c in ranked:
            try:
                products.append({"candidate": c, "result": _product_details(s, c, query), "error": None})
            except Exception as exc:
                products.append({"candidate": c, "result": None, "error": f"{type(exc).__name__}: {exc}"})
        return {
            "ok": any(x.get("result") for x in products),
            "store": "notino",
            "query": query,
            "scraper_version": SCRAPER_VERSION,
            "candidate_count": len(candidates),
            "ranked_candidate_count": len(ranked),
            "result_count": sum(bool(x.get("result")) for x in products),
            "candidates": candidates[:50],
            "products": products,
            "discovery": discovery,
        }
    finally:
        s.close()


def diagnose(query: str) -> Dict[str, Any]:
    query = _clean(query)
    if not query:
        return {"diagnostic": True, "scraper_version": SCRAPER_VERSION, "query": "", "error": "empty_query"}
    s = requests.Session()
    s.headers.update(HEADERS)
    try:
        candidates, discovery = _discover(query, s)
        ranked = _rank(candidates, 8)
        discovery["product_page_candidate_limit"] = 8
        discovery["candidate_urls_before_product_page_limit"] = len(candidates)
        product_pages = []
        for c in ranked:
            entry = {"url": c["url"], "candidate": c}
            try:
                r = _request(s, c["url"])
                entry.update({
                    "status": r.status_code,
                    "final_url": r.url,
                    "html_length": len(r.text or ""),
                    "cloudflare": any(x in r.text.lower() for x in ("just a moment", "cf-chl-", "challenge-platform")),
                    "requested_size": _requested_sizes(query),
                    "size_match": _size_valid(r.text, query),
                })
            except requests.RequestException as exc:
                try:
                    rr = _reader(s, c["url"])
                    parsed = _reader_product(rr.text, c, query)
                    entry.update({
                        "reader_fallback": True,
                        "reader_status": rr.status_code,
                        "reader_html_length": len(rr.text or ""),
                        "parsed_result": bool(parsed),
                        "parsed_name": parsed.get("name") if parsed else "",
                        "parsed_price": parsed.get("price") if parsed else "",
                        "parsed_url": parsed.get("url") if parsed else "",
                        "error": f"{type(exc).__name__}: {exc}",
                    })
                except requests.RequestException as rex:
                    entry.update({"reader_fallback": True, "reader_error": f"{type(rex).__name__}: {rex}"})
            product_pages.append(entry)
        return {
            "diagnostic": True, "scraper_version": SCRAPER_VERSION, "query": query,
            "discovery": discovery, "candidate_count": len(candidates),
            "ranked_candidate_count": len(ranked), "candidates": candidates[:50],
            "product_pages": product_pages,
        }
    finally:
        s.close()


if __name__ == "__main__":
    import argparse, sys
    p = argparse.ArgumentParser()
    p.add_argument("query")
    p.add_argument("--diagnose", action="store_true")
    p.add_argument("--debug-search", action="store_true")
    a = p.parse_args()
    out = diagnose(a.query) if a.diagnose else debug_search(a.query) if a.debug_search else search(a.query)
    print(json.dumps(out, ensure_ascii=False, indent=2))
