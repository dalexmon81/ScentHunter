from __future__ import annotations

import html as html_lib
import json
import re
import time
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

TIMEOUT = 15
READER_TIMEOUT = 25
RETRY_COUNT = 2
SCRAPER_VERSION = "notino-3.0-2026-09-03-boundary-fix"

PRODUCT_RE = re.compile(r"/p-(\d+)(?:/|$)", re.I)
PRODUCT_URL_RE = re.compile(
    r"https?://(?:www\.)?notino\.(?:fr|be|de|com|it|gr|es|pt|ie|co\.uk)/[^\s)\]>]+",
    re.I,
)
RELATIVE_PRODUCT_RE = re.compile(
    r"/(?:[a-z0-9][^\s<>\]\[\)\"']*/)+p-\d+(?:/[^\s<>\]\[\)\"']*)?",
    re.I,
)
PRICE_RE = re.compile(
    r"(?:€\s*(\d{1,4}(?:[.,]\d{2})?)|(\d{1,4}(?:[.,]\d{2})?)\s*€)",
    re.I,
)
SIZE_RE = re.compile(
    r"\b(\d{1,4}(?:[.,]\d{1,2})?)\s*(ml|cl|dl|l|oz|fl\s*oz)\b",
    re.I,
)
RATING_RE = re.compile(r"\b\d[.,]\d\s*\(\s*\d+\s*\)", re.I)

GENERIC_QUERY_WORDS = {
    "pour", "femme", "femmes", "homme", "hommes", "for", "the", "and", "avec",
    "de", "du", "des", "la", "le", "les", "un", "une", "par", "eau", "edp", "edt",
    "parfum", "parfums", "perfume", "perfumes", "woman", "women", "man", "men", "unisex",
    "unisexe", "extrait", "spray", "vaporisateur", "eau-de-parfum", "eau-de-toilette",
}
NON_PERFUME_MARKERS = {
    "gift set", "set regalo", "discovery set", "fragrance set", "perfume set", "parfum set",
    "coffret", "bundle", "travel set", "kit", "duo", "trio", "mystery box", "gift box",
    "tester", "testeur", "sample", "samples", "shampoo", "shower gel", "body wash", "body lotion",
    "body cream", "body milk", "deodorant", "deo spray", "aftershave", "after shave", "body spray",
    "hair mist", "makeup", "cosmetics", "cosmetic", "skincare", "skin care", "cosmetici",
    "creme corpo", "crema corpo", "gel doccia", "bagnoschiuma", "deodorante", "cofanetto", "estuche",
    "etui", "pochette",
}
IN_STOCK_MARKERS = (
    "en stock", "ajouter au panier", "add to cart", "in stock", "disponible", "available",
    "σε απόθεμα", "disponibile subito",
)
OUT_STOCK_MARKERS = (
    "en rupture de stock", "rupture de stock", "actuellement indisponible", "produit indisponible",
    "épuisé", "epuise", "currently unavailable", "out of stock", "non disponibile", "momentaneamente non disponibile",
    "προσωρινά μη διαθέσιμο",
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}
READER_HEADERS = {
    "User-Agent": "ScentHunter/3.0",
    "Accept": "text/plain,text/markdown,text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
}


def _clean(value: Any) -> str:
    text = html_lib.unescape(str(value or ""))
    text = text.replace("\\/", "/")
    text = text.replace("â‚¬", "€").replace("Â", "")
    return re.sub(r"\s+", " ", text).strip()


def _norm(value: Any) -> str:
    """Normalize text and split alpha/numeric boundaries such as Afnan9 -> Afnan 9."""
    value = _clean(value).casefold()
    value = unicase_normalize(value)
    value = re.sub(r"(?<=\d)(?=[a-z])", " ", value)
    value = re.sub(r"(?<=[a-z])(?=\d)", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def unicase_normalize(value: str) -> str:
    # Keep this dependency-free: the repository already supports unicode text.
    import unicodedata
    value = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in value if not unicodedata.combining(ch))


