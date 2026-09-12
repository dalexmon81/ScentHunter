from __future__ import annotations

import html
import json
import re
import unicodedata
from urllib.parse import quote_plus, urljoin, urlparse

import requests


BASE_URL = "https://www.notino.fr"
READER_BASE = "https://r.jina.ai/"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0 Safari/537.36"
)

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/plain,text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
}

SEARCH_TIMEOUT = (3.0, 18.0)
MAX_CANDIDATES = 10


def _debug(message: str) -> None:
    # Render captures stdout from the worker, so diagnostic information
    # is visible in the Render logs without changing the API contract.
    print(f"[NOTINO DIAG] {message}", flush=True)


def norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_price(value: object) -> float | None:
    if value in (None, ""):
        return None

    text = str(value).replace("\xa0", " ").replace("€", "").strip()
    text = re.sub(r"[^\d,.\-]", "", text)

    if not text:
        return None

    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        if len(text.rsplit(",", 1)[-1]) <= 2:
            text = text.replace(",", ".")
        else:
            text = text.replace(",", "")
    elif text.count(".") > 1:
        text = text.replace(".", "")

    try:
        return float(text)
    except ValueError:
        return None


def money(value: object) -> str:
    price = parse_price(value)
    if price is None:
        return ""
    return f"{price:.2f}".replace(".", ",") + " €"


def extract_size_ml(text: object) -> float | None:
    matches = re.findall(
        r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b",
        str(text or ""),
        flags=re.I,
    )

    values = []

    for number, unit in matches:
        try:
            value = float(number.replace(",", "."))
            if unit.lower() == "cl":
                value *= 10
            values.append(value)
        except ValueError:
            pass

    return min(values) if values else None


IGNORED_QUERY_WORDS = {
    "eau", "de", "parfum", "perfume", "edp", "edt",
    "extrait", "spray", "for", "the", "by", "ml",
}


NON_PERFUME_MARKERS = {
    "gift set", "coffret", "set cadeau", "shampoo", "shampoing",
    "conditioner", "apres rasage", "aftershave", "deodorant",
    "déodorant", "body lotion", "lotion corps", "body cream",
    "cream", "creme", "crème", "serum", "sérum", "makeup",
    "maquillage", "concealer", "masque", "mask", "gel douche",
    "shower gel", "savon", "soap", "blush", "fond de teint",
    "rouge a levres", "rouge à lèvres", "lipstick", "bronzer",
    "skincare", "skin care", "cheveux", "hair", "nail", "ongles",
    "accessoire",
}


def contains_non_perfume_marker(name: object) -> bool:
    text = norm(name)
    return any(norm(marker) in text for marker in NON_PERFUME_MARKERS)


def query_matches(name: str, query: str) -> bool:
    if not name or not query:
        return False

    if contains_non_perfume_marker(name):
        return False

    wanted = [
        token for token in norm(query).split()
        if token not in IGNORED_QUERY_WORDS
    ]

    if not wanted:
        return True

    name_norm = norm(name)
    name_tokens = set(name_norm.split())

    if all(token in name_tokens for token in wanted):
        return True

    return " ".join(wanted) in name_norm


def search_url(query: str) -> str:
    return f"{BASE_URL}/search.asp?exps={quote_plus(query)}"


def reader_url(target_url: str) -> str:
    return READER_BASE + target_url


def get_reader(
    session: requests.Session,
    target_url: str,
) -> tuple[str, dict]:
    url = reader_url(target_url)

    diagnostic = {
        "target_url": target_url,
        "reader_url": url,
        "http_status": None,
        "content_type": "",
        "content_length": 0,
        "final_url": "",
        "error": None,
        "preview": "",
    }

    _debug(f"TARGET {target_url}")
    _debug(f"READER {url}")

    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=SEARCH_TIMEOUT,
            allow_redirects=True,
        )

        diagnostic["http_status"] = response.status_code
        diagnostic["content_type"] = response.headers.get(
            "content-type", ""
        )
        diagnostic["final_url"] = str(response.url)

        text = response.text or ""

        diagnostic["content_length"] = len(text)
        diagnostic["preview"] = re.sub(
            r"\s+",
            " ",
            text[:500],
        )

        _debug(
            f"HTTP {response.status_code} "
            f"TYPE={diagnostic['content_type']} "
            f"LEN={len(text)}"
        )

        _debug(f"FINAL {response.url}")
        _debug(f"PREVIEW {diagnostic['preview']!r}")

        if not response.ok:
            diagnostic["error"] = (
                f"HTTP {response.status_code}"
            )
            return "", diagnostic

        return text, diagnostic

    except requests.RequestException as exc:
        diagnostic["error"] = (
            f"{type(exc).__name__}: {exc}"
        )

        _debug(
            f"REQUEST ERROR {diagnostic['error']}"
        )

        return "", diagnostic


