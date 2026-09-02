from __future__ import annotations

import html as html_lib
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote_plus, unquote, urlparse

import requests
from bs4 import BeautifulSoup

STORE = "Notino"
BASE_URL = "https://www.notino.fr"
SEARCH_URL = BASE_URL + "/search.asp"
READER_BASE = "https://r.jina.ai/"
SITEMAP_URL = BASE_URL + "/sitemap.xml"

TIMEOUT = 15
READER_TIMEOUT = 18
PRODUCT_RE = re.compile(r"/p-(\d+)(?:/|$)", re.I)
PRODUCT_URL_RE = re.compile(
    r"https?://(?:www\.)?notino\.fr/[^\s<>\]\[\)\"']+",
    re.I,
)
RELATIVE_PRODUCT_RE = re.compile(
    r"/(?:[a-z0-9][^\s<>\]\[\)\"']*/)+p-\d+(?:/[^\s<>\]\[\)\"']*)?",
    re.I,
)
PRICE_RE = re.compile(r"(?:€\s*(\d{1,4}[.,]\d{2})|(\d{1,4}[.,]\d{2})\s*€)", re.I)
SIZE_RE = re.compile(r"\b(\d{1,4}(?:[.,]\d{1,2})?)\s*(ml|cl|dl|l|oz|fl\s*oz|g|kg)\b", re.I)
RATING_RE = re.compile(r"\b\d[.,]\d\s*\(\s*\d+\s*\)", re.I)

SCRAPER_VERSION = "notino-2.2-2026-09-02-product-url-forms"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}
READER_HEADERS = {
    "User-Agent": "ScentHunter/2.0",
    "Accept": "text/plain,text/markdown,text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
}

GENERIC_QUERY_WORDS = {
    "pour", "femme", "femmes", "homme", "hommes", "for", "the", "and", "avec",
    "de", "du", "des", "la", "le", "les", "un", "une", "par", "eau", "edp", "edt",
    "parfum", "parfums", "perfume", "perfumes", "woman", "women", "man", "men", "unisex",
    "unisexe", "extrait", "spray", "vaporisateur", "eau-de-parfum", "eau-de-toilette",
}
NON_PERFUME_MARKERS = {
    "gift set", "set regalo", "discovery set", "fragrance set", "perfume set", "coffret",
    "bundle", "travel set", "kit", "duo", "trio", "mystery box", "tester", "testeur",
    "sample", "shampoo", "shower gel", "body wash", "body lotion", "body cream", "body milk",
    "deodorant", "deo spray", "aftershave", "after shave", "body spray", "hair mist", "makeup",
    "cosmetics", "cosmetic", "skincare", "skin care", "cosmetici",
}
IN_STOCK_MARKERS = ("en stock", "ajouter au panier", "add to cart", "disponible")
OUT_STOCK_MARKERS = ("en rupture de stock", "rupture de stock", "actuellement indisponible", "produit indisponible", "épuisé", "epuise")