def _tokens(value: Any, keep_short: bool = True) -> List[str]:
    raw = re.findall(r"[a-z0-9]+", _norm(value))
    if keep_short:
        return raw
    return [token for token in raw if len(token) > 1]


def _query_identity_tokens(query: str) -> List[str]:
    tokens: List[str] = []
    for token in _tokens(query):
        if token in GENERIC_QUERY_WORDS:
            continue
        if token not in tokens:
            tokens.append(token)
    return tokens


def _requested_sizes(value: Any) -> List[Tuple[str, str]]:
    return [
        (m.group(1).replace(",", "."), re.sub(r"\s+", "", m.group(2).lower()))
        for m in SIZE_RE.finditer(_clean(value))
    ]


def _size_matches(text: Any, size: Tuple[str, str]) -> bool:
    number, unit = size
    number_re = re.escape(number).replace(r"\.", r"[.,]")
    unit_re = re.escape(unit).replace("floz", r"fl\s*oz")
    return bool(re.search(rf"\b{number_re}\s*{unit_re}\b", _clean(text), re.I))


def _requested_size_ok(text: Any, query: str) -> bool:
    sizes = _requested_sizes(query)
    return not sizes or any(_size_matches(text, size) for size in sizes)


def _query_matches_name(name: str, query: str) -> bool:
    """Strict identity matching, tolerant of retailer alpha/numeric formatting."""
    name_norm = _norm(name)
    query_norm = _norm(query)
    name_tokens = set(name_norm.split())
    required = _query_identity_tokens(query)

    if not required or not name_tokens:
        return False
    if not all(token in name_tokens for token in required):
        return False

    # The explicit query sequence must exist, after alpha/numeric normalization.
    q_sequence = query_norm.split()
    n_sequence = name_norm.split()
    if q_sequence and not any(
        n_sequence[i:i + len(q_sequence)] == q_sequence
        for i in range(0, len(n_sequence) - len(q_sequence) + 1)
    ):
        # Brand may be omitted from the retailer anchor, so fall back to the
        # identity-token check only when the explicit query's brand is absent.
        q_without_brand = [t for t in q_sequence if t not in {"pour", "femme", "homme", "for", "women", "woman", "men", "man"}]
        if not q_without_brand or not all(token in name_tokens for token in q_without_brand):
            return False

    q = query_norm
    n = name_norm
    gender_checks = (
        (r"\b(?:pour|for) femmes?\b", r"\b(?:pour|for) femmes?\b"),
        (r"\b(?:pour|for) hommes?\b", r"\b(?:pour|for) hommes?\b"),
        (r"\b(?:pour|for) (?:woman|women)\b", r"\b(?:pour|for) (?:woman|women)\b"),
        (r"\b(?:pour|for) (?:man|men)\b", r"\b(?:pour|for) (?:man|men)\b"),
        (r"\b(?:unisex|unisexe)\b", r"\b(?:unisex|unisexe)\b"),
    )
    for query_pattern, name_pattern in gender_checks:
        if re.search(query_pattern, q) and not re.search(name_pattern, n):
            return False

    return True


def _has_non_perfume_marker(value: Any) -> bool:
    low = _norm(value)
    return any(_norm(marker) in f" {low} " for marker in NON_PERFUME_MARKERS)


def normaliseurl(url: str) -> str:
    value = html_lib.unescape(str(url or "")).strip()
    if not value:
        return ""
    value = value.replace("\\/", "/")
    if value.startswith("//"):
        return "https:" + value
    return urljoin(BASE_URL + "/", value)


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
    if host not in allowed_hosts:
        return False
    path = unquote(parsed.path or "").lower().strip("/")
    return bool(PRODUCT_RE.search(parsed.path or ""))


_looks_like_product_url = lookslikeproducturl


def _product_id(url: str) -> Optional[str]:
    match = PRODUCT_RE.search(url or "")
    return match.group(1) if match else None