PRODUCT_URL_RE = re.compile(
    r"https?://(?:www\.)?notino\.fr/"
    r"[^)\s\"<>]+?/p-\d+/"
    r"(?:[?#][^)\s\"<>]*)?",
    flags=re.I,
)

RELATIVE_PRODUCT_URL_RE = re.compile(
    r"/[^)\s\"<>]+?/p-\d+/",
    flags=re.I,
)


def clean_product_url(url: str) -> str:
    url = html.unescape(str(url or "")).strip()
    url = url.rstrip(").,;\"'")

    if url.startswith("/"):
        url = urljoin(BASE_URL, url)

    parsed = urlparse(url)

    if parsed.netloc.lower() not in {
        "notino.fr",
        "www.notino.fr",
    }:
        return ""

    if not re.search(r"/p-\d+/?$", parsed.path):
        return ""

    return f"{BASE_URL}{parsed.path.rstrip('/')}/"


def extract_product_urls(markdown: str) -> list[str]:
    urls = []
    seen = set()

    for match in PRODUCT_URL_RE.findall(markdown or ""):
        url = clean_product_url(match)
        if url and url not in seen:
            seen.add(url)
            urls.append(url)

    for match in RELATIVE_PRODUCT_URL_RE.findall(markdown or ""):
        url = clean_product_url(match)
        if url and url not in seen:
            seen.add(url)
            urls.append(url)

    return urls


def extract_markdown_links(
    markdown: str,
) -> list[tuple[str, str]]:
    pattern = re.compile(
        r"\[([^\]]+)\]\((https?://[^)\s]+|/[^)\s]+)\)",
        flags=re.I,
    )

    output = []

    for match in pattern.finditer(markdown or ""):
        anchor = html.unescape(match.group(1)).strip()
        url = clean_product_url(
            html.unescape(match.group(2)).strip()
        )

        if url:
            output.append((anchor, url))

    return output


def candidate_score(
    candidate: dict,
    query: str,
) -> int:
    text = norm(
        f"{candidate.get('search_text', '')} "
        f"{candidate.get('url', '')}"
    )

    wanted = [
        token for token in norm(query).split()
        if token not in IGNORED_QUERY_WORDS
    ]

    score = 0

    for token in wanted:
        if token in text:
            score += 10

    if extract_size_ml(text) is not None:
        score += 3

    if "liquid brun" in text:
        score += 5

    return score


def discover_candidates(
    markdown: str,
    query: str,
) -> list[dict]:
    links = extract_markdown_links(markdown)

    candidates = []
    seen = set()

    for anchor, url in links:
        if url in seen:
            continue

        seen.add(url)

        text = anchor.strip()

        # Some Reader outputs put the product information immediately
        # before/after the markdown link. Keep the anchor plus a nearby
        # context window for matching.
        pos = markdown.find(url)

        context = ""
        if pos >= 0:
            context = markdown[
                max(0, pos - 600):
                min(len(markdown), pos + 900)
            ]

        combined = f"{text} {context}"

        candidates.append(
            {
                "url": url,
                "search_text": text,
                "context": combined,
            }
        )

    # If Markdown links were not preserved, fall back to raw product URLs.
    if not candidates:
        for url in extract_product_urls(markdown):
            if url in seen:
                continue

            seen.add(url)

            candidates.append(
                {
                    "url": url,
                    "search_text": "",
                    "context": "",
                }
            )

    candidates.sort(
        key=lambda item: candidate_score(
            item,
            query,
        ),
        reverse=True,
    )

    candidates = candidates[:MAX_CANDIDATES]

    _debug(
        f"PRODUCT URLS FOUND={len(extract_product_urls(markdown))}"
    )
    _debug(
        f"CANDIDATES SELECTED={len(candidates)}"
    )

    for index, candidate in enumerate(candidates, 1):
        _debug(
            f"CANDIDATE {index}: "
            f"{candidate['url']} "
            f"TEXT={candidate['search_text']!r}"
        )

    return candidates


