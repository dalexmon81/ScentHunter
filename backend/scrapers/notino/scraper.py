from __future__ import annotations

import html as html_lib
import json
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote_plus, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

STORE = "Notino"
BASE_URL = "https://www.notino.fr"
SEARCH_URL = BASE_URL + "/search.asp"
READER_BASE = "https://r.jina.ai/"
SITEMAP_URL = BASE_URL + "/sitemap.xml"

TIMEOUT = 18
READER_TIMEOUT = 30
RETRY_COUNT = 2
MAX_CANDIDATES = 48
ENRICH_WORKERS = 6
SCRAPER_VERSION = "notino-3.7-2026-09-05-variant-page-authoritative"

PRODUCT_RE = re.compile(r"/p-(\d+)(?:/|$)", re.I)
PRODUCT_URL_RE = re.compile(
    r"https?://(?:www\.)?notino\.(?:fr|be|de|com|it|gr|es|pt|ie|co\.uk)/[^\s)\]>\"']+",
    re.I,
)
RELATIVE_PRODUCT_RE = re.compile(
    r"/(?:[a-z0-9][^\s<>\]\[\)\"']*/)+p-\d+(?:/[^\s<>\]\[\)\"']*)?",
    re.I,
)
PRICE_RE = re.compile(
    r"(?:€\s*(\d{1,4}(?:[.,]\d{1,2})?)|(\d{1,4}(?:[.,]\d{1,2})?)\s*€|(?:EUR|\bprice\b\s*[:=])\s*(\d{1,4}(?:[.,]\d{1,2})?))",
    re.I,
)
SIZE_RE = re.compile(
    r"\b(\d{1,4}(?:[.,]\d{1,2})?)\s*(ml|cl|dl|l|oz|fl\.?\s*oz)\b",
    re.I,
)
RATING_RE = re.compile(r"\b\d[.,]\d\s*\(\s*\d+\s*\)", re.I)

GENERIC_QUERY_WORDS = {
    "pour", "femme", "femmes", "homme", "hommes", "for", "the", "and", "avec",
    "de", "du", "des", "la", "le", "les", "un", "une", "par", "eau", "edp", "edt",
    "parfum", "parfums", "perfume", "perfumes", "woman", "women", "man", "men", "unisex",
    "unisexe", "extrait", "spray", "vaporisateur", "eau-de-parfum", "eau-de-toilette",
    "eau-de-cologne", "eau", "de", "oz", "ml", "cl", "dl", "l",
}
NON_PERFUME_MARKERS = {
    "gift set", "set regalo", "discovery set", "fragrance set", "perfume set", "parfum set",
    "coffret", "bundle", "travel set", "kit", "duo", "trio", "mystery box", "gift box",
    "tester", "testeur", "sample", "samples", "shampoo", "shower gel", "body wash", "body lotion",
    "body cream", "body milk", "deodorant", "deo spray", "aftershave", "after shave", "body spray",
    "hair mist", "makeup", "cosmetics", "cosmetic", "skincare", "skin care", "cosmetici",
    "creme corpo", "crema corpo", "gel doccia", "bagnoschiuma", "deodorante", "cofanetto", "estuche",
    "etui", "pochette", "miniature", "mini spray", "minispray",
}
IN_STOCK_MARKERS = (
    "en stock", "ajouter au panier", "add to cart", "in stock", "disponible", "available",
    "σε απόθεμα", "disponibile subito", "stock disponible", "order now",
)
OUT_STOCK_MARKERS = (
    "en rupture de stock", "rupture de stock", "actuellement indisponible", "produit indisponible",
    "épuisé", "epuise", "currently unavailable", "out of stock", "non disponibile",
    "momentanément non disponible", "προσωρινά μη διαθέσιμο", "sold out", "unavailable",
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}
READER_HEADERS = {
    "User-Agent": "ScentHunter/3.2",
    "Accept": "text/plain,text/markdown,text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}


def _clean(value: Any) -> str:
    text = html_lib.unescape(str(value or ""))
    text = text.replace("\\/", "/")
    text = text.replace("â‚¬", "€").replace("Â", "")
    return re.sub(r"\s+", " ", text).strip()


def unicase_normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in value if not unicodedata.combining(ch))