def _slug_name(url: str) -> str:
    try:
        path = unquote(urlparse(normaliseurl(url)).path).strip("/")
        parts = [part for part in path.split("/") if part]
        if parts and PRODUCT_RE.fullmatch(parts[-1].split("?", 1)[0]):
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
    value = re.sub(r"\b(?:en stock|in stock|ajouter au panier|add to cart|disponible|available|momentanément indisponible|actuellement indisponible|out of stock)\b.*$", " ", value, flags=re.I)
    # Product cards often concatenate title + concentration + size + availability.
    # The commercial title is the part before the concentration/format suffix.
    value = re.split(
        r"\b(?:eau[- ]de[- ]parfum|eau[- ]de[- ]toilette|eau[- ]de[- ]cologne|extrait(?: de parfum)?|parfum extrait|parfum intense)\b",
        value,
        maxsplit=1,
        flags=re.I,
    )[0]
    value = re.sub(r"\b\d{1,4}(?:[.,]\d{1,2})?\s*(?:ml|cl|dl|l|oz|fl\s*oz)\b.*$", " ", value, flags=re.I)
    value = re.sub(r"^(?:promo|nouveau|discount|cadeaux? offerts?)\s+", "", value, flags=re.I)
    value = re.sub(r"\s+", " ", value).strip(" -|:;,.[]()")
    return value[:220]


def _name_from_text(text: Any, query: str) -> str:
    """Recover a clean commercial title from a retailer card line."""
    cleaned = _clean_name(text)
    if not cleaned:
        return ""
    if _query_matches_name(cleaned, query):
        return cleaned
    return ""


def _display_name(name: str, url: str = "") -> str:
    cleaned = _clean_name(name)
    return cleaned or _clean_name(_slug_name(url))


# Compatibility names used by the current result builder and old diagnostics.
displayname = _display_name


def _extract_price(text: Any) -> str:
    matches = list(PRICE_RE.finditer(_clean(text)))
    if not matches:
        return ""
    raw = matches[-1].group(1) or matches[-1].group(2)
    try:
        return f"{float(raw.replace(',', '.')):.2f}".replace('.', ',') + "€"
    except (TypeError, ValueError):
        return ""


def _stock(text: Any) -> Optional[bool]:
    low = _clean(text).casefold()
    if any(marker in low for marker in OUT_STOCK_MARKERS):
        return True
    if any(marker in low for marker in IN_STOCK_MARKERS):
        return False
    return None


def _extract_size(text: Any) -> Optional[float]:
    match = SIZE_RE.search(_clean(text))
    if not match:
        return None
    try:
        value = float(match.group(1).replace(",", "."))
    except (TypeError, ValueError):
        return None
    unit = re.sub(r"\s+", "", match.group(2).lower())
    if unit == "cl":
        value *= 10
    elif unit == "dl":
        value *= 100
    elif unit == "l":
        value *= 1000
    elif unit in {"oz", "floz"}:
        value *= 29.5735
    return value


def _extract_concentration(text: Any) -> str:
    low = _norm(text)
    if "extrait de parfum" in low or "parfum extrait" in low:
        return "Extrait"
    if "eau de parfum" in low:
        return "Eau de Parfum"
    if "eau de toilette" in low:
        return "Eau de Toilette"
    if "eau de cologne" in low:
        return "Eau de Cologne"
    if re.search(r"\bparfum\b", low):
        return "Parfum"
    return ""


def _extract_gender(text: Any) -> str:
    low = _norm(text)
    if re.search(r"\b(?:pour|for) (?:femme|femmes|woman|women)\b", low):
        return "female"
    if re.search(r"\b(?:pour|for) (?:homme|hommes|man|men)\b", low):
        return "male"
    if re.search(r"\b(?:unisex|unisexe)\b", low):
        return "unisex"
    return ""


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
                time.sleep(0.6 * (attempt + 1))
                continue
            raise
    assert last_error is not None
    raise last_error


