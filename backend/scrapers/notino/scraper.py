from __future__ import annotations

import html as html_lib
import json
import re
import difflib
from xml.etree import ElementTree as ET
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote_plus, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


STORE = "Notino"
BASE_URL = "https://www.notino.fr"
SEARCH_URL = BASE_URL + "/search.asp"
SITEMAP_URL = BASE_URL + "/sitemap.xml"
READER_BASE = "https://r.jina.ai/"
TIMEOUT = 8
READER_TIMEOUT = 6

SCRAPER_VERSION = (
    "notino-FR-generic-discovery-2026-08-21-v16-fast-reader"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

READER_HEADERS = {
    "User-Agent": "ScentHunter/1.0",
    "Accept": (
        "text/plain,text/markdown,text/html;q=0.9,*/*;q=0.8"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
}

PRODUCT_RE = re.compile(
    r"/p-\d+(?:/|$)",
    re.I,
)

PRODUCT_URL_RE = re.compile(
    r'https?://(?:www\.)?notino\.fr/[^\s)\]>\" ]+',
    re.I,
)

READER_ABSOLUTE_PRODUCT_RE = re.compile(
    r"(?:https?:)?(?:\/\/|//)"
    r"(?:www\.)?notino\.fr(?:/)"
    r"[^\s<>)\]\"']+",
    re.I,
)

READER_RELATIVE_PRODUCT_RE = re.compile(
    r"/(?:[a-z0-9][^\s<>)\]\"']*/)+"
    r"[^\s<>)\]\"']+",
    re.I,
)

PRICE_RE = re.compile(
    r"(?:€\s*(\d{1,4}[.,]\d{2})|"
    r"(\d{1,4}[.,]\d{2})\s*€)",
    re.I,
)

RATING_RE = re.compile(
    r"\b\d[.,]\d\s*\(\s*\d+\s*\)",
    re.I,
)

CHALLENGE_MARKERS = (
    "just a moment",
    "cf-chl-",
    "challenge-platform",
    "checking your browser",
    "verify you are human",
    "enable javascript and cookies",
    "vérification de sécurité en cours",
)

IN_STOCK_MARKERS = (
    "en stock",
    "ajouter au panier",
    "add to cart",
    "disponible",
)

OUT_STOCK_MARKERS = (
    "en rupture de stock",
    "rupture de stock",
    "actuellement indisponible",
    "produit indisponible",
)

NON_PERFUME_MARKERS = {
    "gift set",
    "set regalo",
    "set",
    "discovery set",
    "fragrance set",
    "perfume set",
    "parfum set",
    "coffret",
    "bundle",
    "pack",
    "travel set",
    "kit",
    "duo",
    "trio",
    "mystery box",
    "tester",
    "testeur",
    "sample",
    "shampoo",
    "shower gel",
    "body wash",
    "body lotion",
    "body cream",
    "body milk",
    "deodorant",
    "deo spray",
    "aftershave",
    "after shave",
    "body spray",
    "hair mist",
    "makeup",
    "cosmetics",
    "cosmetic",
    "skincare",
    "skin care",
    "cosmetici",
}

SIZE_RE = re.compile(
    r"\b(\d{1,4}(?:[.,]\d{1,2})?)\s*"
    r"(ml|cl|dl|l|oz|fl\s*oz|g|kg)\b",
    re.I,
)


def _product_norm(value: Any) -> str:
    value = str(value or "").lower()
    value = re.sub(
        r"[^a-z0-9]+",
        " ",
        value,
    )
    return re.sub(
        r"\s+",
        " ",
        value,
    ).strip()


def _has_non_perfume_marker(value: Any) -> bool:
    tokens = set(
        _product_norm(value).split()
    )

    for marker in NON_PERFUME_MARKERS:
        marker_tokens = set(
            _product_norm(marker).split()
        )

        if (
            marker_tokens
            and marker_tokens.issubset(tokens)
        ):
            return True

    return False


def _has_non_perfume_marker_in_product(
    name: Any,
    url: Any = "",
    title: Any = "",
) -> bool:
    for value in (name, title):
        if _has_non_perfume_marker(value):
            return True

    try:
        path = unquote(
            urlparse(
                str(url or "")
            ).path
        )
    except Exception:
        path = str(url or "")

    return _has_non_perfume_marker(path)


def _fix_mojibake(value: Any) -> str:
    """
    Repair common UTF-8/Windows-1252 artifacts
    from reader output.
    """

    text = str(value or "")

    if not text:
        return ""

    markers = (
        "â‚¬",
        "Ã©",
        "Ã¨",
        "Ã´",
        "Ã ",
        "Ã¹",
        "Ã¢",
        "Ãª",
        "Ã®",
        "Ã¯",
        "Â€",
        "Â·",
    )

    if any(
        marker in text
        for marker in markers
    ):
        try:
            repaired = (
                text
                .encode("cp1252")
                .decode("utf-8")
            )

            if repaired != text:
                return repaired

        except (
            UnicodeEncodeError,
            UnicodeDecodeError,
        ):
            pass

    return text.replace(
        "â‚¬",
        "€",
    )


def _clean(value: Any) -> str:
    text = _fix_mojibake(value)

    text = re.sub(
        r"\s+",
        " ",
        text,
    ).strip()

    return re.sub(
        r"([a-zà-ÿ])([A-ZÀ-Ÿ])",
        r"\1 \2",
        text,
    )


def _tokens(value: Any) -> List[str]:
    return [
        x
        for x in re.findall(
            r"[a-z0-9]+",
            _clean(value).lower(),
        )
        if len(x) > 1
    ]


def _query_tokens(value: Any) -> List[str]:
    text = _clean(value)

    text = SIZE_RE.sub(
        " ",
        text,
    )

    return _tokens(text)


def _fuzzy_query_match(
    name: Any,
    query: Any,
) -> Tuple[
    bool,
    Dict[str, bool],
    int,
]:
    """
    Fuzzy matching between query tokens and product name tokens.

    Fixed version:
    the length comparison is now made against the
    ACTUAL closest candidate token instead of the
    longest token in the product name.
    """

    name_tokens = set(
        _query_tokens(name)
    )

    query_tokens = _query_tokens(query)

    if (
        not query_tokens
        or not name_tokens
    ):
        return False, {}, 0

    hits: Dict[str, bool] = {}
    fuzzy_hits = 0

    for token in query_tokens:
        if token in name_tokens:
            hits[token] = True
            continue

        best_ratio = 0.0
        best_length = 0

        for candidate in name_tokens:
            ratio = difflib.SequenceMatcher(
                None,
                token,
                candidate,
            ).ratio()

            if ratio > best_ratio:
                best_ratio = ratio
                best_length = len(candidate)

        hit = (
            best_ratio >= 0.80
            and abs(
                len(token) - best_length
            ) <= 2
        )

        hits[token] = hit
        fuzzy_hits += int(hit)

    return (
        all(hits.values()),
        hits,
        fuzzy_hits,
    )


def _requested_sizes(
    value: Any,
) -> List[Tuple[str, str]]:
    sizes: List[
        Tuple[str, str]
    ] = []

    for match in SIZE_RE.finditer(
        _clean(value)
    ):
        number = match.group(
            1
        ).replace(
            ",",
            ".",
        )

        unit = re.sub(
            r"\s+",
            "",
            match.group(2).lower(),
        )

        sizes.append(
            (
                number,
                unit,
            )
        )

    return sizes


def _size_matches(
    text: Any,
    size: Tuple[str, str],
) -> bool:
    number, unit = size

    number_pattern = re.escape(
        number
    ).replace(
        r"\.",
        r"[.,]",
    )

    unit_pattern = re.escape(
        unit
    ).replace(
        "floz",
        r"fl\s*oz",
    )

    pattern = re.compile(
        rf"\b{number_pattern}\s*"
        rf"{unit_pattern}\b",
        re.I,
    )

    return bool(
        pattern.search(
            _clean(text)
        )
    )


def _contains_requested_size(
    text: Any,
    query: Any,
) -> bool:
    requested = _requested_sizes(
        query
    )

    if not requested:
        return True

    return any(
        _size_matches(
            text,
            size,
        )
        for size in requested
    )


def _matches(
    text: Any,
    query: Any,
) -> bool:
    text = _clean(text).lower()

    tokens = _query_tokens(
        query
    )

    return (
        bool(tokens)
        and all(
            token in text
            for token in tokens
        )
    )


def _format_price(
    value: Any,
) -> str:
    match = re.search(
        r"(\d{1,4}(?:[.,]\d{1,2})?)",
        _clean(value),
    )

    if not match:
        return ""

    try:
        number = float(
            match.group(1).replace(
                ",",
                ".",
            )
        )

    except ValueError:
        return ""

    if number <= 0:
        return ""

    return (
        f"{number:.2f}".replace(
            ".",
            ",",
        )
        + "€"
    )


def _extract_price(
    text: Any,
) -> str:
    matches = list(
        PRICE_RE.finditer(
            _clean(text)
        )
    )

    if not matches:
        return ""

    match = matches[-1]

    return _format_price(
        match.group(1)
        or match.group(2)
    )


def _extract_product_price(
    text: Any,
) -> str:
    """
    Extract selling price while avoiding
    unit prices such as:

    26,67 € / 100 ml
    """

    content = _clean(text)

    if not content:
        return ""

    current_matches = list(
        re.finditer(
            r"prix\s+actuel\s+"
            r"(?:de\s+)?"
            r"(\d{1,4}[.,]\d{2})\s*€",
            content,
            flags=re.I,
        )
    )

    for current in reversed(
        current_matches
    ):
        after = content[
            current.end():
            current.end() + 40
        ].lower()

        if not re.match(
            r"\s*/\s*100\s*(?:ml|g)",
            after,
        ):
            return _format_price(
                current.group(1)
            )

    sized_prices = re.findall(
        r"\b\d{1,4}(?:[.,]\d{1,2})?\s*"
        r"(?:ml|cl|dl|l|oz|fl\s*oz|g|kg)\s+"
        r"(?:de\s+)?"
        r"(\d{1,4}[.,]\d{2})\s*€",
        content,
        flags=re.I,
    )

    if sized_prices:
        return _format_price(
            sized_prices[-1]
        )

    price_before_size = re.findall(
        r"(?:€\s*)?"
        r"(\d{1,4}[.,]\d{2})\s*€?\s+"
        r"\d{1,4}(?:[.,]\d{1,2})?\s*"
        r"(?:ml|cl|dl|l|oz|fl\s*oz|g|kg)\b",
        content,
        flags=re.I,
    )

    if price_before_size:
        return _format_price(
            price_before_size[-1]
        )

    valid = []

    for match in PRICE_RE.finditer(
        content
    ):
        after = content[
            match.end():
            match.end() + 40
        ].lower()

        if re.match(
            r"\s*/\s*100\s*(?:ml|g)",
            after,
        ):
            continue

        valid.append(
            match.group(1)
            or match.group(2)
        )

    if valid:
        return _format_price(
            valid[-1]
        )

    return ""


def _extract_price_from_lines(
    text: Any,
) -> str:
    """
    Extra price fallback for Jina/Markdown pages.
    """

    raw = html_lib.unescape(
        str(text or "")
    )

    lines = [
        _clean(line)
        for line in raw.splitlines()
        if _clean(line)
    ]

    priority_patterns = (
        re.compile(
            r"prix\s+actuel.*?"
            r"(\d{1,4}[.,]\d{2})\s*€",
            re.I,
        ),
        re.compile(
            r"(\d{1,4}[.,]\d{2})\s*€"
            r"(?!\s*/\s*100)",
            re.I,
        ),
        re.compile(
            r"€\s*(\d{1,4}[.,]\d{2})"
            r"(?!\s*/\s*100)",
            re.I,
        ),
    )

    for line in lines:
        if len(line) > 500:
            continue

        for pattern in priority_patterns:
            match = pattern.search(
                line
            )

            if match:
                price = _format_price(
                    match.group(1)
                )

                if price:
                    return price

    return ""


def _is_excluded_notino_path(
    path: str,
) -> bool:
    low = (
        path or ""
    ).rstrip("/").lower()

    return any(
        low.startswith(prefix)
        for prefix in (
            "/search",
            "/avis/",
            "/erfahrungen/",
            "/magazine/",
            "/blog/",
            "/panier",
            "/cart",
            "/login",
            "/compte",
            "/account",
        )
    )


def _looks_like_product_url(
    url: str,
) -> bool:
    try:
        parsed = urlparse(
            url
        )

    except Exception:
        return False

    if parsed.netloc.lower() not in {
        "www.notino.fr",
        "notino.fr",
    }:
        return False

    path = parsed.path.rstrip("/")

    if _is_excluded_notino_path(
        path
    ):
        return False

    segments = [
        x
        for x in path.split("/")
        if x
    ]

    return len(segments) >= 2


def _canonical_product_url(
    url: str,
) -> str:
    """
    Collapse:

    /product-slug/p-123

    into:

    /product-slug
    """

    try:
        parsed = urlparse(
            str(url or "")
        )

        path = parsed.path.rstrip("/")

        parts = [
            part
            for part in path.split("/")
            if part
        ]

        if (
            len(parts) >= 3
            and re.fullmatch(
                r"p-\d+",
                parts[-1],
                re.I,
            )
        ):
            path = (
                "/"
                + "/".join(
                    parts[:-1]
                )
            )

        return (
            f"https://{parsed.netloc.lower()}"
            f"{path}"
        )

    except Exception:
        return str(
            url or ""
        ).strip()


def _normalise_reader_url(
    raw: Any,
) -> Optional[str]:
    value = html_lib.unescape(
        str(raw or "")
    ).strip()

    value = (
        value
        .replace(
            "\\/",
            "/",
        )
        .replace(
            "\\u002F",
            "/",
        )
    )

    value = unquote(
        value
    ).strip(
        " <>\"'()[]{}.,;"
    )

    if value.startswith(
        "//"
    ):
        value = (
            "https:"
            + value
        )

    elif value.startswith(
        "/"
    ):
        value = urljoin(
            BASE_URL,
            value,
        )

    try:
        parsed = urlparse(
            value
        )

    except Exception:
        return None

    if parsed.netloc.lower() not in {
        "www.notino.fr",
        "notino.fr",
    }:
        return None

    path = parsed.path

    while (
        path.lower().startswith(
            "/www.notino.fr/"
        )
        or path.lower().startswith(
            "/notino.fr/"
        )
    ):
        path = (
            "/"
            + path.split(
                "/",
                2,
            )[2]
        )

    normalised = (
        f"https://{parsed.netloc.lower()}"
        f"{path.rstrip('/')}"
    )

    normalised = (
        _canonical_product_url(
            normalised
        )
    )

    if not _looks_like_product_url(
        normalised
    ):
        return None

    return normalised


def _search_urls(
    query: str,
) -> List[str]:
    q = quote_plus(
        query
    )

    return [
        f"{SEARCH_URL}?exps={q}",
        f"{BASE_URL}/search?query={q}",
    ]


def _request(
    session: requests.Session,
    url: str,
) -> requests.Response:
    response = session.get(
        url,
        timeout=TIMEOUT,
        allow_redirects=True,
    )

    response.raise_for_status()

    return response


def _reader_request(
    session: requests.Session,
    url: str,
) -> requests.Response:
    response = session.get(
        READER_BASE + url,
        headers=READER_HEADERS,
        timeout=READER_TIMEOUT,
        allow_redirects=True,
    )

    response.raise_for_status()

    return response


def _is_challenge(
    text: str,
) -> bool:
    low = _clean(
        text
    ).lower()

    return any(
        marker in low
        for marker in CHALLENGE_MARKERS
    )


def _clean_name(
    text: str,
) -> str:
    value = RATING_RE.sub(
        " ",
        _clean(text),
    )

    value = PRICE_RE.sub(
        " ",
        value,
    )

    value = re.sub(
        r"^(?:promo|nouveau|discount|"
        r"cadeaux? offerts|livraison offerte)\s+",
        "",
        value,
        flags=re.I,
    )

    words = value.split()

    if (
        len(words) >= 4
        and len(words) % 2 == 0
    ):
        half = len(words) // 2

        if (
            words[:half]
            == words[half:]
        ):
            value = " ".join(
                words[:half]
            )

    return _clean(
        value
    )


def _card_text(
    link,
) -> str:
    node = link

    best = _clean(
        link.get_text(
            " ",
            strip=True,
        )
    )

    for _ in range(10):
        node = getattr(
            node,
            "parent",
            None,
        )

        if node is None:
            break

        text = _clean(
            node.get_text(
                " ",
                strip=True,
            )
        )

        if len(text) > len(best):
            best = text

        if (
            40 <= len(text) <= 1200
            and _extract_price(text)
        ):
            return text

    return best


def _make_candidate(
    url: str,
    anchor: str,
    card: str,
    query: str,
    source: str,
) -> Optional[
    Dict[str, Any]
]:
    url = (
        _clean(url)
        .split("?")[0]
    )

    if not _looks_like_product_url(
        url
    ):
        return None

    anchor = _clean(
        anchor
    )

    card = _clean(
        card
    )

    slug_name = (
        _name_from_product_url(
            url
        )
    )

    url_brand = (
        _brand_from_product_url(
            url
        )
    )

    branded_slug = (
        _clean_name(
            f"{url_brand} {slug_name}"
        )
        if url_brand and slug_name
        else slug_name
    )

    anchor_name = _clean_name(
        anchor
    )

    name = anchor_name

    polluted_anchor = (
        len(anchor_name) > 220
        or anchor_name.count("##") >= 2
        or anchor_name.count("promo") >= 2
        or anchor_name.count("cadeaux") >= 2
        or anchor_name.count("sponsoris") >= 2
    )

    if (
        polluted_anchor
        and slug_name
    ):
        name = slug_name

    if slug_name:
        slug_matches = _fuzzy_query_match(
            (
                f"{url_brand} {slug_name}"
                if url_brand
                else slug_name
            ),
            query,
        )[0]

        if not slug_matches:
            return None

        if (
            polluted_anchor
            or not _fuzzy_query_match(
                name,
                query,
            )[0]
        ):
            name = (
                branded_slug
                or slug_name
            )

    if not name:
        name = _clean_name(
            card
        )

    if (
        not name
        or _has_non_perfume_marker_in_product(
            name,
            url,
            anchor,
        )
    ):
        return None

    matched, hits, fuzzy_hits = (
        _fuzzy_query_match(
            name,
            query,
        )
    )

    query_tokens = _query_tokens(
        query
    )

    if (
        not query_tokens
        or not matched
    ):
        return None

    score = (
        sum(hits.values()) * 5
        + fuzzy_hits * 2
        + 5
    )

    search_context = (
        f"{anchor} {card}"
    )

    requested_sizes = (
        _requested_sizes(
            query
        )
    )

    if requested_sizes:
        if any(
            _size_matches(
                search_context,
                size,
            )
            for size in requested_sizes
        ):
            score += 6
        else:
            score -= 1

    if (
        _extract_price(anchor)
        or _extract_price(card)
    ):
        score += 1

    return {
        "url": url,
        "anchor_text": (
            anchor or name
        ),
        "card_text": (
            card or anchor
        ),
        "name": name,
        "score": score,
        "token_hits": hits,
        "contains_all_query_tokens": matched,
        "requested_size": bool(
            requested_sizes
        ),
        "size_match_in_search_context": (
            any(
                _size_matches(
                    search_context,
                    size,
                )
                for size in requested_sizes
            )
            if requested_sizes
            else True
        ),
        "source": source,
    }


def extract_candidates_from_html(
    html: str,
    query: str,
) -> List[
    Dict[str, Any]
]:
    soup = BeautifulSoup(
        html or "",
        "html.parser",
    )

    found: Dict[
        str,
        Dict[str, Any],
    ] = {}

    for link in soup.find_all(
        "a",
        href=True,
    ):
        url = urljoin(
            BASE_URL,
            _clean(
                link.get(
                    "href"
                )
            ),
        ).split("?")[0]

        if not _looks_like_product_url(
            url
        ):
            continue

        candidate = _make_candidate(
            url,
            _clean(
                link.get_text(
                    " ",
                    strip=True,
                )
            ),
            _card_text(link),
            query,
            "direct-search",
        )

        if (
            candidate
            and (
                candidate["url"]
                not in found
                or candidate["score"]
                > found[
                    candidate["url"]
                ]["score"]
            )
        ):
            found[
                candidate["url"]
            ] = candidate

    return sorted(
        found.values(),
        key=lambda x: (
            not x[
                "contains_all_query_tokens"
            ],
            -x["score"],
            x["url"],
        ),
    )


def _reader_name_from_context(
    context: str,
    query: str,
) -> str:
    raw = (
        html_lib.unescape(
            context or ""
        )
        .replace(
            "\\/",
            "/",
        )
    )

    lines = [
        re.sub(
            r"\s+",
            " ",
            x,
        ).strip()
        for x in str(
            raw
        ).splitlines()
        if x.strip()
    ]

    headings: List[
        Tuple[int, str]
    ] = []

    for line in lines:
        match = re.match(
            r"^(###|##)\s*(.+)$",
            line,
        )

        if not match:
            continue

        headings.append(
            (
                (
                    3
                    if match.group(1)
                    == "###"
                    else 2
                ),
                _clean_name(
                    match.group(2)
                ).strip(
                    " <>[]()"
                ),
            )
        )

    if not headings:
        return ""

    level, title = headings[-1]

    if not title:
        return ""

    if level == 3:
        for (
            prev_level,
            brand,
        ) in reversed(
            headings[:-1]
        ):
            if prev_level == 3:
                break

            if (
                prev_level == 2
                and brand
            ):
                query_tokens = (
                    _query_tokens(
                        query
                    )
                )

                brand_tokens = (
                    _query_tokens(
                        brand
                    )
                )

                brand_relevant = any(
                    bt in query_tokens
                    or any(
                        difflib.SequenceMatcher(
                            None,
                            bt,
                            qt,
                        ).ratio()
                        >= 0.80
                        and abs(
                            len(bt)
                            - len(qt)
                        ) <= 2
                        for qt in query_tokens
                    )
                    for bt in brand_tokens
                )

                combined = _clean_name(
                    f"{brand} {title}"
                )

                if (
                    brand_relevant
                    and _fuzzy_query_match(
                        combined,
                        query,
                    )[0]
                ):
                    return combined

                return (
                    title
                    if _fuzzy_query_match(
                        title,
                        query,
                    )[0]
                    else ""
                )

    return (
        title
        if _fuzzy_query_match(
            title,
            query,
        )[0]
        else ""
    )


def _name_from_product_url(
    url: str,
) -> str:
    try:
        path = unquote(
            urlparse(url).path
        ).strip("/")

    except Exception:
        return ""

    parts = [
        x
        for x in path.split("/")
        if x
    ]

    if len(parts) < 2:
        return ""

    slug = (
        parts[-2]
        if parts[-1].startswith("p-")
        else parts[-1]
    )

    slug = re.sub(
        r"-\d{5,}$",
        "",
        slug,
    )

    slug = re.sub(
        r"[-_]+",
        " ",
        slug,
    )

    return _clean_name(
        slug
    )


def _brand_from_product_url(
    url: str,
) -> str:
    try:
        path = unquote(
            urlparse(url).path
        ).strip("/")

    except Exception:
        return ""

    parts = [
        x
        for x in path.split("/")
        if x
    ]

    return (
        _clean_name(
            parts[0].replace(
                "-",
                " ",
            )
        )
        if len(parts) >= 2
        else ""
    )


def _reader_candidates(
    text: str,
    query: str,
) -> List[
    Dict[str, Any]
]:
    found: Dict[
        str,
        Dict[str, Any],
    ] = {}

    raw = (
        html_lib.unescape(
            text or ""
        )
        .replace(
            "\\/",
            "/",
        )
    )

    lines = [
        x.strip()
        for x in raw.splitlines()
        if x.strip()
    ]

    markdown = re.compile(
        r"\[([^\]]+)\]\(([^)]+)\)",
        re.I,
    )

    for i, line in enumerate(
        lines
    ):
        for match in markdown.finditer(
            line
        ):
            anchor = _clean(
                match.group(1)
            )

            url = _normalise_reader_url(
                match.group(2)
            )

            if not url:
                continue

            name = _clean_name(
                anchor
            )

            query_tokens = (
                _query_tokens(
                    query
                )
            )

            name_tokens = set(
                _query_tokens(
                    name
                )
            )

            needs_heading = (
                not query_tokens
                or not all(
                    token in name_tokens
                    for token in query_tokens
                )
            )

            if needs_heading:
                heading_context = (
                    "\n".join(
                        lines[
                            max(
                                0,
                                i - 80,
                            ):
                            i + 1
                        ]
                    )
                )

                heading_name = (
                    _reader_name_from_context(
                        heading_context,
                        query,
                    )
                )

                if heading_name:
                    name = heading_name

            slug_name = (
                _name_from_product_url(
                    url
                )
            )

            if slug_name and (
                not name
                or not _fuzzy_query_match(
                    name,
                    query,
                )[0]
                or _has_non_perfume_marker(
                    name
                )
            ):
                name = slug_name

            brand = (
                _brand_from_product_url(
                    url
                )
            )

            if brand:
                query_tokens = (
                    _query_tokens(
                        query
                    )
                )

                brand_tokens = (
                    _query_tokens(
                        brand
                    )
                )

                brand_relevant = any(
                    bt in query_tokens
                    or any(
                        difflib.SequenceMatcher(
                            None,
                            bt,
                            qt,
                        ).ratio()
                        >= 0.80
                        and abs(
                            len(bt)
                            - len(qt)
                        ) <= 2
                        for qt in query_tokens
                    )
                    for bt in brand_tokens
                )

                branded_name = (
                    _clean_name(
                        f"{brand} "
                        f"{slug_name or name}"
                    )
                )

                if (
                    brand_relevant
                    and _fuzzy_query_match(
                        branded_name,
                        query,
                    )[0]
                ):
                    name = branded_name

            if (
                not name
                or not _fuzzy_query_match(
                    name,
                    query,
                )[0]
            ):
                continue

            if _has_non_perfume_marker_in_product(
                name,
                url,
                anchor,
            ):
                continue

            candidate = _make_candidate(
                url,
                name,
                anchor or name,
                query,
                "reader-markdown",
            )

            if (
                candidate
                and (
                    url not in found
                    or candidate["score"]
                    > found[url]["score"]
                )
            ):
                found[url] = candidate

    for pattern in (
        PRODUCT_URL_RE,
        READER_ABSOLUTE_PRODUCT_RE,
        READER_RELATIVE_PRODUCT_RE,
    ):
        for match in pattern.finditer(
            raw
        ):
            url = _normalise_reader_url(
                match.group(0)
            )

            if not url:
                continue

            slug_name = (
                _name_from_product_url(
                    url
                )
            )

            if not slug_name:
                continue

            name = slug_name

            brand = (
                _brand_from_product_url(
                    url
                )
            )

            branded_name = (
                _clean_name(
                    f"{brand} {slug_name}"
                )
                if brand
                else ""
            )

            query_tokens = (
                _query_tokens(
                    query
                )
            )

            brand_tokens = (
                _query_tokens(
                    brand
                )
            )

            brand_relevant = (
                bool(brand_tokens)
                and any(
                    bt in query_tokens
                    or any(
                        difflib.SequenceMatcher(
                            None,
                            bt,
                            qt,
                        ).ratio()
                        >= 0.80
                        and abs(
                            len(bt)
                            - len(qt)
                        ) <= 2
                        for qt in query_tokens
                    )
                    for bt in brand_tokens
                )
            )

            if (
                branded_name
                and brand_relevant
                and _fuzzy_query_match(
                    branded_name,
                    query,
                )[0]
            ):
                name = branded_name

            if _has_non_perfume_marker_in_product(
                name,
                url,
            ):
                continue

            if not _fuzzy_query_match(
                name,
                query,
            )[0]:
                continue

            candidate = _make_candidate(
                url,
                name,
                name,
                query,
                "reader-url",
            )

            if (
                candidate
                and (
                    url not in found
                    or candidate["score"]
                    > found[url]["score"]
                )
            ):
                found[url] = candidate

    return sorted(
        found.values(),
        key=lambda x: (
            not bool(
                x.get(
                    "contains_all_query_tokens"
                )
            ),
            -int(
                x.get("score") or 0
            ),
            x["url"],
        ),
    )


def _rank_candidates_for_product_lookup(
    candidates: List[
        Dict[str, Any]
    ],
    limit: int = 3,
) -> List[
    Dict[str, Any]
]:
    if not candidates:
        return []

    ordered = sorted(
        candidates,
        key=lambda x: (
            not bool(
                x.get(
                    "contains_all_query_tokens"
                )
            ),
            -int(
                x.get("score") or 0
            ),
            x.get(
                "url",
                "",
            ),
        ),
    )

    exact = [
        x
        for x in ordered
        if x.get(
            "contains_all_query_tokens"
        )
    ]

    return (
        exact
        if exact
        else ordered
    )[:limit]


def _parse_sitemap_xml(
    text: str,
) -> Tuple[
    str,
    List[str],
]:
    try:
        root = ET.fromstring(
            text or ""
        )

    except ET.ParseError:
        return "", []

    root_type = root.tag.rsplit(
        "}",
        1,
    )[-1].lower()

    locs = []

    for elem in root.iter():
        if (
            elem.tag.rsplit(
                "}",
                1,
            )[-1].lower()
            == "loc"
            and elem.text
        ):
            locs.append(
                html_lib.unescape(
                    elem.text.strip()
                )
            )

    return (
        root_type,
        locs,
    )


def _sitemap_product_urls(
    text: str,
) -> List[str]:
    root_type, locs = (
        _parse_sitemap_xml(
            text
        )
    )

    urls = []
    seen = set()

    if root_type == "urlset":
        for value in locs:
            url = (
                _normalise_reader_url(
                    value
                )
            )

            if (
                url
                and url not in seen
            ):
                seen.add(url)
                urls.append(url)

        return urls

    raw = (
        html_lib.unescape(
            str(text or "")
        )
        .replace(
            "\\/",
            "/",
        )
    )

    for match in re.finditer(
        r"<loc>\s*(.*?)\s*</loc>",
        raw,
        flags=re.I | re.S,
    ):
        url = (
            _normalise_reader_url(
                match.group(1).strip()
            )
        )

        if (
            url
            and url not in seen
        ):
            seen.add(url)
            urls.append(url)

    return urls


def _sitemap_child_urls(
    text: str,
) -> List[str]:
    root_type, locs = (
        _parse_sitemap_xml(
            text
        )
    )

    if root_type == "sitemapindex":
        return list(
            dict.fromkeys(
                x
                for x in locs
                if x.lower().endswith(
                    ".xml"
                )
            )
        )

    raw = (
        html_lib.unescape(
            str(text or "")
        )
        .replace(
            "\\/",
            "/",
        )
    )

    out = []

    for match in re.finditer(
        r"<loc>\s*(.*?)\s*</loc>",
        raw,
        flags=re.I | re.S,
    ):
        value = match.group(
            1
        ).strip()

        if (
            value.lower().endswith(
                ".xml"
            )
            and value not in out
        ):
            out.append(value)

    return out


def _candidate_from_sitemap_url(
    url: str,
    query: str,
) -> Optional[
    Dict[str, Any]
]:
    slug_name = (
        _name_from_product_url(
            url
        )
    )

    if not slug_name:
        return None

    brand = (
        _brand_from_product_url(
            url
        )
    )

    name = slug_name

    branded_name = (
        _clean_name(
            f"{brand} {slug_name}"
        )
        if brand
        else ""
    )

    query_tokens = (
        _query_tokens(
            query
        )
    )

    brand_tokens = (
        _query_tokens(
            brand
        )
    )

    brand_relevant = (
        bool(brand_tokens)
        and any(
            bt in query_tokens
            or any(
                difflib.SequenceMatcher(
                    None,
                    bt,
                    qt,
                ).ratio()
                >= 0.80
                and abs(
                    len(bt)
                    - len(qt)
                ) <= 2
                for qt in query_tokens
            )
            for bt in brand_tokens
        )
    )

    if (
        branded_name
        and brand_relevant
    ):
        name = branded_name

    if _has_non_perfume_marker_in_product(
        name,
        url,
    ):
        return None

    matched, hits, fuzzy_hits = (
        _fuzzy_query_match(
            name,
            query,
        )
    )

    if not matched:
        return None

    score = (
        sum(hits.values()) * 5
        + fuzzy_hits * 2
        + 5
    )

    return {
        "url": url,
        "anchor_text": name,
        "card_text": name,
        "name": name,
        "score": score,
        "token_hits": hits,
        "contains_all_query_tokens": True,
        "requested_size": bool(
            _requested_sizes(
                query
            )
        ),
        "size_match_in_search_context": (
            _contains_requested_size(
                name,
                query,
            )
        ),
        "source": "sitemap",
    }


def _sitemap_discovery(
    query: str,
    session: requests.Session,
    max_child_sitemaps: int = 200,
) -> Tuple[
    List[Dict[str, Any]],
    Dict[str, Any],
]:
    pages: List[
        Dict[str, Any]
    ] = []

    candidates: Dict[
        str,
        Dict[str, Any],
    ] = {}

    def consume(
        text: str,
        source_url: str,
    ) -> List[str]:
        found_urls = (
            _sitemap_product_urls(
                text
            )
        )

        for url in found_urls:
            candidate = (
                _candidate_from_sitemap_url(
                    url,
                    query,
                )
            )

            if candidate:
                old = candidates.get(
                    url
                )

                if (
                    old is None
                    or candidate["score"]
                    > old["score"]
                ):
                    candidates[
                        url
                    ] = candidate

        return found_urls

    try:
        try:
            response = _request(
                session,
                SITEMAP_URL,
            )

            root_text = (
                response.text or ""
            )

            pages.append(
                {
                    "url": SITEMAP_URL,
                    "status": response.status_code,
                    "html_length": len(
                        root_text
                    ),
                    "source": "sitemap",
                }
            )

        except requests.RequestException as exc:
            reader = _reader_request(
                session,
                SITEMAP_URL,
            )

            root_text = (
                reader.text or ""
            )

            pages.append(
                {
                    "url": SITEMAP_URL,
                    "status": getattr(
                        getattr(
                            exc,
                            "response",
                            None,
                        ),
                        "status_code",
                        None,
                    ),
                    "error": (
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    ),
                    "reader_status": (
                        reader.status_code
                    ),
                    "reader_html_length": len(
                        root_text
                    ),
                    "source": (
                        "sitemap-reader"
                    ),
                }
            )

        consume(
            root_text,
            SITEMAP_URL,
        )

        child_sitemaps = (
            _sitemap_child_urls(
                root_text
            )
        )

        for child_url in child_sitemaps[
            :max_child_sitemaps
        ]:
            try:
                try:
                    child = _request(
                        session,
                        child_url,
                    )

                    child_text = (
                        child.text or ""
                    )

                    child_status = (
                        child.status_code
                    )

                    child_source = (
                        "sitemap"
                    )

                except requests.RequestException:
                    child = _reader_request(
                        session,
                        child_url,
                    )

                    child_text = (
                        child.text or ""
                    )

                    child_status = (
                        child.status_code
                    )

                    child_source = (
                        "sitemap-reader"
                    )

                before = len(
                    candidates
                )

                consume(
                    child_text,
                    child_url,
                )

                pages.append(
                    {
                        "url": child_url,
                        "status": child_status,
                        "html_length": len(
                            child_text
                        ),
                        "candidate_count": (
                            len(candidates)
                            - before
                        ),
                        "source": (
                            child_source
                        ),
                    }
                )

            except requests.RequestException as exc:
                pages.append(
                    {
                        "url": child_url,
                        "status": getattr(
                            getattr(
                                exc,
                                "response",
                                None,
                            ),
                            "status_code",
                            None,
                        ),
                        "error": (
                            f"{type(exc).__name__}: "
                            f"{exc}"
                        ),
                        "source": (
                            "sitemap"
                        ),
                    }
                )

    except requests.RequestException as exc:
        pages.append(
            {
                "url": SITEMAP_URL,
                "status": getattr(
                    getattr(
                        exc,
                        "response",
                        None,
                    ),
                    "status_code",
                    None,
                ),
                "error": (
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),
                "source": (
                    "sitemap"
                ),
            }
        )

    return (
        sorted(
            candidates.values(),
            key=lambda x: (
                -x["score"],
                x["url"],
            ),
        ),
        pages,
    )


def _reader_discovery(
    query: str,
    session: requests.Session,
) -> Tuple[
    List[Dict[str, Any]],
    Dict[str, Any],
]:
    """
    FAST JINA DISCOVERY

    Previous behaviour could generate many sequential
    Jina requests:

        Liquid Brun
        Brun Liquid
        Liquid
        Brun
        brand pages
        branded queries
        sitemap
        ...

    This version deliberately limits discovery to:

        1. original query
        2. reversed query

    It stops as soon as 3 exact candidates are found.

    Sitemap is used only when no exact candidate was found.
    """

    query = _clean(
        query
    )

    tokens = _query_tokens(
        query
    )

    candidates: Dict[
        str,
        Dict[str, Any],
    ] = {}

    pages: List[
        Dict[str, Any]
    ] = []

    # ---------------------------------------------------------
    # ONLY TWO QUERY VARIANTS
    # ---------------------------------------------------------

    variants: List[str] = []

    for value in (
        query,
        " ".join(
            reversed(tokens)
        ),
    ):
        value = _clean(
            value
        )

        if (
            value
            and value not in variants
        ):
            variants.append(
                value
            )

    def collect(
        url: str,
        variant: str,
        source_url: str,
    ) -> None:
        try:
            response = _reader_request(
                session,
                url,
            )

            found = _reader_candidates(
                response.text,
                query,
            )

            for candidate in found:
                old = candidates.get(
                    candidate["url"]
                )

                if (
                    old is None
                    or candidate["score"]
                    > old["score"]
                ):
                    candidates[
                        candidate["url"]
                    ] = candidate

            pages.append(
                {
                    "url": source_url,
                    "query": variant,
                    "reader_url": (
                        READER_BASE
                        + source_url
                    ),
                    "status": (
                        response.status_code
                    ),
                    "html_length": len(
                        response.text
                        or ""
                    ),
                    "candidate_count": len(
                        found
                    ),
                    "reader": True,
                }
            )

        except requests.RequestException as exc:
            pages.append(
                {
                    "url": source_url,
                    "query": variant,
                    "reader_url": (
                        READER_BASE
                        + source_url
                    ),
                    "status": getattr(
                        getattr(
                            exc,
                            "response",
                            None,
                        ),
                        "status_code",
                        None,
                    ),
                    "error": (
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    ),
                }
            )

    # ---------------------------------------------------------
    # FAST PATH
    # ---------------------------------------------------------

    for variant in variants:
        search_url = (
            f"{BASE_URL}/search"
            f"?query={quote_plus(variant)}"
        )

        collect(
            search_url,
            variant,
            search_url,
        )

        exact_count = sum(
            1
            for candidate
            in candidates.values()
            if candidate.get(
                "contains_all_query_tokens"
            )
        )

        # Three good candidates are enough.
        if exact_count >= 3:
            break

    # ---------------------------------------------------------
    # RANKING
    # ---------------------------------------------------------

    ordered = sorted(
        candidates.values(),
        key=lambda x: (
            not bool(
                x.get(
                    "contains_all_query_tokens"
                )
            ),
            -int(
                x.get(
                    "score"
                )
                or 0
            ),
            x.get(
                "url",
                "",
            ),
        ),
    )

    # ---------------------------------------------------------
    # SITEMAP ONLY IF NOTHING EXACT WAS FOUND
    # ---------------------------------------------------------

    sitemap_pages: List[
        Dict[str, Any]
    ] = []

    exact_count = sum(
        1
        for candidate in ordered
        if candidate.get(
            "contains_all_query_tokens"
        )
    )

    if exact_count == 0:
        (
            sitemap_candidates,
            sitemap_pages,
        ) = _sitemap_discovery(
            query,
            session,
        )

        for candidate in sitemap_candidates:
            old = candidates.get(
                candidate["url"]
            )

            if (
                old is None
                or candidate["score"]
                > old["score"]
            ):
                candidates[
                    candidate["url"]
                ] = candidate

        ordered = sorted(
            candidates.values(),
            key=lambda x: (
                not bool(
                    x.get(
                        "contains_all_query_tokens"
                    )
                ),
                -int(
                    x.get(
                        "score"
                    )
                    or 0
                ),
                x.get(
                    "url",
                    "",
                ),
            ),
        )

    pages.extend(
        sitemap_pages
    )

    return (
        ordered,
        {
            "query": query,
            "discovery_queries": variants,
            "search_urls": [
                f"{BASE_URL}/search"
                f"?query={quote_plus(x)}"
                for x in variants
            ],
            "pages": pages,
            "raw_product_urls": len(
                ordered
            ),
            "candidate_urls": len(
                ordered
            ),
            "raw_query_token_hits": [
                x
                for x in ordered
                if x.get(
                    "contains_all_query_tokens"
                )
            ],
            "fallback": (
                "jina-reader+sitemap"
            ),
        },
    )


def _search_http_candidates(
    query: str,
    session: Optional[
        requests.Session
    ] = None,
) -> Tuple[
    List[Dict[str, Any]],
    Dict[str, Any],
]:
    own = (
        session is None
    )

    if own:
        session = requests.Session()
        session.headers.update(
            HEADERS
        )

    candidates: Dict[
        str,
        Dict[str, Any],
    ] = {}

    pages = []

    try:
        for url in _search_urls(
            query
        ):
            try:
                response = _request(
                    session,
                    url,
                )

            except requests.RequestException as exc:
                pages.append(
                    {
                        "url": url,
                        "status": getattr(
                            getattr(
                                exc,
                                "response",
                                None,
                            ),
                            "status_code",
                            None,
                        ),
                        "error": (
                            f"{type(exc).__name__}: "
                            f"{exc}"
                        ),
                    }
                )
                continue

            found = (
                extract_candidates_from_html(
                    response.text,
                    query,
                )
            )

            for candidate in found:
                old = candidates.get(
                    candidate["url"]
                )

                if (
                    old is None
                    or candidate["score"]
                    > old["score"]
                ):
                    candidates[
                        candidate["url"]
                    ] = candidate

            pages.append(
                {
                    "url": url,
                    "final_url": response.url,
                    "status": (
                        response.status_code
                    ),
                    "html_length": len(
                        response.text
                        or ""
                    ),
                    "candidate_count": len(
                        found
                    ),
                    "cloudflare": _is_challenge(
                        response.text
                    ),
                    "source": "direct",
                }
            )

            if found:
                break

        ordered = sorted(
            candidates.values(),
            key=lambda x: (
                not x[
                    "contains_all_query_tokens"
                ],
                -x["score"],
                x["url"],
            ),
        )

        if ordered:
            return (
                ordered,
                {
                    "query": query,
                    "search_urls": _search_urls(
                        query
                    ),
                    "pages": pages,
                    "raw_product_urls": len(
                        ordered
                    ),
                    "candidate_urls": len(
                        ordered
                    ),
                    "raw_query_token_hits": [
                        x
                        for x in ordered
                        if x[
                            "contains_all_query_tokens"
                        ]
                    ],
                    "fallback": None,
                },
            )

        reader_candidates, report = (
            _reader_discovery(
                query,
                session,
            )
        )

        report[
            "direct_pages"
        ] = pages

        return (
            reader_candidates,
            report,
        )

    finally:
        if own:
            session.close()


def _json_ld_products(
    soup: BeautifulSoup,
) -> Iterable[
    Dict[str, Any]
]:
    for script in soup.find_all(
        "script",
        type="application/ld+json",
    ):
        try:
            data = json.loads(
                script.string
                or script.get_text()
            )

        except (
            TypeError,
            ValueError,
        ):
            continue

        stack = (
            data
            if isinstance(
                data,
                list,
            )
            else [data]
        )

        while stack:
            item = stack.pop()

            if isinstance(
                item,
                list,
            ):
                stack.extend(
                    item
                )

            elif isinstance(
                item,
                dict,
            ):
                if isinstance(
                    item.get(
                        "@graph"
                    ),
                    list,
                ):
                    stack.extend(
                        item["@graph"]
                    )

                types = item.get(
                    "@type",
                    [],
                )

                types = (
                    types
                    if isinstance(
                        types,
                        list,
                    )
                    else [types]
                )

                if "Product" in types:
                    yield item


def _offer_data(
    offers: Any,
) -> Tuple[
    str,
    str,
]:
    if isinstance(
        offers,
        dict,
    ):
        offers = [
            offers
        ]

    if not isinstance(
        offers,
        list,
    ):
        return "", ""

    for offer in offers:
        if not isinstance(
            offer,
            dict,
        ):
            continue

        availability = _clean(
            offer.get(
                "availability"
            )
        ).lower()

        if any(
            x in availability
            for x in (
                "outofstock",
                "soldout",
                "discontinued",
            )
        ):
            continue

        price = (
            _format_price(
                offer.get(
                    "price"
                )
            )
            or _format_price(
                offer.get(
                    "lowPrice"
                )
            )
        )

        if price:
            return (
                price,
                availability,
            )

    return "", ""


def _requested_size_is_valid(
    text: str,
    query: str,
) -> bool:
    requested = (
        _requested_sizes(
            query
        )
    )

    if not requested:
        return True

    explicit_sizes = (
        SIZE_RE.findall(
            _clean(text)
        )
    )

    if not explicit_sizes:
        return True

    return any(
        _size_matches(
            text,
            size,
        )
        for size in requested
    )


def _extract_reader_product_name(
    text: str,
    candidate: Dict[str, Any],
    query: str,
) -> str:
    """
    Extract a clean product name from Jina.

    Product URL is authoritative.
    """

    raw = (
        _fix_mojibake(
            text
        )
        .replace(
            "\\/",
            "/",
        )
    )

    candidate_url = (
        _canonical_product_url(
            candidate.get(
                "url",
                "",
            )
        )
    )

    # 1. URL slug.
    slug_name = (
        _name_from_product_url(
            candidate_url
        )
    )

    brand = (
        _brand_from_product_url(
            candidate_url
        )
    )

    if slug_name:
        url_name = _clean_name(
            (
                f"{brand} {slug_name}"
                if brand
                else slug_name
            )
        )

        if (
            url_name
            and _fuzzy_query_match(
                url_name,
                query,
            )[0]
            and not _has_non_perfume_marker_in_product(
                url_name,
                candidate_url,
            )
        ):
            return url_name

    # 2. Structured headings.
    lines = []

    for raw_line in raw.splitlines():
        line = _clean(
            re.sub(
                r"^#{1,6}\s*",
                "",
                raw_line,
            )
        )

        if not line:
            continue

        if re.match(
            r"^(title|description|image|url|canonical|meta)\s*:",
            line,
            re.I,
        ):
            continue

        lines.append(
            line
        )

    for line in lines[:180]:
        if (
            len(line) > 220
            or PRICE_RE.search(
                line
            )
        ):
            continue

        cleaned = _clean_name(
            line
        )

        if (
            cleaned
            and _fuzzy_query_match(
                cleaned,
                query,
            )[0]
            and not _has_non_perfume_marker_in_product(
                cleaned,
                candidate_url,
            )
        ):
            return cleaned

    # 3. Discovery fallback.
    for value in (
        candidate.get(
            "name"
        ),
        candidate.get(
            "anchor_text"
        ),
        candidate.get(
            "card_text"
        ),
    ):
        cleaned = _clean_name(
            value or ""
        )

        if (
            cleaned
            and not cleaned.lower().startswith(
                "title:"
            )
            and _fuzzy_query_match(
                cleaned,
                query,
            )[0]
            and not _has_non_perfume_marker_in_product(
                cleaned,
                candidate_url,
            )
        ):
            return cleaned

    return ""


def _reader_product(
    text: str,
    candidate: Dict[str, Any],
    query: str,
) -> Optional[
    Dict[str, Any]
]:
    """
    Parse a Notino product page returned by Jina.
    """

    raw = (
        html_lib.unescape(
            str(text or "")
        )
        .replace(
            "\\/",
            "/",
        )
    )

    content = _clean(
        raw
    )

    if not content:
        return None

    candidate_url = (
        _canonical_product_url(
            candidate.get(
                "url",
                "",
            )
        )
    )

    identity_text = (
        content
        + " "
        + candidate_url
        + " "
        + candidate.get(
            "name",
            "",
        )
    )

    if not _fuzzy_query_match(
        identity_text,
        query,
    )[0]:
        return None

    if not _requested_size_is_valid(
        content
        + " "
        + candidate.get(
            "card_text",
            "",
        ),
        query,
    ):
        return None

    name = (
        _extract_reader_product_name(
            raw,
            candidate,
            query,
        )
    )

    if not name:
        return None

    if _has_non_perfume_marker_in_product(
        name,
        candidate_url,
    ):
        return None

    if not _fuzzy_query_match(
        name,
        query,
    )[0]:
        return None

    # ---------------------------------------------------------
    # PRICE
    # ---------------------------------------------------------

    price = ""

    # 1. JSON-LD.
    for price_match in re.finditer(
        r'"(?:price|lowPrice)"\s*:\s*'
        r'"?(\d{1,4}[.,]\d{2})',
        raw,
        flags=re.I,
    ):
        possible = _format_price(
            price_match.group(1)
        )

        if possible:
            price = possible
            break

    # 2. prix actuel.
    if not price:
        current_matches = re.findall(
            r"prix\s+actuel\s+"
            r"(?:de\s+)?"
            r"(\d{1,4}[.,]\d{2})\s*€",
            content,
            flags=re.I,
        )

        if current_matches:
            price = _format_price(
                current_matches[-1]
            )

    # 3. Price associated with size.
    if not price:
        price = _extract_product_price(
            content
        )

    # 4. Line fallback.
    if not price:
        price = _extract_price_from_lines(
            raw
        )

    # 5. Search card fallback.
    if not price:
        price = (
            _extract_product_price(
                candidate.get(
                    "anchor_text",
                    "",
                )
            )
            or _extract_product_price(
                candidate.get(
                    "card_text",
                    "",
                )
            )
            or _extract_price(
                candidate.get(
                    "anchor_text",
                    "",
                )
            )
            or _extract_price(
                candidate.get(
                    "card_text",
                    "",
                )
            )
        )

    if not price:
        return None

    # ---------------------------------------------------------
    # AVAILABILITY
    # ---------------------------------------------------------

    low = content.lower()

    out_marked = any(
        marker in low
        for marker in OUT_STOCK_MARKERS
    )

    in_marked = any(
        marker in low
        for marker in IN_STOCK_MARKERS
    )

    if (
        out_marked
        and not in_marked
    ):
        return None

    return {
        "store": STORE,
        "name": name,
        "price": price,
        "url": candidate_url,
    }


def _card_result(
    candidate: Dict[str, Any],
    query: str,
) -> Optional[
    Dict[str, Any]
]:
    anchor = _clean(
        candidate.get(
            "anchor_text",
            "",
        )
    )

    card = _clean(
        candidate.get(
            "card_text",
            "",
        )
    )

    url = (
        _canonical_product_url(
            _clean(
                candidate.get(
                    "url",
                    "",
                )
            )
        )
    )

    slug_name = (
        _name_from_product_url(
            url
        )
    )

    brand = (
        _brand_from_product_url(
            url
        )
    )

    if slug_name:
        url_name = _clean_name(
            (
                f"{brand} {slug_name}"
                if brand
                else slug_name
            )
        )

        if not _fuzzy_query_match(
            url_name,
            query,
        )[0]:
            return None

        name = url_name

    else:
        name = _clean_name(
            anchor
        )

    if (
        len(name) > 220
        or name.count("##") >= 2
    ):
        if slug_name:
            name = _clean_name(
                (
                    f"{brand} {slug_name}"
                    if brand
                    else slug_name
                )
            )

        else:
            return None

    if (
        not name
        or _has_non_perfume_marker_in_product(
            name,
            url,
            anchor,
        )
    ):
        return None

    matched, _, _ = (
        _fuzzy_query_match(
            name,
            query,
        )
    )

    if not matched:
        return None

    context = (
        f"{anchor} {card}"
    )

    if not _requested_size_is_valid(
        context,
        query,
    ):
        return None

    price = (
        _extract_price(anchor)
        or _extract_price(card)
        or _extract_product_price(
            anchor
        )
        or _extract_product_price(
            card
        )
    )

    if not price:
        return None

    return {
        "store": STORE,
        "name": name,
        "price": price,
        "url": url,
    }


def _product_details(
    session: requests.Session,
    candidate: Dict[str, Any],
    query: str,
) -> Optional[
    Dict[str, Any]
]:
    url = candidate[
        "url"
    ]

    try:
        response = _request(
            session,
            url,
        )

    except requests.RequestException:
        try:
            reader = _reader_request(
                session,
                url,
            )

            reader_result = (
                _reader_product(
                    reader.text,
                    candidate,
                    query,
                )
            )

            if reader_result:
                return reader_result

            return _card_result(
                candidate,
                query,
            )

        except requests.RequestException:
            return _card_result(
                candidate,
                query,
            )

    final_url = (
        _canonical_product_url(
            response.url.split(
                "?"
            )[0]
        )
    )

    final_slug = (
        _name_from_product_url(
            final_url
        )
    )

    final_brand = (
        _brand_from_product_url(
            final_url
        )
    )

    if final_slug:
        final_name = _clean_name(
            (
                f"{final_brand} "
                f"{final_slug}"
                if final_brand
                else final_slug
            )
        )

        if not _fuzzy_query_match(
            final_name,
            query,
        )[0]:
            return None

    if _has_non_perfume_marker_in_product(
        candidate.get(
            "name",
            "",
        ),
        final_url,
    ):
        return None

    if (
        _is_challenge(
            response.text
        )
        or not _looks_like_product_url(
            final_url
        )
    ):
        try:
            reader = _reader_request(
                session,
                url,
            )

            reader_result = (
                _reader_product(
                    reader.text,
                    candidate,
                    query,
                )
            )

            if reader_result:
                return reader_result

            return _card_result(
                candidate,
                query,
            )

        except requests.RequestException:
            return _card_result(
                candidate,
                query,
            )

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    page_text = _clean(
        soup.get_text(
            " ",
            strip=True,
        )
    )

    if not _requested_size_is_valid(
        page_text,
        query,
    ):
        return None

    name = ""
    price = ""

    # ---------------------------------------------------------
    # JSON-LD
    # ---------------------------------------------------------

    for product in _json_ld_products(
        soup
    ):
        product_name = _clean(
            product.get(
                "name"
            )
        )

        brand_value = product.get(
            "brand"
        )

        brand_value = (
            _clean(
                brand_value.get(
                    "name"
                )
            )
            if isinstance(
                brand_value,
                dict,
            )
            else _clean(
                brand_value
            )
        )

        if _matches(
            f"{brand_value} "
            f"{product_name}",
            query,
        ):
            price, _ = _offer_data(
                product.get(
                    "offers"
                )
            )

            if (
                product_name
                and price
            ):
                name = product_name
                break

    # ---------------------------------------------------------
    # H1
    # ---------------------------------------------------------

    if not name:
        h1 = soup.find(
            "h1"
        )

        if h1 and _matches(
            h1.get_text(
                " ",
                strip=True,
            ),
            query,
        ):
            name = _clean(
                h1.get_text(
                    " ",
                    strip=True,
                )
            )

    # ---------------------------------------------------------
    # TITLE
    # ---------------------------------------------------------

    title = soup.find(
        "title"
    )

    if not name and title:
        candidate_name = (
            _clean(
                title.get_text(
                    " ",
                    strip=True,
                )
            )
            .split("|")[0]
        )

        if _matches(
            candidate_name,
            query,
        ):
            name = candidate_name

    if not name:
        return _card_result(
            candidate,
            query,
        )

    page_title = (
        _clean(
            title.get_text(
                " ",
                strip=True,
            )
        )
        if title
        else ""
    )

    if _has_non_perfume_marker_in_product(
        name,
        final_url,
        page_title,
    ):
        return None

    # ---------------------------------------------------------
    # PRICE FALLBACKS
    # ---------------------------------------------------------

    if not price:
        m = re.search(
            r"prix\s+actuel\s+"
            r"(?:de\s+)?"
            r"(\d{1,4}[.,]\d{2})\s*€",
            page_text,
            re.I,
        )

        if m:
            price = _format_price(
                m.group(1)
            )

    if not price:
        m = re.search(
            r"en\s+stock\s*[|:]?\s*"
            r"(\d{1,4}[.,]\d{2})\s*€",
            page_text,
            re.I,
        )

        if m:
            price = _format_price(
                m.group(1)
            )

    if not price:
        price = _extract_product_price(
            page_text
        )

    if not price:
        price = (
            _extract_product_price(
                candidate.get(
                    "anchor_text",
                    "",
                )
            )
            or _extract_product_price(
                candidate.get(
                    "card_text",
                    "",
                )
            )
        )

    # ---------------------------------------------------------
    # STOCK
    # ---------------------------------------------------------

    low = page_text.lower()

    if (
        any(
            x in low
            for x in OUT_STOCK_MARKERS
        )
        and not any(
            x in low
            for x in IN_STOCK_MARKERS
        )
    ):
        return None

    if not price:
        return None

    return {
        "store": STORE,
        "name": name,
        "price": price,
        "url": final_url,
    }


def search(
    query: str,
) -> List[
    Dict[str, Any]
]:
    query = _clean(
        query
    )

    if not query:
        return []

    session = requests.Session()

    session.headers.update(
        HEADERS
    )

    try:
        candidates, _ = (
            _search_http_candidates(
                query,
                session=session,
            )
        )

        # IMPORTANT:
        # max 3 product pages instead of 8.
        candidates = (
            _rank_candidates_for_product_lookup(
                candidates,
                limit=3,
            )
        )

        results = []
        seen = set()

        for candidate in candidates:
            result = _product_details(
                session,
                candidate,
                query,
            )

            if not result:
                continue

            result["url"] = (
                _canonical_product_url(
                    result.get(
                        "url",
                        "",
                    )
                )
            )

            key = (
                result.get(
                    "url",
                    "",
                )
                + "|"
                + _clean(
                    result.get(
                        "name",
                        "",
                    )
                )
            ).lower()

            if key in seen:
                continue

            seen.add(
                key
            )

            results.append(
                result
            )

            if len(results) >= 10:
                break

        return results

    finally:
        session.close()


def scrape(
    query: str,
) -> List[
    Dict[str, Any]
]:
    return search(
        query
    )


def debug_search(
    query: str,
) -> Dict[str, Any]:
    """
    Diagnostic helper used by the ScentHunter
    test endpoint.
    """

    query = _clean(
        query
    )

    if not query:
        return {
            "ok": False,
            "store": STORE.lower(),
            "query": query,
            "error": "empty_query",
        }

    session = requests.Session()

    session.headers.update(
        HEADERS
    )

    try:
        candidates, discovery = (
            _search_http_candidates(
                query,
                session=session,
            )
        )

        # IMPORTANT:
        # same 3-candidate limit as normal search.
        ranked = (
            _rank_candidates_for_product_lookup(
                candidates,
                limit=3,
            )
        )

        products = []

        for candidate in ranked:
            entry = {
                "candidate": candidate,
                "result": None,
                "error": None,
            }

            try:
                entry["result"] = (
                    _product_details(
                        session,
                        candidate,
                        query,
                    )
                )

            except Exception as exc:
                entry["error"] = (
                    f"{type(exc).__name__}: "
                    f"{exc}"
                )

            products.append(
                entry
            )

        valid_results = [
            x["result"]
            for x in products
            if x.get("result")
        ]

        return {
            "ok": bool(
                valid_results
            ),
            "store": STORE.lower(),
            "query": query,
            "scraper_version": (
                SCRAPER_VERSION
            ),
            "candidate_count": len(
                candidates
            ),
            "ranked_candidate_count": len(
                ranked
            ),
            "result_count": len(
                valid_results
            ),
            "candidates": candidates[:25],
            "products": products,
            "discovery": discovery,
        }

    finally:
        session.close()


def diagnose(
    query: str,
) -> Dict[str, Any]:
    query = _clean(
        query
    )

    if not query:
        return {
            "diagnostic": True,
            "scraper_version": (
                SCRAPER_VERSION
            ),
            "query": query,
            "error": "empty_query",
        }

    session = requests.Session()

    session.headers.update(
        HEADERS
    )

    try:
        candidates, discovery = (
            _search_http_candidates(
                query,
                session=session,
            )
        )

        # Keep diagnostics aligned with normal search.
        candidates_for_product_pages = (
            _rank_candidates_for_product_lookup(
                candidates,
                limit=3,
            )
        )

        discovery[
            "product_page_candidate_limit"
        ] = 3

        discovery[
            "candidate_urls_before_product_page_limit"
        ] = len(
            candidates
        )

        product_pages = []

        for candidate in (
            candidates_for_product_pages
        ):
            try:
                response = _request(
                    session,
                    candidate["url"],
                )

                product_pages.append(
                    {
                        "url": candidate["url"],
                        "status": (
                            response.status_code
                        ),
                        "final_url": (
                            response.url
                        ),
                        "html_length": len(
                            response.text
                            or ""
                        ),
                        "cloudflare": (
                            _is_challenge(
                                response.text
                            )
                        ),
                        "reader_fallback": False,
                        "requested_size": (
                            _requested_sizes(
                                query
                            )
                        ),
                        "size_match": (
                            _requested_size_is_valid(
                                response.text,
                                query,
                            )
                        ),
                    }
                )

            except requests.RequestException as exc:
                try:
                    reader = _reader_request(
                        session,
                        candidate["url"],
                    )

                    reader_result = (
                        _reader_product(
                            reader.text,
                            candidate,
                            query,
                        )
                    )

                    product_pages.append(
                        {
                            "url": candidate["url"],
                            "status": getattr(
                                getattr(
                                    exc,
                                    "response",
                                    None,
                                ),
                                "status_code",
                                None,
                            ),
                            "error": (
                                f"{type(exc).__name__}: "
                                f"{exc}"
                            ),
                            "reader_status": (
                                reader.status_code
                            ),
                            "reader_html_length": len(
                                reader.text
                                or ""
                            ),
                            "reader_fallback": True,
                            "requested_size": (
                                _requested_sizes(
                                    query
                                )
                            ),
                            "size_match": (
                                _requested_size_is_valid(
                                    reader.text,
                                    query,
                                )
                            ),
                            "parsed_result": bool(
                                reader_result
                            ),
                            "parsed_price": (
                                reader_result.get(
                                    "price"
                                )
                                if reader_result
                                else ""
                            ),
                            "parsed_name": (
                                reader_result.get(
                                    "name"
                                )
                                if reader_result
                                else ""
                            ),
                            "parsed_url": (
                                reader_result.get(
                                    "url"
                                )
                                if reader_result
                                else ""
                            ),
                        }
                    )

                except requests.RequestException as reader_exc:
                    product_pages.append(
                        {
                            "url": candidate[
                                "url"
                            ],
                            "status": None,
                            "error": (
                                f"{type(exc).__name__}: "
                                f"{exc}"
                            ),
                            "reader_fallback": True,
                            "reader_error": (
                                f"{type(reader_exc).__name__}: "
                                f"{reader_exc}"
                            ),
                        }
                    )

        return {
            "diagnostic": True,
            "scraper_version": (
                SCRAPER_VERSION
            ),
            "query": query,
            "search_url": _search_urls(
                query
            )[0],
            "discovery": discovery,
            "candidate_count": len(
                candidates
            ),
            "candidates": candidates[:25],
            "product_pages": product_pages,
        }

    finally:
        session.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "query"
    )

    parser.add_argument(
        "--diagnose",
        action="store_true",
    )

    parser.add_argument(
        "--debug-search",
        action="store_true",
    )

    args = parser.parse_args()

    if args.debug_search:
        output = debug_search(
            args.query
        )

    elif args.diagnose:
        output = diagnose(
            args.query
        )

    else:
        output = search(
            args.query
        )

    print(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        )
    )