def _clean(value: Any) -> str:
    text = html_lib.unescape(str(value or ""))
    text = text.replace("\\/", "/")
    text = text.replace("â‚¬", "€").replace("Â", "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _norm(value: Any) -> str:
    value = _clean(value).lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _tokens(value: Any, keep_short: bool = True) -> List[str]:
    raw = re.findall(r"[a-z0-9]+", _clean(value).lower())
    if keep_short:
        return raw
    return [x for x in raw if len(x) > 1]


def _query_identity_tokens(query: str) -> List[str]:
    tokens = []
    for token in _tokens(query):
        if token in GENERIC_QUERY_WORDS:
            continue
        if token not in tokens:
            tokens.append(token)
    return tokens


def _requested_sizes(value: Any) -> List[Tuple[str, str]]:
    return [(m.group(1).replace(",", "."), re.sub(r"\s+", "", m.group(2).lower())) for m in SIZE_RE.finditer(_clean(value))]


def _size_matches(text: Any, size: Tuple[str, str]) -> bool:
    number, unit = size
    pat = re.compile(rf"\b{re.escape(number).replace(r'\.', '[.,]')}\s*{re.escape(unit).replace('floz', r'fl\s*oz')}\b", re.I)
    return bool(pat.search(_clean(text)))


def _requested_size_ok(text: Any, query: str) -> bool:
    sizes = _requested_sizes(query)
    return not sizes or any(_size_matches(text, size) for size in sizes)


def _query_matches_name(name: str, query: str) -> bool:
    name_tokens = set(_tokens(name))
    required = _query_identity_tokens(query)
    if not required or not name_tokens:
        return False
    return all(token in name_tokens for token in required)


def _query_matches_context(name: str, context: str, query: str) -> bool:
    combined = f"{name} {context}"
    if not _query_matches_name(name, query):
        return False
    return _requested_size_ok(combined, query)


def _has_non_perfume_marker(value: Any) -> bool:
    low = _norm(value)
    return any(_norm(marker) in low for marker in NON_PERFUME_MARKERS)


def _looks_like_product_url(url: str) -> bool:
    """Recognise both Notino URL generations.

    Some product pages use /p-123456/, while others use a clean product slug
    without a numeric ID. The slug is never used as primary product identity.
    """
    value = _normalise_url(url)
    if "notino.fr" not in value.lower():
        return False
    if PRODUCT_RE.search(value):
        return True
    try:
        parts = [p for p in unquote(urlparse(value).path).split("/") if p]
    except Exception:
        return False
    if len(parts) < 2:
        return False
    slug = parts[-1].lower()
    product_markers = (
        "eau-de-parfum", "eau-de-toilette", "extrait-de-parfum",
        "parfum", "pour-femme", "pour-homme", "for-women", "for-men",
        "edp", "edt", "extrait",
    )
    return any(marker in slug for marker in product_markers)


def _normalise_url(url: str) -> str:
    url = html_lib.unescape(str(url or "")).replace("\\/", "/").strip().strip("<>[]()\"'")
    if url.startswith("//"):
        url = "https:" + url
    elif url.startswith("/"):
        url = BASE_URL + url
    return url.split("?", 1)[0].split("#", 1)[0]


def _product_id(url: str) -> Optional[str]:
    m = PRODUCT_RE.search(url or "")
    return m.group(1) if m else None


def _brand_from_url(url: str) -> str:
    try:
        parts = [p for p in unquote(urlparse(url).path).split("/") if p]
        return parts[0].replace("-", " ").strip().title() if parts else ""
    except Exception:
        return ""


def _slug_name(url: str) -> str:
    try:
        path = unquote(urlparse(url).path).strip("/")
        if not path:
            return ""
        parts = path.split("/")
        if parts and parts[-1].startswith("p-") and len(parts) > 1:
            parts = parts[:-1]
        slug = parts[-1] if parts else ""
        slug = re.sub(r"^p-\d+", "", slug, flags=re.I).strip("-")
        return re.sub(r"\s+", " ", slug.replace("-", " ")).strip().title()
    except Exception:
        return ""


def _clean_name(text: Any) -> str:
    value = _clean(text)
    value = RATING_RE.sub(" ", value)
    value = PRICE_RE.sub(" ", value)
    value = re.sub(r"\b(?:avec le code|with code)\b.*$", " ", value, flags=re.I)
    value = re.sub(r"\b(?:shoppingdays|cadeaux? offerts?|livraison offerte)\b.*$", " ", value, flags=re.I)
    value = re.sub(r"^(?:promo|nouveau|discount)\s+", "", value, flags=re.I)
    value = re.sub(r"\s+", " ", value).strip(" -|:;,.[]()")
    return value[:220]


def _extract_price(text: Any) -> str:
    matches = list(PRICE_RE.finditer(_clean(text)))
    if not matches:
        return ""
    raw = matches[-1].group(1) or matches[-1].group(2)
    try:
        return f"{float(raw.replace(',', '.')):.2f}".replace('.', ',') + "€"
    except Exception:
        return ""


def _stock(text: Any) -> Optional[bool]:
    low = _clean(text).lower()
    if any(x in low for x in OUT_STOCK_MARKERS):
        return True
    if any(x in low for x in IN_STOCK_MARKERS):
        return False
    return None


def _extract_size(text: Any) -> Optional[float]:
    m = SIZE_RE.search(_clean(text))
    if not m:
        return None
    try:
        value = float(m.group(1).replace(',', '.'))
    except Exception:
        return None
    unit = re.sub(r"\s+", "", m.group(2).lower())
    if unit == "cl":
        value *= 10
    elif unit == "dl":
        value *= 100
    elif unit == "l":
        value *= 1000
    return value if unit in {"ml", "cl", "dl", "l"} else None


def _extract_concentration(text: Any) -> str:
    low = _clean(text).lower()
    if "eau de parfum" in low or "eau-de-parfum" in low:
        return "Eau de Parfum"
    if "eau de toilette" in low or "eau-de-toilette" in low:
        return "Eau de Toilette"
    if "extrait de parfum" in low or "parfum extrait" in low:
        return "Extrait"
    if re.search(r"\bparfum\b", low):
        return "Parfum"
    return ""


def _extract_gender(text: Any) -> str:
    low = _clean(text).lower()
    if re.search(r"\b(?:pour|for)\s+(?:femme|femmes|woman|women)\b", low):
        return "female"
    if re.search(r"\b(?:pour|for)\s+(?:homme|hommes|man|men)\b", low):
        return "male"
    if "unisex" in low or "unisexe" in low:
        return "unisex"
    return ""


def _display_name(name: str, url: str = "") -> str:
    name = _clean_name(name)
    if not name:
        return _clean_name(_slug_name(url))
    return name


def _new_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def _request(session: requests.Session, url: str, reader: bool = False) -> requests.Response:
    headers = READER_HEADERS if reader else None
    timeout = READER_TIMEOUT if reader else TIMEOUT
    r = session.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    return r


def _search_urls(query: str) -> List[str]:
    q = quote_plus(query)
    return [f"{SEARCH_URL}?exps={q}", f"{BASE_URL}/search?query={q}"]


def _reader_search(session: requests.Session, url: str) -> Optional[str]:
    try:
        return _request(session, READER_BASE + url, reader=True).text or ""
    except requests.RequestException:
        return None


def _extract_name_from_line(line: str, query: str) -> str:
    raw = _clean(line)
    if not raw:
        return ""

    # Image alt text is usually the cleanest visible product title in Jina Markdown.
    alts = re.findall(r"!\[\s*(?:Image\s*\d+\s*:\s*)?([^\]]+)\]", raw, flags=re.I)
    candidates = [_clean_name(re.sub(r"^Image(?:\s*\d+)?\s*:\s*", "", x, flags=re.I)) for x in alts]

    # Plain Markdown links can contain the visible title as [TITLE](URL).
    for m in re.finditer(r"\[([^\]]{3,220})\]\((https?://[^)]+|/[^)]+)\)", raw, flags=re.I):
        candidates.append(_clean_name(m.group(1)))

    stripped = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", raw)
    stripped = re.sub(r"\[[^\]]*\]\([^)]*\)", " ", stripped)
    stripped = re.sub(r"https?://[^\s]+", " ", stripped, flags=re.I)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    if stripped:
        candidates.append(_clean_name(stripped))

    good = []
    for candidate in candidates:
        if not candidate or len(candidate) > 220:
            continue
        if _has_non_perfume_marker(candidate):
            continue
        if _query_matches_name(candidate, query):
            good.append(candidate)

    if not good:
        return ""
    # Prefer the shortest clean matching title; long Reader lines contain neighbouring products.
    return min(good, key=len)


def _focused_context(text: str, start: int, end: int) -> str:
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    if line_end < 0:
        line_end = len(text)
    line = text[line_start:line_end]
    if len(line) > 1800:
        left = max(0, start - line_start - 700)
        line = line[left:left + 1400]
    return _clean(line)


def _candidate_from_evidence(url: str, name: str, card: str, query: str, source: str) -> Optional[Dict[str, Any]]:
    url = _normalise_url(url)
    if not _looks_like_product_url(url):
        return None
    name = _clean_name(name)
    card = _clean(card)
    if not name or not _query_matches_name(name, query):
        return None
    if _has_non_perfume_marker(name) or _has_non_perfume_marker(url):
        return None
    if not _requested_size_ok(f"{name} {card}", query):
        return None
    return {
        "url": url,
        "name": name,
        "anchor_text": name,
        "card_text": card or name,
        "source": source,
        "product_id": _product_id(url),
        "price": _extract_price(card),
        "stock": _stock(card),
        "size_ml": _extract_size(f"{name} {card}"),
        "score": 100 + (20 if _extract_price(card) else 0) + (10 if _stock(card) is not None else 0),
    }


def _reader_query_variants(query: str) -> List[str]:
    """Small, bounded set of Notino discovery formulations."""
    query = _clean(query)
    if not query:
        return []
    identity = " ".join(_query_identity_tokens(query))
    variants: List[str] = []
    for value in (query, identity, " ".join(reversed(_query_identity_tokens(query)))):
        value = _clean(value)
        if value and value.casefold() not in {v.casefold() for v in variants}:
            variants.append(value)
    return variants[:3]


def _context_names(raw: str, url_start: int, url_end: int, query: str) -> List[str]:
    """Find clean product titles in the small Reader block around one URL."""
    lines = raw.splitlines()
    # Map character position to line index without scanning the whole document repeatedly.
    pos = 0
    line_index = 0
    for i, line in enumerate(lines):
        next_pos = pos + len(line) + 1
        if pos <= url_start < next_pos:
            line_index = i
            break
        pos = next_pos

    candidates: List[str] = []
    # Reader Markdown cards are normally compact; keep the window deliberately tight.
    for i in range(max(0, line_index - 7), min(len(lines), line_index + 4)):
        line = lines[i].strip()
        if not line:
            continue
        cleaned = _extract_name_from_line(line, query)
        if cleaned:
            candidates.append(cleaned)
        # Also test the whole line after removing the candidate URL. This catches
        # Notino cards where title and URL are rendered on different Markdown lines.
        line_without_url = PRODUCT_URL_RE.sub(" ", line)
        line_without_url = re.sub(r"https?://[^\s]+", " ", line_without_url, flags=re.I)
        cleaned = _extract_name_from_line(line_without_url, query)
        if cleaned:
            candidates.append(cleaned)

    # Last resort: inspect a bounded character window and split on Markdown/card boundaries.
    window = raw[max(0, url_start - 700):min(len(raw), url_end + 350)]
    window = PRODUCT_URL_RE.sub(" ", window)
    for fragment in re.split(r"\n+|\]\s*\[|\|", window):
        cleaned = _clean_name(fragment)
        if not cleaned or len(cleaned) > 180:
            continue
        if _has_non_perfume_marker(cleaned):
            continue
        if _query_matches_name(cleaned, query):
            candidates.append(cleaned)

    # Shortest matching title is generally the clean product title, while longer
    # strings tend to contain promo/price/neighbouring-card material.
    unique = list(dict.fromkeys(candidates))
    unique.sort(key=lambda x: (len(x), x.casefold()))
    return unique


def _reader_candidates(text: str, query: str) -> List[Dict[str, Any]]:
    found: Dict[str, Dict[str, Any]] = {}
    raw = html_lib.unescape(text or "").replace("\\/", "/")

    for match in PRODUCT_URL_RE.finditer(raw):
        url = _normalise_url(match.group(0))
        if not _looks_like_product_url(url):
            continue

        names = _context_names(raw, match.start(), match.end(), query)
        if not names:
            continue

        # Prefer a visible title over the URL slug. This is critical on Notino:
        # legacy product URLs can contain a misleading AM/PM slug while the
        # visible product title is the authoritative identity.
        for name in names:
            candidate = _candidate_from_evidence(
                url, name,
                raw[max(0, match.start() - 500):min(len(raw), match.end() + 250)],
                query,
                "reader-context",
            )
            if not candidate:
                continue
            old = found.get(url)
            if old is None or candidate["score"] > old["score"] or len(candidate["name"]) < len(old["name"]):
                found[url] = candidate
            # Once we have a clean title for this URL, do not let a later
            # neighbouring fragment replace it with a noisier title.
            break

    return list(found.values())

def _html_candidates(html: str, query: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html or "", "html.parser")
    found: Dict[str, Dict[str, Any]] = {}
    for a in soup.find_all("a", href=True):
        url = _normalise_url(a.get("href", ""))
        if not _looks_like_product_url(url):
            continue
        anchor = _clean_name(a.get_text(" ", strip=True))
        card_node = a
        best = anchor
        for _ in range(8):
            card_node = getattr(card_node, "parent", None)
            if card_node is None:
                break
            text = _clean(card_node.get_text(" ", strip=True))
            if len(text) > len(best) and len(text) < 1500:
                best = text
            if _extract_price(text):
                break
        name = anchor if _query_matches_name(anchor, query) else ""
        if not name:
            # Search headings/strong text inside the card, but only accept an exact identity-token match.
            for node in card_node.find_all(["h2", "h3", "h4", "strong", "span"], limit=30) if card_node else []:
                n = _clean_name(node.get_text(" ", strip=True))
                if _query_matches_name(n, query):
                    name = n
                    break
        if not name:
            continue
        candidate = _candidate_from_evidence(url, name, best, query, "direct-html")
        if candidate:
            old = found.get(url)
            if old is None or candidate["score"] > old["score"]:
                found[url] = candidate
    return list(found.values())


def _discover(query: str, session: requests.Session) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    candidates: Dict[str, Dict[str, Any]] = {}
    diagnostics: Dict[str, Any] = {
        "strategy": "direct-search -> Jina search -> sitemap-only-if-empty",
        "direct": [],
        "reader": [],
        "sitemap_used": False,
    }

    # 1) Direct Notino search. Usually 403 in production, but keep it as the cheapest source when available.
    for url in _search_urls(query):
        try:
            r = _request(session, url)
            found = _html_candidates(r.text, query)
            diagnostics["direct"].append({"url": url, "status": r.status_code, "candidates": len(found)})
            for c in found:
                candidates[c["url"]] = c
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            diagnostics["direct"].append({"url": url, "status": status, "error": type(exc).__name__})

    # 2) Jina Reader. Use a small bounded set of query formulations, sequentially,
    # so discovery can recover when Notino's search engine ranks the exact phrase poorly.
    diagnostics["reader_queries"] = _reader_query_variants(query)
    for discovery_query in _reader_query_variants(query):
        for url in _search_urls(discovery_query):
            text = _reader_search(session, url)
            if text is None:
                diagnostics["reader"].append({"url": url, "query": discovery_query, "status": None, "candidates": 0})
                continue
            found = _reader_candidates(text, query)
            diagnostics["reader"].append({"url": url, "query": discovery_query, "status": 200, "candidates": len(found), "text_length": len(text)})
            for c in found:
                old = candidates.get(c["url"])
                if old is None or c["score"] > old["score"] or len(c["name"]) < len(old["name"]):
                    candidates[c["url"]] = c

    # 3) Sitemap is an emergency discovery source only. It never overrides a visible search-card name.
    if not candidates:
        diagnostics["sitemap_used"] = True
        try:
            r = _request(session, SITEMAP_URL)
            soup = BeautifulSoup(r.text, "xml")
            for loc in soup.find_all("loc"):
                url = _normalise_url(loc.get_text(" ", strip=True))
                if not _looks_like_product_url(url):
                    continue
                slug = _slug_name(url)
                if not _query_matches_name(slug, query):
                    continue
                c = _candidate_from_evidence(url, slug, "", query, "sitemap")
                if c:
                    candidates[url] = c
        except requests.RequestException:
            pass

    return list(candidates.values()), diagnostics


def _reader_product(session: requests.Session, candidate: Dict[str, Any], query: str) -> Optional[Dict[str, Any]]:
    try:
        text = _request(session, READER_BASE + candidate["url"], reader=True).text or ""
    except requests.RequestException:
        return None
    if not text or not _requested_size_ok(text, query):
        return None

    # Product page identity: visible title first; URL slug is only fallback.
    lines = [_clean(re.sub(r"^#{1,6}\s*", "", x)) for x in text.splitlines() if _clean(x)]
    name = ""
    for line in lines[:180]:
        if len(line) > 220 or PRICE_RE.search(line):
            continue
        if _query_matches_name(line, query) and not _has_non_perfume_marker(line):
            name = _clean_name(line)
            break
    if not name:
        name = _clean_name(candidate.get("name") or "")
    if not name or not _query_matches_name(name, query):
        return None
    if _has_non_perfume_marker(name):
        return None

    price = _extract_price(text) or candidate.get("price", "")
    stock = _stock(text)
    size = _extract_size(text) or candidate.get("size_ml")
    concentration = _extract_concentration(text)
    gender = _extract_gender(text)
    if not price:
        return None
    return _result(name, price, stock, candidate["url"], size, concentration, gender)


def _card_result(candidate: Dict[str, Any], query: str) -> Optional[Dict[str, Any]]:
    name = _clean_name(candidate.get("name") or "")
    card = _clean(candidate.get("card_text") or "")
    if not name or not _query_matches_name(name, query):
        return None
    if not _requested_size_ok(f"{name} {card}", query):
        return None
    price = candidate.get("price") or _extract_price(card)
    if not price:
        return None
    return _result(
        name,
        price,
        candidate.get("stock"),
        candidate["url"],
        candidate.get("size_ml") or _extract_size(f"{name} {card}"),
        _extract_concentration(f"{name} {card}"),
        _extract_gender(f"{name} {card}"),
    )


def _result(name: str, price: str, stock: Optional[bool], url: str, size: Optional[float], concentration: str, gender: str) -> Dict[str, Any]:
    return {
        "store": STORE,
        "name": _display_name(name, url),
        "price": price,
        "availability": "out of stock" if stock is True else "in stock" if stock is False else "unknown",
        "available": False if stock is True else True if stock is False else None,
        "url": url,
        "size_ml": size,
        "concentration": concentration,
        "gender": gender,
    }


def _enrich_one(candidate: Dict[str, Any], query: str) -> Optional[Dict[str, Any]]:
    # A validated search card is already a real Notino offer. Do not make a second
    # network request merely to enrich it: product-page Reader calls were the main
    # source of avoidable 429s/latency in the old scraper. If the card has no price,
    # only then spend one request on the product page.
    card = _card_result(candidate, query)
    if card:
        return card

    session = _new_session()
    try:
        return _reader_product(session, candidate, query)
    finally:
        session.close()


def _dedupe_results(results: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_id: Dict[str, Dict[str, Any]] = {}
    for item in results:
        url = item.get("url", "")
        pid = _product_id(url)
        key = f"id:{pid}" if pid else f"url:{url.lower()}"
        old = by_id.get(key)
        if old is None:
            by_id[key] = item
            continue
        # Same Notino product ID is one offer; keep the richer result.
        richness = sum(bool(item.get(k)) for k in ("size_ml", "concentration", "gender"))
        old_richness = sum(bool(old.get(k)) for k in ("size_ml", "concentration", "gender"))
        if richness > old_richness:
            by_id[key] = item
    return list(by_id.values())


def search(query: str) -> List[Dict[str, Any]]:
    query = _clean(query)
    if not query:
        return []
    session = _new_session()
    try:
        candidates, _ = _discover(query, session)
    finally:
        session.close()

    # Keep product-page fan-out deliberately small. Notino is the only store that can already have
    # multiple fallback requests behind one candidate; 3 workers avoid the old 8x8 burst pattern.
    candidates.sort(key=lambda x: (-int(x.get("score", 0)), x.get("url", "")))
    candidates = candidates[:16]
    results: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(3, len(candidates) or 1)) as executor:
        futures = [executor.submit(_enrich_one, c, query) for c in candidates]
        for future in as_completed(futures):
            try:
                item = future.result()
            except Exception:
                item = None
            if item:
                results.append(item)
    return _dedupe_results(results)[:16]


def scrape(query: str) -> List[Dict[str, Any]]:
    return search(query)


def diagnose(query: str) -> Dict[str, Any]:
    query = _clean(query)
    if not query:
        return {"diagnostic": True, "scraper_version": SCRAPER_VERSION, "query": "", "error": "empty_query"}
    session = _new_session()
    try:
        candidates, discovery = _discover(query, session)
    finally:
        session.close()
    return {
        "diagnostic": True,
        "scraper_version": SCRAPER_VERSION,
        "query": query,
        "identity_tokens": _query_identity_tokens(query),
        "candidate_count": len(candidates),
        "candidates": candidates[:30],
        "discovery": discovery,
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--diagnose", action="store_true")
    args = parser.parse_args()
    data = diagnose(args.query) if args.diagnose else search(args.query)
    print(json.dumps(data, ensure_ascii=False, indent=2))