def _search_urls(query: str) -> List[str]:
    q = quote_plus(query)
    return [
        f"{SEARCH_URL}?exps={q}",
        f"{BASE_URL}/search?query={q}",
    ]


def _reader_search(session: requests.Session, url: str) -> Optional[str]:
    try:
        return _request(session, READER_BASE + url, reader=True).text or ""
    except requests.RequestException:
        return None


def _extract_name_from_line(line: str, query: str) -> str:
    raw = _clean(line)
    if not raw:
        return ""
    candidates: List[str] = []
    for alt in re.findall(r"!\[\s*(?:Image\s*\d+\s*:\s*)?([^\]]+)\]", raw, flags=re.I):
        candidates.append(_clean_name(re.sub(r"^Image(?:\s*\d+)?\s*:\s*", "", alt, flags=re.I)))
    for match in re.finditer(r"\[([^\]]{3,220})\]\((https?://[^)]+|/[^)]+)\)", raw, flags=re.I):
        candidates.append(_clean_name(match.group(1)))
    stripped = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", raw)
    stripped = re.sub(r"\[[^\]]*\]\([^)]*\)", " ", stripped)
    stripped = re.sub(r"https?://[^\s]+", " ", stripped, flags=re.I)
    stripped = _clean_name(stripped)
    if stripped:
        candidates.append(stripped)
    good = [
        candidate for candidate in candidates
        if candidate and len(candidate) <= 220
        and not _has_non_perfume_marker(candidate)
        and _query_matches_name(candidate, query)
    ]
    return min(good, key=lambda item: (len(item), item.casefold())) if good else ""


def _focused_card_from_html_anchor(a: Any) -> str:
    texts: List[str] = []
    node = a
    for _ in range(8):
        if node is None:
            break
        text = _clean(getattr(node, "get_text", lambda *args, **kwargs: "")(" ", strip=True))
        if text:
            texts.append(text)
        if _extract_price(text):
            break
        node = getattr(node, "parent", None)
    return max(texts, key=len) if texts else ""


def _candidate_from_evidence(url: str, name: str, card: str, query: str, source: str) -> Optional[Dict[str, Any]]:
    url = normaliseurl(url)
    name = _clean_name(name)
    card = _clean(card)
    if not lookslikeproducturl(url):
        return None
    if not name or not _query_matches_name(name, query):
        return None
    if _has_non_perfume_marker(name) or _has_non_perfume_marker(url):
        return None
    if not _requested_size_ok(f"{name} {card}", query):
        return None
    stock = _stock(card)
    return {
        "url": url,
        "name": name,
        "anchor_text": name,
        "card_text": card or name,
        "source": source,
        "product_id": _product_id(url),
        "price": _extract_price(card),
        "stock": stock,
        "size_ml": _extract_size(f"{name} {card}"),
        "score": 100 + (20 if _extract_price(card) else 0) + (10 if stock is not None else 0),
    }


def _html_candidates(html: str, query: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html or "", "html.parser")
    found: Dict[str, Dict[str, Any]] = {}
    for anchor in soup.find_all("a", href=True):
        raw_href = str(anchor.get("href") or "").strip()
        url = normaliseurl(raw_href)
        if not lookslikeproducturl(url):
            continue

        anchor_name = _name_from_text(anchor.get_text(" ", strip=True), query)
        card = _focused_card_from_html_anchor(anchor)
        name = anchor_name if _query_matches_name(anchor_name, query) else ""

        if not name:
            container = anchor
            for _ in range(8):
                container = getattr(container, "parent", None)
                if container is None:
                    break
                for node in container.find_all(["h1", "h2", "h3", "h4", "strong", "span"], limit=40):
                    candidate_name = _name_from_text(node.get_text(" ", strip=True), query)
                    if _query_matches_name(candidate_name, query) and not _has_non_perfume_marker(candidate_name):
                        name = candidate_name
                        break
                if name:
                    break

        if not name:
            # The current Notino HTML often places the title in an image alt.
            for img in anchor.find_all("img", limit=5):
                alt = _name_from_text(img.get("alt") or "", query)
                if _query_matches_name(alt, query):
                    name = alt
                    break

        if not name:
            continue
        candidate = _candidate_from_evidence(url, name, card, query, "direct-html")
        if candidate:
            old = found.get(url)
            if old is None or candidate["score"] > old["score"]:
                found[url] = candidate
    return list(found.values())