def strip_markdown(text: str) -> str:
    text = re.sub(
        r"!\[[^\]]*\]\([^)]+\)",
        " ",
        text,
    )

    text = re.sub(
        r"\[([^\]]+)\]\([^)]+\)",
        r"\1",
        text,
    )

    text = re.sub(
        r"https?://\S+",
        " ",
        text,
    )

    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def extract_heading(markdown: str) -> str:
    matches = re.findall(
        r"(?m)^#\s+(.+?)\s*$",
        markdown or "",
    )

    for match in matches:
        title = strip_markdown(match)

        if not title:
            continue

        if norm(title) in {
            "notino",
            "accueil",
            "home",
        }:
            continue

        return title

    return ""


def extract_title_from_text(
    markdown: str,
    fallback: str,
) -> str:
    heading = extract_heading(markdown)

    if heading:
        return heading

    fallback = strip_markdown(fallback)

    if fallback:
        # Try to find a line that looks like a product title.
        for line in fallback.splitlines():
            line = line.strip()

            if (
                len(line) >= 3
                and extract_size_ml(line) is not None
            ):
                return line

        return fallback

    return ""


PRICE_RE = re.compile(
    r"(?<![\d.,])"
    r"(\d{1,4}(?:[ .]\d{3})?(?:[,.]\d{1,2})?)"
    r"\s*€",
    flags=re.I,
)


def extract_prices(markdown: str) -> list[float]:
    values = []

    for match in PRICE_RE.findall(markdown or ""):
        value = parse_price(match)

        if value is None:
            continue

        if 0 < value <= 5000:
            values.append(value)

    return values


def extract_current_price(
    markdown: str,
) -> float | None:
    if not markdown:
        return None

    # First look around common stock/current-price text.
    lines = [
        strip_markdown(line)
        for line in markdown.splitlines()
    ]

    for index, line in enumerate(lines):
        lower = norm(line)

        if (
            "en stock" in lower
            or "ajouter au panier" in lower
            or "prix actuel" in lower
        ):
            local = " ".join(
                lines[max(0, index - 1):index + 3]
            )

            matches = PRICE_RE.findall(local)

            if matches:
                value = parse_price(matches[0])
                if value is not None:
                    return value

    prices = extract_prices(markdown)

    return prices[0] if prices else None


def extract_availability(
    markdown: str,
) -> bool | None:
    text = norm(markdown)

    out_markers = (
        "en rupture de stock",
        "rupture de stock",
        "out of stock",
        "indisponible",
        "non disponible",
    )

    for marker in out_markers:
        if norm(marker) in text:
            return False

    in_markers = (
        "en stock",
        "in stock",
        "disponible",
        "ajouter au panier",
        "add to cart",
    )

    for marker in in_markers:
        if norm(marker) in text:
            return True

    return None


def extract_image(markdown: str) -> str:
    if not markdown:
        return ""

    image_matches = re.findall(
        r"!\[[^\]]*\]\((https?://[^)\s]+)\)",
        markdown,
        flags=re.I,
    )

    for url in image_matches:
        if "notino" in url.lower():
            return url

    plain_matches = re.findall(
        r"https?://[^\s)\"]+\.(?:jpg|jpeg|png|webp)"
        r"(?:\?[^\s)\"]*)?",
        markdown,
        flags=re.I,
    )

    for url in plain_matches:
        if "notino" in url.lower():
            return url

    return ""


def extract_brand(
    title: str,
    fallback: str,
) -> str:
    title = strip_markdown(title)
    fallback = strip_markdown(fallback)

    # Notino often places the brand at the beginning of the title.
    # We only use it when there is enough information to avoid inventing
    # a brand from a one-word perfume name.
    fallback_words = fallback.split()

    if len(fallback_words) >= 2:
        first = fallback_words[0]

        if first.lower() not in {
            "eau", "de", "parfum", "extrait"
        }:
            return first

    words = title.split()

    if len(words) >= 2:
        first = words[0]

        if first.lower() not in {
            "eau", "de", "parfum", "extrait"
        }:
            return first

    return ""