def _norm(value: Any) -> str:
    value = unicase_normalize(_clean(value).casefold())
    value = re.sub(r"(?<=\d)(?=[a-z])", " ", value)
    value = re.sub(r"(?<=[a-z])(?=\d)", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _tokens(value: Any) -> List[str]:
    return _norm(value).split()


def _query_identity_tokens(query: str) -> List[str]:
    output: List[str] = []
    for token in _tokens(query):
        if token in GENERIC_QUERY_WORDS:
            continue
        if token not in output:
            output.append(token)
    return output


def _requested_sizes(value: Any) -> List[Tuple[float, str]]:
    sizes: List[Tuple[float, str]] = []
    for match in SIZE_RE.finditer(_clean(value)):
        try:
            number = float(match.group(1).replace(",", "."))
        except (TypeError, ValueError):
            continue
        unit = re.sub(r"\s+", "", match.group(2).lower())
        sizes.append((number, unit))
    return sizes


def _size_to_ml(value: float, unit: str) -> float:
    if unit == "cl":
        return value * 10
    if unit == "dl":
        return value * 100
    if unit == "l":
        return value * 1000
    if unit in {"oz", "floz"}:
        return value * 29.5735
    return value


def _extract_size(text: Any) -> Optional[float]:
    match = SIZE_RE.search(_clean(text))
    if not match:
        return None
    try:
        number = float(match.group(1).replace(",", "."))
    except (TypeError, ValueError):
        return None
    unit = re.sub(r"\s+", "", match.group(2).lower())
    return _size_to_ml(number, unit)


def _requested_size_conflicts(text: Any, query: str) -> bool:
    requested = _requested_sizes(query)
    if not requested:
        return False
    discovered = _extract_size(text)
    if discovered is None:
        # Unknown size is inconclusive. Do NOT discard the candidate.
        return False
    for number, unit in requested:
        requested_ml = _size_to_ml(number, unit)
        if abs(discovered - requested_ml) <= 0.01:
            return False
    return True


def _gender_marker(value: Any) -> str:
    low = _norm(value)
    female = bool(re.search(r"\b(?:pour femmes?|for (?:her|women)|women|woman|femme|donna|donne)\b", low))
    male = bool(re.search(r"\b(?:pour hommes?|for (?:him|men)|men|man|homme|uomo)\b", low))
    if female and not male:
        return "female"
    if male and not female:
        return "male"
    if re.search(r"\b(?:unisex|unisexe|mixte)\b", low):
        return "unisex"
    return ""


def _gender_compatible(name: str, query: str) -> bool:
    q_gender = _gender_marker(query)
    if not q_gender:
        return True
    n_gender = _gender_marker(name)
    return not n_gender or n_gender == q_gender


def _query_matches_name(name: str, query: str) -> bool:
    name_norm = _norm(name)
    query_norm = _norm(query)
    required = [
        token for token in _query_identity_tokens(query)
        if not re.fullmatch(r"\d+(?:[.,]\d+)?", token) or any(
            number > 10 for number, _unit in _requested_sizes(query)
        ) is False
    ]
    # Numeric perfume-format values (50/75/100/150...) are attributes, not identity.
    requested_sizes = _requested_sizes(query)
    if requested_sizes:
        size_numbers = {str(int(number)) if float(number).is_integer() else str(number) for number, _ in requested_sizes}
        required = [token for token in required if token not in size_numbers]
    if not required or not name_norm:
        return False

    name_tokens = set(name_norm.split())
    if not all(token in name_tokens for token in required):
        return False
    if not _gender_compatible(name, query):
        return False

    # Sequence is a ranking signal, not a hard requirement. Notino frequently
    # changes punctuation, ordering of commercial descriptors, and placement
    # of gender/concentration terms.
    q_identity = " ".join(required)
    n_identity = " ".join(token for token in name_norm.split() if token not in GENERIC_QUERY_WORDS)
    if q_identity and q_identity in n_identity:
        return True
    return True


def _has_non_perfume_marker(value: Any) -> bool:
    low = _norm(value)
    padded = f" {low} "
    return any(f" {_norm(marker)} " in padded for marker in NON_PERFUME_MARKERS)


def normaliseurl(url: str) -> str:
    value = html_lib.unescape(str(url or "")).strip()
    if not value:
        return ""
    value = value.replace("\\/", "/")

    # Jina can occasionally expose an absolute Notino URL with the hostname
    # duplicated inside the path. Never let that leak into the candidate URL.
    value = re.sub(
        r"^(https?://(?:www\.)?notino\.[a-z.]+)/(?:www\.)?notino\.[a-z.]+/",
        r"\1/",
        value,
        flags=re.I,
    )
    if value.startswith("//"):
        value = "https:" + value
    elif re.match(r"^www\.notino\.[a-z.]+/", value, flags=re.I):
        value = "https://" + value
    elif re.match(r"^notino\.[a-z.]+/", value, flags=re.I):
        value = "https://www." + value

    normalized = urljoin(BASE_URL + "/", value)
    parsed = urlparse(normalized)
    host = parsed.netloc.lower().split(":", 1)[0]
    if host in {"www.notino.fr", "notino.fr"}:
        path = re.sub(r"^/(?:www\.)?notino\.fr(?=/|$)", "", parsed.path, flags=re.I)
        if not path.startswith("/"):
            path = "/" + path
        normalized = parsed._replace(netloc="www.notino.fr", path=path).geturl()
    return normalized


_normalise_url = normaliseurl


def lookslikeproducturl(url: str) -> bool:
    value = normaliseurl(url)
    if not value:
        return False
    parsed = urlparse(value)
    host = parsed.netloc.lower().split(":", 1)[0]
    allowed_hosts = {
        "www.notino.fr", "notino.fr", "www.notino.be", "notino.be", "www.notino.de", "notino.de",
        "www.notino.com", "notino.com", "www.notino.it", "notino.it", "www.notino.gr", "notino.gr",
        "www.notino.es", "notino.es", "www.notino.pt", "notino.pt", "www.notino.ie", "notino.ie",
        "www.notino.co.uk", "notino.co.uk",
    }
    return host in allowed_hosts and bool(PRODUCT_RE.search(parsed.path or ""))


_looks_like_product_url = lookslikeproducturl


def _product_id(url: str) -> Optional[str]:
    match = PRODUCT_RE.search(url or "")
    return match.group(1) if match else None


def _slug_name(url: str) -> str:
    try:
        path = unquote(urlparse(normaliseurl(url)).path).strip("/")
        parts = [part for part in path.split("/") if part]
        slug = parts[-1] if parts else ""
        slug = re.sub(r"^p-\d+", "", slug, flags=re.I).strip("-")
        return re.sub(r"\s+", " ", slug.replace("-", " ")).strip().title()
    except Exception:
        return ""


def _clean_name(text: Any) -> str:
    value = _clean(text)
    # Normalize alpha/numeric boundaries before token validation.
    value = unicase_normalize(value)
    value = re.sub(r"(?<=\d)(?=[A-Za-z])|(?<=[A-Za-z])(?=\d)", " ", value)
    value = RATING_RE.sub(" ", value)
    value = re.sub(r"\b(?:avec le code|with code)\b.*$", " ", value, flags=re.I)
    value = re.sub(r"\b(?:shoppingdays|cadeaux? offerts?|livraison offerte)\b.*$", " ", value, flags=re.I)
    value = re.sub(
        r"\b(?:en stock|in stock|ajouter au panier|add to cart|disponible|available|"
        r"momentanément indisponible|actuellement indisponible|out of stock|sold out)\b.*$",
        " ", value, flags=re.I,
    )
    # Remove commercial attributes without deleting an adjacent numeric token
    # from the product identity (e.g. Afnan9 -> Afnan 9).
    value = re.sub(
        r"\b(?:eau[- ]de[- ]parfum|eau[- ]de[- ]toilette|eau[- ]de[- ]cologne|"
        r"extrait(?:[- ]de[- ]parfum)?|parfum intense)\b",
        " ", value, flags=re.I,
    )
    value = re.sub(
        r"\b\d{1,4}(?:[.,]\d{1,2})?\s*(?:ml|cl|dl|l|oz|fl\s*oz)\b.*$",
        " ", value, flags=re.I,
    )
    value = re.sub(r"\s+", " ", value).strip(" -|:;,.[]()")
    return value[:240]


def _display_name(name: str, url: str = "") -> str:
    cleaned = _clean_name(name)
    return cleaned or _clean_name(_slug_name(url))


def displayname(name: str, url: str = "") -> str:
    return _display_name(name, url)


def _extract_concentration(text: Any) -> str:
    low = _norm(text)
    if "extrait de parfum" in low or "parfum extrait" in low:
        return "Extrait"
    if "parfum intense" in low:
        return "Parfum Intense"
    if "eau de parfum" in low or re.search(r"\bedp\b", low):
        return "Eau de Parfum"
    if "eau de toilette" in low or re.search(r"\bedt\b", low):
        return "Eau de Toilette"
    if "eau de cologne" in low or re.search(r"\bedc\b", low):
        return "Eau de Cologne"
    if re.search(r"\bparfum\b", low):
        return "Parfum"
    return ""


def _extract_price(text: Any) -> str:
    cleaned = _clean(text)
    matches = list(PRICE_RE.finditer(cleaned))
    if matches:
        match = matches[-1]
        raw = match.group(1) or match.group(2) or match.group(3)
        if raw:
            try:
                value = float(raw.replace(",", "."))
                return f"{value:.2f}".replace(".", ",") + "€"
            except (TypeError, ValueError):
                pass

    # Structured JSON is often flattened by readers without a euro symbol.
    # Accept a numeric price only when a nearby EUR marker exists.
    patterns = (
        r'"price"\s*:\s*"?(\d{1,4}(?:[.,]\d{1,2})?)"?[^}]{0,120}"priceCurrency"\s*:\s*"EUR"',
        r'"priceCurrency"\s*:\s*"EUR"[^}]{0,120}"price"\s*:\s*"?(\d{1,4}(?:[.,]\d{1,2})?)"?',
        r'(?i)\b(?:EUR|€)\s*[:=]?\s*(\d{1,4}(?:[.,]\d{1,2})?)\b',
    )
    for pattern in patterns:
        match = re.search(pattern, cleaned, re.I)
        if not match:
            continue
        try:
            value = float(match.group(1).replace(",", "."))
            return f"{value:.2f}".replace(".", ",") + "€"
        except (TypeError, ValueError):
            continue
    return ""


def _stock(text: Any) -> Optional[bool]:
    low = _clean(text).casefold()
    if any(marker in low for marker in OUT_STOCK_MARKERS):
        return True
    if any(marker in low for marker in IN_STOCK_MARKERS):
        return False
    return None


def _new_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    return session


def _request(session: requests.Session, url: str, reader: bool = False) -> requests.Response:
    headers = READER_HEADERS if reader else None
    timeout = READER_TIMEOUT if reader else TIMEOUT
    last_error: Optional[Exception] = None
    for attempt in range(RETRY_COUNT + 1):
        try:
            response = session.get(url, headers=headers, timeout=timeout, allow_redirects=True)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            if attempt < RETRY_COUNT:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise
    raise last_error or RuntimeError("request failed")


def _search_urls(query: str) -> List[str]:
    q = quote_plus(query)
    return [
        f"{SEARCH_URL}?exps={q}",
        f"{BASE_URL}/search?query={q}",
    ]


def _reader_search(session: requests.Session, url: str) -> Tuple[Optional[str], Optional[str]]:
    try:
        response = _request(session, READER_BASE + url, reader=True)
        return response.text or "", None
    except requests.RequestException as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _json_walk_products(payload: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(payload, dict):
        typ = payload.get("@type") or payload.get("type")
        if typ == "Product" or (isinstance(typ, list) and "Product" in typ):
            yield payload
        for value in payload.values():
            if isinstance(value, (dict, list)):
                yield from _json_walk_products(value)
    elif isinstance(payload, list):
        for value in payload:
            yield from _json_walk_products(value)


def _structured_product_records(text: str) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    soup = BeautifulSoup(text or "", "html.parser")
    scripts = soup.find_all("script", type=re.compile(r"ld\+json", re.I))
    for script in scripts:
        raw = script.string or script.get_text("", strip=True)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        for product in _json_walk_products(payload):
            records.append(product)
    return records


def _structured_record_to_evidence(record: Dict[str, Any]) -> Tuple[str, str, str, Optional[str], Optional[float]]:
    name = _clean(record.get("name") or record.get("title") or "")
    brand = record.get("brand")
    if isinstance(brand, dict):
        brand = brand.get("name")
    brand = _clean(brand or "")
    url = normaliseurl(record.get("url") or "")
    offers = record.get("offers")
    price = ""
    currency = ""
    stock = None
    if isinstance(offers, dict):
        price = _clean(offers.get("price") or offers.get("lowPrice") or "")
        currency = _clean(offers.get("priceCurrency") or "")
        stock = _stock(_clean(offers.get("availability") or ""))
    elif isinstance(offers, list):
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            price = _clean(offer.get("price") or offer.get("lowPrice") or "")
            currency = _clean(offer.get("priceCurrency") or "")
            stock = _stock(_clean(offer.get("availability") or ""))
            if price:
                break
    size = _extract_size(name)
    if not price:
        price = _extract_price(name)
    elif currency.casefold() not in {"eur", "€"}:
        # Preserve only likely euro records; Notino.fr uses EUR.
        price = ""
    if price:
        try:
            numeric = float(str(price).replace(",", "."))
            price = f"{numeric:.2f}".replace(".", ",") + "€"
        except (TypeError, ValueError):
            price = ""
    return name, brand, url, price or None, size


def _query_score(name: str, query: str, url: str = "", size_ml: Optional[float] = None) -> int:
    name_norm = _norm(name)
    query_norm = _norm(query)
    required = _query_identity_tokens(query)
    name_tokens = set(name_norm.split())
    score = 0
    score += 50 * sum(1 for token in required if token in name_tokens)
    if query_norm and query_norm in name_norm:
        score += 120
    identity_phrase = " ".join(required)
    if identity_phrase and identity_phrase in name_norm:
        score += 70
    if _gender_compatible(name, query):
        score += 20
    else:
        score -= 1000
    requested = _requested_sizes(query)
    if requested and size_ml is not None:
        if any(abs(size_ml - _size_to_ml(number, unit)) <= 0.01 for number, unit in requested):
            score += 40
        else:
            score -= 60
    if url and query_norm:
        slug = _norm(_slug_name(url))
        if identity_phrase and identity_phrase in slug:
            score += 45
    return score


def _candidate_from_evidence(
    url: str,
    name: str,
    card: str,
    query: str,
    source: str,
    *,
    brand: str = "",
    structured_price: str = "",
    structured_size: Optional[float] = None,
    structured_stock: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    url = normaliseurl(url)
    name = _clean_name(name)
    card = _clean(card)
    if not lookslikeproducturl(url):
        return None
    if not name:
        return None
    if not _query_matches_name(name, query):
        return None
    if _has_non_perfume_marker(name) or _has_non_perfume_marker(url):
        return None

    combined = " ".join(filter(None, [name, card]))
    size = structured_size or _extract_size(combined)
    # Only reject when an explicit discovered size conflicts with the request.
    # Missing size is unknown, not a mismatch.
    if size is not None and _requested_size_conflicts(combined, query):
        return None

    price = structured_price or _extract_price(card) or _extract_price(combined)
    stock = structured_stock if structured_stock is not None else _stock(card)
    score = _query_score(name, query, url, size)
    score += 30 if price else 0
    score += 12 if stock is not None else 0
    return {
        "url": url,
        "name": name,
        "anchor_text": name,
        "card_text": card or name,
        "source": source,
        "brand": brand,
        "product_id": _product_id(url),
        "price": price,
        "stock": stock,
        "size_ml": size,
        "score": score,
    }


def _name_candidates_from_node(node: Any, query: str) -> List[str]:
    candidates: List[str] = []
    text = _clean(node.get_text(" ", strip=True)) if node is not None else ""
    if text:
        cleaned = _clean_name(text)
        if cleaned and _query_matches_name(cleaned, query):
            candidates.append(cleaned)
    if node is not None:
        for img in node.find_all("img", limit=8):
            alt = _clean_name(img.get("alt") or "")
            if alt and _query_matches_name(alt, query):
                candidates.append(alt)
    return candidates


def _focused_card_from_html_anchor(anchor: Any) -> str:
    texts: List[str] = []
    node = anchor
    for _ in range(9):
        if node is None:
            break
        text = _clean(getattr(node, "get_text", lambda *args, **kwargs: "")(" ", strip=True))
        if text:
            texts.append(text)
        if _extract_price(text) or _stock(text) is not None:
            break
        node = getattr(node, "parent", None)
    return max(texts, key=len) if texts else ""


def _html_candidates(html: str, query: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html or "", "html.parser")
    found: Dict[str, Dict[str, Any]] = {}

    # 1) Visible/anchored product cards.
    for anchor in soup.find_all("a", href=True):
        url = normaliseurl(str(anchor.get("href") or "").strip())
        if not lookslikeproducturl(url):
            continue
        card = _focused_card_from_html_anchor(anchor)
        names = _name_candidates_from_node(anchor, query)
        if not names:
            parent = anchor
            for _ in range(7):
                parent = getattr(parent, "parent", None)
                if parent is None:
                    break
                for candidate_name in _name_candidates_from_node(parent, query):
                    names.append(candidate_name)
                if names:
                    break
        if not names:
            names = [_clean_name(_slug_name(url))]
        for name in names:
            candidate = _candidate_from_evidence(url, name, card, query, "direct-html")
            if candidate:
                old = found.get(url)
                if old is None or candidate["score"] > old["score"]:
                    found[url] = candidate

    # 2) JSON-LD product objects. This catches pages where the visible anchor
    # text is incomplete or title/price live only in structured data.
    for record in _structured_product_records(html):
        name, brand, url, price, size = _structured_record_to_evidence(record)
        if not url:
            continue
        candidate = _candidate_from_evidence(
            url, name or _slug_name(url), name, query, "direct-jsonld",
            brand=brand, structured_price=price or "", structured_size=size,
        )
        if candidate:
            old = found.get(url)
            if old is None or candidate["score"] > old["score"]:
                found[url] = candidate

    # 3) Raw product URLs embedded in HTML/JS even when no <a> exists.
    # Prefer a reliable local title over the URL slug. Notino can expose a
    # product ID under a misleading slug (notably p-16167394).
    raw_urls = set(PRODUCT_URL_RE.findall(html or ""))
    raw_urls.update(RELATIVE_PRODUCT_RE.findall(html or ""))
    for raw_url in raw_urls:
        url = normaliseurl(raw_url)
        if not lookslikeproducturl(url):
            continue

        slug = _clean_name(_slug_name(url))
        around = _url_context(html or "", raw_url, radius=900)
        around_no_urls = PRODUCT_URL_RE.sub(" ", around)
        around_no_urls = RELATIVE_PRODUCT_RE.sub(" ", around_no_urls)

        local_names: List[str] = []
        for value in re.findall(
            r'!\[\s*(?:Image\s*\d+\s*:\s*)?([^\]]+)\]\(',
            around_no_urls,
            flags=re.I,
        ):
            cleaned = _clean_name(value)
            if cleaned and not _has_non_perfume_marker(cleaned):
                local_names.append(cleaned)

        for fragment in re.split(r'\n+|\]\s*\[|\|', around_no_urls):
            cleaned = _clean_name(fragment)
            if not cleaned or len(cleaned) > 180 or _has_non_perfume_marker(cleaned):
                continue
            local_names.append(cleaned)

        local_matches = [
            name for name in dict.fromkeys(local_names)
            if _query_matches_name(name, query)
        ]

        if local_matches:
            name = max(
                local_matches,
                key=lambda value: _query_score(
                    value, query, "", _extract_size(value)
                ),
            )
            candidate = _candidate_from_evidence(
                url, name, around_no_urls, query, "embedded-url-context"
            )
        else:
            if not slug or not _query_matches_name(slug, query):
                continue
            candidate = _candidate_from_evidence(
                url, slug, slug, query, "embedded-url-slug"
            )

        if candidate:
            old = found.get(url)
            if old is None or candidate["score"] > old["score"]:
                found[url] = candidate

    return sorted(found.values(), key=lambda item: (-item["score"], item["url"]))


def extract_candidates_from_html(html: str, query: str) -> List[Dict[str, Any]]:
    return _html_candidates(html, _clean(query))


def _url_context(text: str, needle: str, radius: int = 1800) -> str:
    pos = text.find(needle)
    if pos < 0:
        pos = text.casefold().find(needle.casefold())
    if pos < 0:
        return ""
    return text[max(0, pos - radius): min(len(text), pos + len(needle) + radius)]


def _reader_anchor_text(anchor_text: str) -> str:
    """Clean the label of one atomic Markdown product card.

    Jina can emit nested Markdown inside the label, most commonly an image
    link.  The important rule is that we clean *only this anchor label* and
    never borrow text from neighbouring links/cards.
    """
    value = html_lib.unescape(anchor_text or "")
    value = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", value, flags=re.I)
    value = re.sub(
        r"^\s*(?:Cadeaux offerts|Promo Cadeaux offerts|Gifts|Promo)\s*!?",
        " ",
        value,
        flags=re.I,
    )
    value = re.sub(r"\b(?:avec le code|with code)\b.*$", " ", value, flags=re.I)
    return _clean_name(value)


def _scan_markdown_link(raw: str, start: int) -> Optional[Tuple[str, str, int]]:
    """Parse one Markdown link starting at ``start`` with balanced delimiters.

    Regex is deliberately not used here: nested ``[]``/``()`` in Jina output
    can make a regex pair a product URL with an unrelated navigation fragment.
    Returns ``(label, destination, end_position)`` or ``None``.
    """
    if start < 0 or start >= len(raw) or raw[start] != "[":
        return None

    i = start + 1
    depth = 1
    escaped = False
    while i < len(raw):
        ch = raw[i]
        if escaped:
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                break
        i += 1
    if i >= len(raw) or depth != 0:
        return None

    label = raw[start + 1:i]
    j = i + 1
    if j >= len(raw) or raw[j] != "(":
        return None

    j += 1
    paren_depth = 1
    escaped = False
    destination_start = j
    while j < len(raw):
        ch = raw[j]
        if escaped:
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == "(":
            paren_depth += 1
        elif ch == ")":
            paren_depth -= 1
            if paren_depth == 0:
                destination = raw[destination_start:j].strip()
                # Markdown destinations may have a title after whitespace.
                # We only need the first URL token for Notino product links.
                destination = destination.split()[0] if destination else ""
                return label, destination, j + 1
        j += 1
    return None


def _reader_markdown_product_links(raw: str) -> List[Tuple[str, str]]:
    """Extract product URL + title from atomic outer Markdown anchors.

    This parser understands nested Markdown instead of using a greedy regex.
    That distinction matters on Jina output such as navigation links followed
    immediately by product cards: each product URL is paired only with its own
    outer label.
    """
    if not raw:
        return []

    pairs: List[Tuple[str, str]] = []
    i = 0
    while i < len(raw):
        if raw[i] != "[":
            i += 1
            continue
        parsed = _scan_markdown_link(raw, i)
        if not parsed:
            i += 1
            continue
        label_raw, destination, end = parsed
        url = normaliseurl(html_lib.unescape(destination).replace("\\/", "/"))
        if lookslikeproducturl(url):
            label = _reader_anchor_text(label_raw)
            if label:
                pairs.append((label, url))
            i = end
        else:
            # An outer navigation link may contain a nested product link.
            # Resume one character after its opening '[' so the nested link
            # gets its own atomic parse instead of being skipped.
            i += 1
    return pairs


def _reader_markdown_product_cards(raw: str) -> List[Tuple[str, str, str]]:
    """Return ``(label, url, atomic_label)`` for product anchors.

    Kept separate from the public pair helper so the candidate builder can use
    the exact label as its evidence and never attach a broad URL neighbourhood.
    """
    if not raw:
        return []

    cards: List[Tuple[str, str, str]] = []
    i = 0
    while i < len(raw):
        if raw[i] != "[":
            i += 1
            continue
        parsed = _scan_markdown_link(raw, i)
        if not parsed:
            i += 1
            continue
        label_raw, destination, end = parsed
        url = normaliseurl(html_lib.unescape(destination).replace("\\/", "/"))
        if lookslikeproducturl(url):
            label = _reader_anchor_text(label_raw)
            if label:
                cards.append((label, url, label_raw))
            i = end
        else:
            # Keep looking inside non-product outer links for nested product
            # anchors, while preserving atomic boundaries for real cards.
            i += 1
    return cards


def _reader_candidates(text: str, query: str) -> List[Dict[str, Any]]:
    raw = html_lib.unescape(text or "").replace("\\/", "/")
    found: Dict[str, Dict[str, Any]] = {}

    # 1) Atomic Markdown cards are the primary reader-discovery source.
    # The title in the same card is authoritative for identity.  In particular,
    # do NOT reject a card because its URL slug says "9-am" when the card title
    # explicitly says "9 PM Pour Femme" (Notino product p-16167394 is a real
    # example of this URL/title mismatch).
    markdown_cards = _reader_markdown_product_cards(raw)
    paired_urls = set()
    for label, url, label_raw in markdown_cards:
        paired_urls.add(url.rstrip("/"))
        if not _query_matches_name(label, query):
            continue
        # Use only the atomic anchor label as evidence. It contains the product
        # title, size, price and stock text emitted by Notino/Jina, without
        # neighbouring navigation or product cards.
        candidate = _candidate_from_evidence(
            url, label, label_raw, query, "reader-markdown"
        )
        if candidate:
            old = found.get(url)
            if old is None or candidate["score"] > old["score"]:
                found[url] = candidate

    # 2) JSON-LD may survive through Jina in raw HTML form.
    for record in _structured_product_records(raw):
        name, brand, url, price, size = _structured_record_to_evidence(record)
        if not url:
            continue
        candidate = _candidate_from_evidence(
            url, name or _slug_name(url), name, query, "reader-jsonld",
            brand=brand, structured_price=price or "", structured_size=size,
        )
        if candidate:
            old = found.get(url)
            if old is None or candidate["score"] > old["score"]:
                found[url] = candidate

    # 3) Fallback for product URLs that are not paired with an atomic
    # Markdown card.
    #
    # IMPORTANT: the URL slug is NEVER a hard veto here. Notino has real
    # product pages whose slug and title disagree (for example p-16167394
    # uses an "9-am" slug while the actual title is "Afnan 9 PM Pour Femme").
    # Recover a bounded local title first; use the slug only as a last resort.
    matches = list(PRODUCT_URL_RE.finditer(raw)) + list(RELATIVE_PRODUCT_RE.finditer(raw))
    matches.sort(key=lambda match: match.start())

    for match in matches:
        url = normaliseurl(match.group(0))
        if not lookslikeproducturl(url) or url.rstrip("/") in paired_urls:
            continue

        slug = _clean_name(_slug_name(url))
        context = _url_context(raw, match.group(0), radius=900)
        context_without_urls = PRODUCT_URL_RE.sub(" ", context)
        context_without_urls = RELATIVE_PRODUCT_RE.sub(" ", context_without_urls)

        local_names: List[str] = []

        for value in re.findall(
            r"!\[\s*(?:Image\s*\d+\s*:\s*)?([^\]]+)\]\(",
            context_without_urls,
            flags=re.I,
        ):
            cleaned = _clean_name(value)
            if cleaned and not _has_non_perfume_marker(cleaned):
                local_names.append(cleaned)

        for fragment in re.split(r"\n+|\]\s*\[|\|", context_without_urls):
            cleaned = _clean_name(fragment)
            if not cleaned or len(cleaned) > 180 or _has_non_perfume_marker(cleaned):
                continue
            local_names.append(cleaned)

        local_matches = [
            name for name in dict.fromkeys(local_names)
            if _query_matches_name(name, query)
        ]

        if local_matches:
            name = max(
                local_matches,
                key=lambda value: _query_score(
                    value, query, "", _extract_size(value)
                ),
            )
            candidate = _candidate_from_evidence(
                url, name, context_without_urls, query, "reader-url-context"
            )
        else:
            # Slug is only a discovery fallback. It cannot override a title
            # recovered from the local product context.
            if not slug or not _query_matches_name(slug, query):
                continue
            candidate = _candidate_from_evidence(
                url, slug, slug, query, "reader-url-slug"
            )

        if candidate:
            old = found.get(url)
            if old is None or candidate["score"] > old["score"]:
                found[url] = candidate

    return sorted(found.values(), key=lambda item: (-item["score"], item["url"]))


def _extract_variant_offers(text: str) -> List[Tuple[float, str]]:
    """Extract explicit size/price pairs from a Notino product page.

    Only pairs with a size immediately followed by a nearby EUR price are
    accepted. This avoids assigning the price of one bottle size to another.
    """
    soup = BeautifulSoup(text, "html.parser")
    chunks: List[str] = []
    for node in soup.find_all(["option", "label", "button", "li", "div", "span"], limit=2500):
        value = _clean(node.get_text(" ", strip=True))
        if value and SIZE_RE.search(value) and PRICE_RE.search(value):
            chunks.append(value)
    page_text = _clean(soup.get_text(" ", strip=True))
    if page_text:
        chunks.append(page_text)

    found: List[Tuple[float, str]] = []
    seen = set()
    for chunk in chunks:
        for sm in SIZE_RE.finditer(chunk):
            size = _size_to_ml(float(sm.group(1).replace(",", ".")), sm.group(2))
            if size <= 0:
                continue
            tail = chunk[sm.end():sm.end()+180]
            pm = PRICE_RE.search(tail)
            if not pm:
                continue
            price = pm.group(0)
            key = (round(size, 2), _clean(price))
            if key not in seen:
                seen.add(key)
                found.append(key)
    return sorted(found, key=lambda item: (item[0], _clean(item[1])))

def _extract_product_variant_urls(text: str, base_url: str) -> List[str]:
    """Find sibling Notino product-variant URLs exposed on a product page.

    Notino commonly represents bottle sizes as separate /p-<id>/ pages while
    linking those variants from the same product page. The search result may
    discover only one of them, so variant discovery must happen from the
    authoritative product page before applying the requested-size filter.
    """
    found: List[str] = []
    seen = set()
    soup = BeautifulSoup(text or "", "html.parser")

    # First inspect actual hrefs. This keeps URL ownership precise and avoids
    # pairing a product id with neighbouring card text.
    for anchor in soup.find_all("a", href=True):
        url = normaliseurl(urljoin(base_url, str(anchor.get("href") or "")))
        if not lookslikeproducturl(url):
            continue
        key = url.rstrip("/").casefold()
        if key not in seen:
            seen.add(key)
            found.append(url)

    # Jina/Notino can also expose variant links inside JSON or script blobs.
    for raw_url in PRODUCT_URL_RE.findall(text or ""):
        url = normaliseurl(raw_url)
        if not lookslikeproducturl(url):
            continue
        key = url.rstrip("/").casefold()
        if key not in seen:
            seen.add(key)
            found.append(url)
    for raw_url in RELATIVE_PRODUCT_RE.findall(text or ""):
        url = normaliseurl(urljoin(base_url, raw_url))
        if not lookslikeproducturl(url):
            continue
        key = url.rstrip("/").casefold()
        if key not in seen:
            seen.add(key)
            found.append(url)

    return found



def _reader_product(session: requests.Session, candidate: Dict[str, Any], query: str, _allow_variants: bool = True) -> Optional[Dict[str, Any]]:
    try:
        text = _request(session, READER_BASE + candidate["url"], reader=True).text or ""
    except requests.RequestException:
        return None
    if not text:
        return None

    # A discovered product page can be a sibling size rather than the exact
    # requested variant. Do NOT reject it yet: its page can contain links to
    # the exact sibling variant that the search engine failed to discover.
    page_size = _extract_size(text)
    page_size_conflicts = page_size is not None and _requested_size_conflicts(text, query)

    # Notino often links all bottle-size variants from the page of whichever
    # variant happened to be discovered first. The reader representation may
    # omit those hrefs, however, so also fetch the canonical family URL (the
    # same product path without /p-<id>/) and inspect it for sibling variants.
    if _allow_variants:
        variant_urls = _extract_product_variant_urls(text, candidate["url"])

        family_url = re.sub(r"/p-\d+/?$", "/", candidate["url"], flags=re.I)
        family_url = normaliseurl(family_url)
        if family_url.rstrip("/").casefold() != candidate["url"].rstrip("/").casefold():
            try:
                family_text = _request(session, READER_BASE + family_url, reader=True).text or ""
            except requests.RequestException:
                family_text = ""
            if family_text:
                for url in _extract_product_variant_urls(family_text, family_url):
                    if url.rstrip("/").casefold() not in {u.rstrip("/").casefold() for u in variant_urls}:
                        variant_urls.append(url)

        sibling_results: List[Dict[str, Any]] = []
        for variant_url in variant_urls:
            if variant_url.rstrip("/").casefold() == candidate["url"].rstrip("/").casefold():
                continue
            variant_candidate = dict(candidate)
            variant_candidate["url"] = variant_url
            variant_candidate["name"] = candidate.get("name") or _slug_name(variant_url)
            variant_candidate["source"] = "product-variant-url"
            try:
                variant_result = _reader_product(session, variant_candidate, query, _allow_variants=False)
            except Exception:
                variant_result = None
            if isinstance(variant_result, list):
                sibling_results.extend(variant_result)
            elif isinstance(variant_result, dict):
                sibling_results.append(variant_result)
        if sibling_results:
            return sibling_results

    records = _structured_product_records(text)
    structured_name = ""
    structured_price = ""
    structured_size: Optional[float] = None
    structured_brand = ""
    structured_stock: Optional[bool] = None
    for record in records:
        rec_name, rec_brand, rec_url, rec_price, rec_size = _structured_record_to_evidence(record)
        if rec_name and _query_matches_name(rec_name, query):
            structured_name = rec_name
            structured_brand = rec_brand
            structured_price = rec_price or ""
            structured_size = rec_size
            structured_stock = _stock(str(record.get("offers") or "")) if record.get("offers") else None
            break

    # Try headings first, then metadata, then slug.
    name_candidates: List[str] = []
    soup = BeautifulSoup(text, "html.parser")
    for tag in soup.find_all(["h1", "h2", "h3", "title", "strong"], limit=80):
        name = _clean_name(tag.get_text(" ", strip=True))
        if name and _query_matches_name(name, query) and not _has_non_perfume_marker(name):
            name_candidates.append(name)
    for meta in soup.find_all("meta"):
        key = str(meta.get("property") or meta.get("name") or "").casefold()
        content = _clean_name(meta.get("content") or "")
        if key in {"og:title", "twitter:title", "title"} and content and _query_matches_name(content, query):
            name_candidates.append(content)

    name = structured_name or (max(name_candidates, key=lambda item: _query_score(item, query)) if name_candidates else "")
    if not name:
        name = _clean_name(candidate.get("name") or "") or _clean_name(_slug_name(candidate["url"]))
    if not name or not _query_matches_name(name, query) or _has_non_perfume_marker(name):
        return None

    # If this page itself is an explicitly different size and no sibling page
    # produced the requested variant, reject it here. Missing size remains
    # unknown and is handled by the central matcher.
    if page_size_conflicts:
        return None

    variant_offers = _extract_variant_offers(text)
    if variant_offers:
        output = []
        for variant_size, variant_price in variant_offers:
            output.append(result(
                name, variant_price, structured_stock if structured_stock is not None else _stock(text),
                candidate["url"], variant_size, _extract_concentration(text) or _extract_concentration(name),
                _gender_marker(text) or _gender_marker(name), brand=structured_brand or candidate.get("brand", "")
            ))
        if output:
            return output

    price = structured_price or _extract_price(text) or str(candidate.get("price") or "")
    if not price:
        # Search-page evidence remains authoritative enough to retain the
        # candidate even when the product page does not expose its price.
        return None

    stock = structured_stock if structured_stock is not None else (_stock(text) if _stock(text) is not None else candidate.get("stock"))
    size = structured_size or page_size or candidate.get("size_ml")
    concentration = _extract_concentration(text) or _extract_concentration(name) or _extract_concentration(candidate.get("card_text"))
    gender = _gender_marker(text) or _gender_marker(name) or _gender_marker(candidate.get("card_text"))
    return result(name, price, stock, candidate["url"], size, concentration, gender, brand=structured_brand or candidate.get("brand", ""))


def result(
    name: str,
    price: str,
    stock: Optional[bool],
    url: str,
    size: Optional[float],
    concentration: str,
    gender: str,
    *,
    brand: str = "",
) -> Dict[str, Any]:
    availability = "out of stock" if stock is True else "in stock" if stock is False else "unknown"
    display = _display_name(name, url)
    return {
        "store": "notino",
        "name": display,
        "canonicalname": display,
        "catalogvariant": display,
        "brand": _clean(brand),
        "url": normaliseurl(url),
        "price": price,
        "availability": availability,
        "available": False if stock is True else True if stock is False else None,
        "sizeml": size,
        "size": size,
        "size_ml": size,
        "concentration": concentration,
        "canonicalconcentration": concentration,
        "gender": gender,
        "source": {
            "store": "notino",
            "sourcestore": "notino",
            "sourcename": display,
            "source_name": display,
            "source_brand": _clean(brand),
            "url": normaliseurl(url),
        },
        "product_id": _product_id(normaliseurl(url)),
    }


_result = result


def _card_result(candidate: Dict[str, Any], query: str) -> Optional[Dict[str, Any]]:
    name = _clean_name(candidate.get("name") or "")
    card = _clean(candidate.get("card_text") or "")
    if not name or not _query_matches_name(name, query):
        return None
    combined = f"{name} {card}".strip()
    if _requested_size_conflicts(combined, query):
        return None
    price = str(candidate.get("price") or _extract_price(card) or "")
    if not price:
        return None
    return result(
        name,
        price,
        candidate.get("stock"),
        candidate["url"],
        candidate.get("size_ml") or _extract_size(combined),
        _extract_concentration(combined),
        _gender_marker(combined),
        brand=str(candidate.get("brand") or ""),
    )


def _enrich_one(candidate: Dict[str, Any], query: str) -> Any:
    # Search-page candidates built from a broad URL context can contain price
    # and stock belonging to a neighbouring card. Never let that evidence
    # short-circuit product-page enrichment. The product URL itself is the
    # authoritative source for name, size, price and availability.
    source = str(candidate.get("source") or "")
    if source in {"embedded-url-context", "reader-url-context"}:
        session = _new_session()
        try:
            return _reader_product(session, candidate, query)
        finally:
            session.close()

    card = _card_result(candidate, query)
    if card:
        return card
    session = _new_session()
    try:
        return _reader_product(session, candidate, query)
    finally:
        session.close()

def _dedupe_results(results: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_key: Dict[str, Dict[str, Any]] = {}
    for item in results:
        url = normaliseurl(item.get("url", ""))
        pid = _product_id(url)
        size = item.get("size_ml")
        size_key = f":size:{size}" if size is not None else ":size:unknown"
        key = (f"id:{pid}" if pid else f"url:{url.lower()}") + size_key
        old = by_key.get(key)
        if old is None:
            by_key[key] = item
            continue
        richness = sum(bool(item.get(k)) for k in ("size_ml", "concentration", "gender", "availability", "price"))
        old_richness = sum(bool(old.get(k)) for k in ("size_ml", "concentration", "gender", "availability", "price"))
        if richness > old_richness:
            by_key[key] = item
    return list(by_key.values())


def _discover(query: str, session: requests.Session) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    raw_query = _clean(query)
    identity_query = " ".join(_query_identity_tokens(raw_query))
    compact_query = re.sub(r"(?<=\d)\s+(?=[a-z])|(?<=[a-z])\s+(?=\d)", "", _norm(raw_query))
    queries: List[str] = []
    seen_q = set()
    for value in (raw_query, identity_query, compact_query):
        key = value.casefold()
        if value and key not in seen_q:
            seen_q.add(key)
            queries.append(value)

    diagnostics: Dict[str, Any] = {
        "strategy": "direct-html+jsonld -> Jina search -> sitemap-if-empty",
        "queries": queries[:3],
        "direct": [],
        "reader": [],
        "sitemap_used": False,
    }
    candidates: Dict[str, Dict[str, Any]] = {}

    # Direct HTTP requests are allowed to fail; the reader is the recovery path.
    for search_query in queries[:2]:
        for url in _search_urls(search_query):
            try:
                response = _request(session, url)
                found = _html_candidates(response.text, raw_query)
                diagnostics["direct"].append({"url": url, "status": response.status_code, "candidates": len(found)})
                for item in found:
                    old = candidates.get(item["url"])
                    if old is None or item["score"] > old["score"]:
                        candidates[item["url"]] = item
            except requests.RequestException as exc:
                diagnostics["direct"].append({
                    "url": url,
                    "status": getattr(getattr(exc, "response", None), "status_code", None),
                    "error": f"{type(exc).__name__}: {exc}",
                })

    for search_query in queries[:3]:
        for url in _search_urls(search_query):
            text, error = _reader_search(session, url)
            if text is None:
                diagnostics["reader"].append({"url": url, "query": search_query, "status": None, "candidates": 0, "error": error})
                continue
            found = _reader_candidates(text, raw_query)
            diagnostics["reader"].append({
                "url": url,
                "query": search_query,
                "status": 200,
                "candidates": len(found),
                "text_length": len(text),
            })
            for item in found:
                old = candidates.get(item["url"])
                if old is None or item["score"] > old["score"]:
                    candidates[item["url"]] = item

    if not candidates:
        diagnostics["sitemap_used"] = True
        try:
            response = _request(session, SITEMAP_URL)
            soup = BeautifulSoup(response.text, "xml")
            for loc in soup.find_all("loc"):
                url = normaliseurl(loc.get_text(" ", strip=True))
                if not lookslikeproducturl(url):
                    continue
                slug = _clean_name(_slug_name(url))
                if not slug or not _query_matches_name(slug, raw_query):
                    continue
                candidate = _candidate_from_evidence(url, slug, "", raw_query, "sitemap")
                if candidate:
                    candidates[url] = candidate
        except requests.RequestException as exc:
            diagnostics["sitemap_error"] = f"{type(exc).__name__}: {exc}"

    ordered = sorted(candidates.values(), key=lambda item: (-item["score"], item["url"]))
    return ordered, diagnostics


def search(query: str) -> List[Dict[str, Any]]:
    query = _clean(query)
    if not query:
        return []

    session = _new_session()
    try:
        candidates, _ = _discover(query, session)
    finally:
        session.close()

    # Keep more candidates than the old 24-result cutoff, but put the exact
    # query match first. This prevents broad families from hiding the requested
    # variant behind unrelated results.
    candidates = candidates[:MAX_CANDIDATES]
    results: List[Dict[str, Any]] = []
    if not candidates:
        return []

    with ThreadPoolExecutor(max_workers=min(ENRICH_WORKERS, len(candidates))) as executor:
        futures = [executor.submit(_enrich_one, candidate, query) for candidate in candidates]
        for future in as_completed(futures):
            try:
                item = future.result()
            except Exception:
                item = None
            if isinstance(item, list):
                results.extend(item)
            elif item:
                results.append(item)
    return _dedupe_results(results)[:MAX_CANDIDATES]


def scrape(query: str) -> List[Dict[str, Any]]:
    return search(query)


def diagnose(query: str) -> Dict[str, Any]:
    query = _clean(query)
    if not query:
        return {
            "diagnostic": True,
            "scraper_version": SCRAPER_VERSION,
            "query": "",
            "error": "empty_query",
        }

    session = _new_session()
    try:
        candidates, discovery = _discover(query, session)
        enrichment: List[Dict[str, Any]] = []
        for candidate in candidates[:MAX_CANDIDATES]:
            entry = {
                "url": candidate.get("url"),
                "product_id": candidate.get("product_id"),
                "name": candidate.get("name"),
                "score": candidate.get("score"),
                "candidate_source": candidate.get("source"),
                "card_price": candidate.get("price"),
                "card_size_ml": candidate.get("size_ml"),
                "card_stock": candidate.get("stock"),
                "card_attempt": None,
                "product_page_attempt": None,
            }
            try:
                card = _card_result(candidate, query)
                entry["card_attempt"] = {"ok": bool(card), "result": card}
            except Exception as exc:
                entry["card_attempt"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            if not entry["card_attempt"].get("ok"):
                try:
                    page = _reader_product(session, candidate, query)
                    entry["product_page_attempt"] = {"ok": bool(page), "result": page}
                except Exception as exc:
                    entry["product_page_attempt"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            enrichment.append(entry)
    finally:
        session.close()

    return {
        "diagnostic": True,
        "scraper_version": SCRAPER_VERSION,
        "query": query,
        "normalized_query": _norm(query),
        "identity_tokens": _query_identity_tokens(query),
        "discovery": discovery,
        "candidate_count": len(candidates),
        "candidates": candidates[:MAX_CANDIDATES],
        "enrichment": enrichment,
        "result_count": sum(
            1 for item in enrichment
            if item.get("card_attempt", {}).get("ok")
            or item.get("product_page_attempt", {}).get("ok")
        ),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--diagnose", action="store_true")
    args = parser.parse_args()
    payload = diagnose(args.query) if args.diagnose else search(args.query)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