def extract_candidates_from_html(html: str, query: str) -> List[Dict[str, Any]]:
    """Compatibility extractor used by the deep diagnostic endpoint."""
    return _html_candidates(html, _clean(query))


def _reader_candidates(text: str, query: str) -> List[Dict[str, Any]]:
    raw = html_lib.unescape(text or "").replace("\\/", "/")
    found: Dict[str, Dict[str, Any]] = {}

    absolute_urls = list(PRODUCT_URL_RE.finditer(raw))

    abs_spans = [(m.start(), m.end()) for m in absolute_urls]

    relative_urls = []

    for match in RELATIVE_PRODUCT_RE.finditer(raw):
        start, end = match.start(), match.end()

        if any(
            start < abs_end and end > abs_start
            for abs_start, abs_end in abs_spans
        ):
            continue

        relative_urls.append(match)

    matches = absolute_urls + relative_urls
    matches.sort(key=lambda match: match.start())

    for match in matches:
        raw_url = match.group(0)
        url = normaliseurl(raw_url)
        if not lookslikeproducturl(url):
            continue

                # Use only the local text between this product URL and the next product URL.
        # This prevents names/prices from neighbouring products being mixed together.
        next_match = None
        for other in matches:
            if other.start() > match.end():
                next_match = other
                break

        start = match.start()
        end = next_match.start() if next_match else min(len(raw), match.end() + 1200)

        window = raw[start:end]
        lines = window.splitlines()

               candidate_names: List[str] = []

        # Jina can place the product URL immediately before the next
        # product card. Therefore arbitrary text after the URL cannot
        # be considered the title of that URL.

        # Look for an explicit markdown link whose target is this exact URL.
        exact_url = url.rstrip("/")

        for md in re.finditer(
            r"\[([^\]]{3,220})\]\((https?://[^)]+|/[^)]+)\)",
            raw,
            flags=re.I,
        ):
            target = normaliseurl(md.group(2)).rstrip("/")

            if target != exact_url:
                continue

            name = _clean_name(md.group(1))

            if (
                name
                and not _has_non_perfume_marker(name)
                and _query_matches_name(name, query)
            ):
                candidate_names.append(name)

        # Look for the image alt text belonging to this product URL.
        url_position = match.start()

        local_before = raw[max(0, url_position - 500):url_position]
        local_after = raw[match.end():min(len(raw), match.end() + 500)]

        for context in (local_before, local_after):
            for image_match in re.finditer(
                r"!\[\s*(?:Image\s*\d+\s*:\s*)?([^\]]{3,220})\]",
                context,
                flags=re.I,
            ):
                name = _clean_name(
                    re.sub(
                        r"^Image(?:\s*\d+)?\s*:\s*",
                        "",
                        image_match.group(1),
                        flags=re.I,
                    )
                )

                if (
                    name
                    and not _has_non_perfume_marker(name)
                    and _query_matches_name(name, query)
                ):
                    candidate_names.append(name)

        # Never manufacture a product name from unrelated text.
        if not candidate_names:
            continue
            set(candidate_names),
            key=lambda item: (len(item), item.casefold())
        )[:4]:

            candidate = _candidate_from_evidence(
                url,
                name,
                window,
                query,
                "reader",
            )

            if not candidate:
                continue

            old = found.get(url)

            if (
                old is None
                or candidate["score"] > old["score"]
                or len(candidate["name"]) < len(old["name"])
            ):
                found[url] = candidate
                break

    return list(found.values())