def parse_product(
    markdown: str,
    candidate: dict,
    query: str,
) -> dict | None:
    if not markdown:
        return None

    fallback = (
        candidate.get("search_text")
        or candidate.get("context")
        or ""
    )

    title = extract_title_from_text(
        markdown,
        fallback,
    )

    if not title:
        return None

    if (
        not query_matches(title, query)
        and not query_matches(
            f"{title} {fallback}",
            query,
        )
    ):
        _debug(
            f"REJECT QUERY MISMATCH URL={candidate['url']} "
            f"TITLE={title!r}"
        )
        return None

    price_num = extract_current_price(markdown)
    available = extract_availability(markdown)
    size_ml = extract_size_ml(
        f"{title} {fallback} {markdown[:8000]}"
    )

    brand = extract_brand(
        title,
        fallback,
    )

    image = extract_image(markdown)

    result = {
        "store": "notino",
        "shop": "Notino",
        "brand": brand,
        "name": title,
        "price": money(price_num),
        "price_num": price_num,
        "size_ml": size_ml,
        "url": candidate["url"],
        "available": available,
        "availability": (
            "in_stock"
            if available is True
            else "out_of_stock"
            if available is False
            else "unknown"
        ),
    }

    if image:
        result["image"] = image

    _debug(
        "PARSED "
        f"name={result['name']!r} "
        f"size={result['size_ml']} "
        f"price={result['price_num']} "
        f"available={result['available']}"
    )

    return result


def fetch_product(
    candidate: dict,
    query: str,
) -> dict | None:
    session = requests.Session()

    try:
        _debug(
            f"PRODUCT REQUEST {candidate['url']}"
        )

        markdown, diagnostic = get_reader(
            session,
            candidate["url"],
        )

        if not markdown:
            _debug(
                f"PRODUCT EMPTY URL={candidate['url']} "
                f"STATUS={diagnostic.get('http_status')} "
                f"ERROR={diagnostic.get('error')}"
            )
            return None

        return parse_product(
            markdown,
            candidate,
            query,
        )

    finally:
        session.close()


def search(query: str) -> list[dict]:
    query = str(query or "").strip()

    if not query:
        _debug("EMPTY QUERY")
        return []

    _debug("=" * 60)
    _debug(f"SEARCH START query={query!r}")
    _debug("=" * 60)

    session = requests.Session()

    try:
        target = search_url(query)

        markdown, diagnostic = get_reader(
            session,
            target,
        )

    finally:
        session.close()

    if not markdown:
        _debug(
            "SEARCH FAILED "
            f"status={diagnostic.get('http_status')} "
            f"error={diagnostic.get('error')} "
            f"len={diagnostic.get('content_length')}"
        )
        return []

    _debug(
        f"SEARCH PAGE RECEIVED len={len(markdown)}"
    )

    candidates = discover_candidates(
        markdown,
        query,
    )

    if not candidates:
        _debug(
            "SEARCH PAGE RECEIVED BUT "
            "NO NOTINO PRODUCT URL WAS FOUND"
        )
        return []

    results = []

    # Product pages are fetched concurrently so one slow page does not
    # serialize the entire Notino scraper.
    with __import__("concurrent.futures").futures.ThreadPoolExecutor(
        max_workers=min(5, len(candidates))
    ) as executor:

        future_map = {
            executor.submit(
                fetch_product,
                candidate,
                query,
            ): candidate
            for candidate in candidates
        }

        for future in __import__("concurrent.futures").futures.as_completed(
            future_map
        ):
            candidate = future_map[future]

            try:
                result = future.result()

                if isinstance(result, dict):
                    results.append(result)

            except Exception as exc:
                _debug(
                    f"PRODUCT EXCEPTION "
                    f"url={candidate['url']} "
                    f"error={type(exc).__name__}: {exc}"
                )

    # Deduplicate.
    final = []
    seen = set()

    for result in results:
        key = (
            str(result.get("url") or "").rstrip("/"),
            str(result.get("size_ml") or ""),
        )

        if key in seen:
            continue

        seen.add(key)
        final.append(result)

    final.sort(
        key=lambda item: (
            item.get("available") is not True,
            item.get("price_num") is None,
            item.get("price_num")
            if item.get("price_num") is not None
            else 999999.0,
        )
    )

    _debug(
        f"SEARCH END query={query!r} "
        f"results={len(final)}"
    )

    return final


if __name__ == "__main__":
    for test in (
        "Liquid Brun",
        "Dior Sauvage",
    ):
        print()
        print("=" * 70)
        print(f"TEST: {test}")
        print("=" * 70)

        rows = search(test)

        print(
            json.dumps(
                rows,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