def _reader_product(session: requests.Session, candidate: Dict[str, Any], query: str) -> Optional[Dict[str, Any]]:
    try:
        text = _request(session, READER_BASE + candidate["url"], reader=True).text or ""
    except requests.RequestException:
        return None
    if not text or not _requested_size_ok(text, query):
        return None

    name = ""
    for line in [_clean(re.sub(r"^#{1,6}\s*", "", item)) for item in text.splitlines() if _clean(item)][:220]:
        if len(line) > 220 or PRICE_RE.search(line):
            continue
        if _query_matches_name(line, query) and not _has_non_perfume_marker(line):
            name = _clean_name(line)
            break
    if not name:
        name = _clean_name(candidate.get("name") or "")
    if not name or not _query_matches_name(name, query) or _has_non_perfume_marker(name):
        return None

    price = _extract_price(text) or str(candidate.get("price") or "")
    if not price:
        return None
    stock = _stock(text)
    size = _extract_size(text) or candidate.get("size_ml")
    concentration = _extract_concentration(text)
    gender = _extract_gender(text)
    return result(name, price, stock, candidate["url"], size, concentration, gender)


def result(
    name: str,
    price: str,
    stock: Optional[bool],
    url: str,
    size: Optional[float],
    concentration: str,
    gender: str,
) -> Dict[str, Any]:
    availability = "out of stock" if stock is True else "in stock" if stock is False else "unknown"
    display = _display_name(name, url)
    return {
        "store": "notino",
        "name": display,
        "canonicalname": display,
        "catalogvariant": display,
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
            "sourcename": "Notino",
            "name": display,
            "source_name": display,
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
    if not _requested_size_ok(f"{name} {card}", query):
        return None
    price = str(candidate.get("price") or _extract_price(card) or "")
    if not price:
        return None
    return result(
        name,
        price,
        candidate.get("stock"),
        candidate["url"],
        candidate.get("size_ml") or _extract_size(f"{name} {card}"),
        _extract_concentration(f"{name} {card}"),
        _extract_gender(f"{name} {card}"),
    )


def _enrich_one(candidate: Dict[str, Any], query: str) -> Optional[Dict[str, Any]]:
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
        key = f"id:{pid}" if pid else f"url:{url.lower()}"
        old = by_key.get(key)
        if old is None:
            by_key[key] = item
            continue
        richness = sum(bool(item.get(k)) for k in ("size_ml", "concentration", "gender", "availability"))
        old_richness = sum(bool(old.get(k)) for k in ("size_ml", "concentration", "gender", "availability"))
        if richness > old_richness:
            by_key[key] = item
    return list(by_key.values())


def _discover(query: str, session: requests.Session) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    candidates: Dict[str, Dict[str, Any]] = {}
    diagnostics: Dict[str, Any] = {
        "strategy": "direct-search -> Jina search -> sitemap-if-empty",
        "direct": [],
        "reader": [],
        "reader_queries": [],
        "sitemap_used": False,
    }

    queries: List[str] = []
    raw_query = _clean(query)
    identity = " ".join(_query_identity_tokens(raw_query))
    compact = re.sub(r"(?<=\d)\s+(?=[a-z])|(?<=[a-z])\s+(?=\d)", "", _norm(raw_query))
    for value in (raw_query, identity, compact):
        if value and value.casefold() not in {x.casefold() for x in queries}:
            queries.append(value)
    diagnostics["reader_queries"] = queries[:3]

    # Direct Notino requests are still useful and cheapest when the edge allows them.
    for search_query in queries[:2]:
        for url in _search_urls(search_query):
            try:
                response = _request(session, url)
                found = _html_candidates(response.text, raw_query)
                diagnostics["direct"].append({"url": url, "status": response.status_code, "candidates": len(found)})
                for item in found:
                    candidates[item["url"]] = item
            except requests.RequestException as exc:
                diagnostics["direct"].append({
                    "url": url,
                    "status": getattr(getattr(exc, "response", None), "status_code", None),
                    "error": f"{type(exc).__name__}: {exc}",
                })

    # Jina Reader is the main recovery path when Notino returns 403 to the app.
    for search_query in queries[:3]:
        for url in _search_urls(search_query):
            text = _reader_search(session, url)
            if text is None:
                diagnostics["reader"].append({"url": url, "query": search_query, "status": None, "candidates": 0})
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
                if old is None or item["score"] > old["score"] or len(item["name"]) < len(old["name"]):
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
                if not _query_matches_name(slug, raw_query):
                    continue
                item = _candidate_from_evidence(url, slug, "", raw_query, "sitemap")
                if item:
                    candidates[url] = item
        except requests.RequestException as exc:
            diagnostics["sitemap_error"] = f"{type(exc).__name__}: {exc}"

    return list(candidates.values()), diagnostics


def search(query: str) -> List[Dict[str, Any]]:
    query = _clean(query)
    if not query:
        return []
    session = _new_session()
    try:
        candidates, _ = _discover(query, session)
    finally:
        session.close()

    candidates.sort(key=lambda item: (-int(item.get("score", 0)), str(item.get("url", ""))))
    candidates = candidates[:24]
    results: List[Dict[str, Any]] = []
    if not candidates:
        return []

    with ThreadPoolExecutor(max_workers=min(4, len(candidates))) as executor:
        futures = [executor.submit(_enrich_one, candidate, query) for candidate in candidates]
        for future in as_completed(futures):
            try:
                item = future.result()
            except Exception:
                item = None
            if item:
                results.append(item)
    return _dedupe_results(results)[:24]


def scrape(query: str) -> List[Dict[str, Any]]:
    return search(query)


def diagnose(query: str) -> Dict[str, Any]:
    query = _clean(query)
    if not query:
        return {"diagnostic": True, "scraper_version": SCRAPER_VERSION, "query": "", "error": "empty_query"}

    report: Dict[str, Any] = {
        "diagnostic": True,
        "scraper_version": SCRAPER_VERSION,
        "query": query,
        "normalized_query": _norm(query),
        "identity_tokens": _query_identity_tokens(query),
        "compatibility_checks": {
            "BASE_URL": BASE_URL,
            "BASEURL_defined": "BASEURL" in globals(),
            "displayname_callable": callable(globals().get("displayname")),
            "_result_callable": callable(globals().get("_result")),
            "extract_candidates_from_html_callable": callable(globals().get("extract_candidates_from_html")),
            "relative_url_probe": normaliseurl("/afnan/9-am-pour-femme-eau-de-parfum-i-pour-femme/p-16167394/") if True else "",
            "alpha_numeric_probe": {
                "query": "Afnan 9 PM Pour Femme",
                "name": "Afnan9 PM Pour Femme",
                "matched": _query_matches_name("Afnan9 PM Pour Femme", "Afnan 9 PM Pour Femme"),
            },
        },
    }

    session = _new_session()
    try:
        candidates, discovery = _discover(query, session)
    finally:
        session.close()

    report["discovery"] = discovery
    report["candidate_count"] = len(candidates)
    report["candidates"] = candidates[:50]

    enrichment: List[Dict[str, Any]] = []
    session_for_product = _new_session()
    try:
        for candidate in candidates[:24]:
            entry = {
                "url": candidate.get("url"),
                "name": candidate.get("name"),
                "price": candidate.get("price"),
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
                    product_page = _reader_product(session_for_product, candidate, query)
                    entry["product_page_attempt"] = {"ok": bool(product_page), "result": product_page}
                except Exception as exc:
                    entry["product_page_attempt"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            enrichment.append(entry)
    finally:
        session_for_product.close()

    report["enrichment"] = enrichment
    report["result_count"] = sum(1 for entry in enrichment if entry.get("card_attempt", {}).get("ok") or entry.get("product_page_attempt", {}).get("ok"))
    return report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--diagnose", action="store_true")
    args = parser.parse_args()
    payload = diagnose(args.query) if args.diagnose else search(args.query)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
