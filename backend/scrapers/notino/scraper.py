from __future__ import annotations

import html
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus, urljoin, urlparse

import requests


# ============================================================
# NOTINO
# ============================================================

BASE_URL = "https://www.notino.fr"

# Jina Reader is used only as a transport/proxy layer.
# The extracted products must still belong to notino.fr.
READER_BASE = "https://r.jina.ai/"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0 Safari/537.36"
)

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/plain,text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
}

SEARCH_TIMEOUT = (3.0, 18.0)
PRODUCT_TIMEOUT = (3.0, 18.0)

MAX_CANDIDATES = 8
MAX_PRODUCT_REQUESTS = 6


# ============================================================
# NORMALISATION
# ============================================================

def norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(
        char for char in text
        if not unicodedata.combining(char)
    )
    text = text.lower()

    text = re.sub(
        r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)",
        " ",
        text,
    )

    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_price(value: object) -> float | None:
    if value in (None, ""):
        return None

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value)
    text = text.replace("\xa0", " ")
    text = text.replace("€", "")
    text = text.strip()

    # Keep only numbers/separators.
    text = re.sub(r"[^\d,.\-]", "", text)

    if not text:
        return None

    if "," in text and "." in text:
        # French format: 1.234,56
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "")
            text = text.replace(",", ".")
        else:
            # English format: 1,234.56
            text = text.replace(",", "")

    elif "," in text:
        # 51,00
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
    value = str(text or "")

    matches = re.findall(
        r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b",
        value,
        flags=re.I,
    )

    if not matches:
        return None

    sizes: list[float] = []

    for number, unit in matches:
        try:
            size = float(number.replace(",", "."))

            if unit.lower() == "cl":
                size *= 10

            sizes.append(size)

        except ValueError:
            continue

    if not sizes:
        return None

    return min(sizes)


# ============================================================
# QUERY MATCHING
# ============================================================

IGNORED_QUERY_WORDS = {
    "eau",
    "de",
    "parfum",
    "perfume",
    "edp",
    "edt",
    "extrait",
    "spray",
    "for",
    "the",
    "by",
    "ml",
}


NON_PERFUME_MARKERS = {
    "gift set",
    "coffret",
    "set cadeau",
    "set",
    "shampoo",
    "shampoing",
    "conditioner",
    "apres rasage",
    "aftershave",
    "deodorant",
    "déodorant",
    "body lotion",
    "lotion corps",
    "body cream",
    "cream",
    "creme",
    "crème",
    "serum",
    "sérum",
    "makeup",
    "maquillage",
    "concealer",
    "masque",
    "mask",
    "gel douche",
    "shower gel",
    "savon",
    "soap",
    "blush",
    "fond de teint",
    "rouge a levres",
    "rouge à lèvres",
    "lipstick",
    "bronzer",
    "skincare",
    "skin care",
    "cheveux",
    "hair",
    "nail",
    "ongles",
    "accessoire",
}


def contains_non_perfume_marker(name: object) -> bool:
    text = norm(name)

    if not text:
        return True

    for marker in NON_PERFUME_MARKERS:
        marker_norm = norm(marker)

        if not marker_norm:
            continue

        if marker_norm in text:
            return True

    return False


def query_tokens(query: str) -> list[str]:
    return [
        token
        for token in norm(query).split()
        if token not in IGNORED_QUERY_WORDS
    ]


def query_matches(name: str, query: str) -> bool:
    if not name or not query:
        return False

    if contains_non_perfume_marker(name):
        return False

    wanted = query_tokens(query)

    if not wanted:
        return True

    name_norm = norm(name)
    name_tokens = set(name_norm.split())

    # Exact token matching first.
    if all(token in name_tokens for token in wanted):
        return True

    # Also accept contiguous phrase.
    phrase = " ".join(wanted)

    return phrase in name_norm


# ============================================================
# HTTP
# ============================================================

def reader_url(target_url: str) -> str:
    return READER_BASE + target_url


def get_reader(
    session: requests.Session,
    target_url: str,
    timeout: tuple[float, float],
) -> str:
    url = reader_url(target_url)

    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=timeout,
            allow_redirects=True,
        )

        if not response.ok:
            return ""

        text = response.text or ""

        if not text:
            return ""

        return text

    except requests.RequestException:
        return ""


# ============================================================
# NOTINO PRODUCT URL EXTRACTION
# ============================================================

PRODUCT_URL_RE = re.compile(
    r"https?://(?:www\.)?notino\.fr/"
    r"[^)\s\"<>]+?"
    r"/p-\d+/"
    r"(?:[?#][^)\s\"<>]*)?",
    flags=re.I,
)


RELATIVE_PRODUCT_URL_RE = re.compile(
    r"(?:^|\()"
    r"(/[^)\s\"<>]+?/p-\d+/"
    r"(?:[?#][^)\s\"<>]*)?)",
    flags=re.I,
)


def clean_product_url(url: str) -> str:
    url = html.unescape(str(url or "")).strip()

    # Markdown punctuation.
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

    return (
        f"{BASE_URL}"
        f"{parsed.path.rstrip('/')}/"
    )


def extract_product_urls(markdown: str) -> list[str]:
    if not markdown:
        return []

    urls: list[str] = []
    seen: set[str] = set()

    # Absolute URLs.
    for match in PRODUCT_URL_RE.findall(markdown):
        clean = clean_product_url(match)

        if clean and clean not in seen:
            seen.add(clean)
            urls.append(clean)

    # Relative URLs from markdown links.
    for match in RELATIVE_PRODUCT_URL_RE.findall(markdown):
        clean = clean_product_url(match)

        if clean and clean not in seen:
            seen.add(clean)
            urls.append(clean)

    return urls


# ============================================================
# MARKDOWN LINK / PRODUCT TEXT
# ============================================================

def markdown_links(markdown: str) -> list[tuple[str, str]]:
    """
    Return [(anchor_text, url), ...] from Markdown links.
    """
    if not markdown:
        return []

    pattern = re.compile(
        r"\[([^\]]+)\]\((https?://[^)\s]+|/[^)\s]+)\)",
        flags=re.I,
    )

    output: list[tuple[str, str]] = []

    for match in pattern.finditer(markdown):
        anchor = html.unescape(match.group(1)).strip()
        url = html.unescape(match.group(2)).strip()

        clean = clean_product_url(url)

        if clean:
            output.append((anchor, clean))

    return output


def product_context(markdown: str, product_url: str) -> str:
    """
    Extract a small amount of text around a product URL.

    This is intentionally conservative. We never create a product from
    a generic search-engine result. The source URL must be Notino.
    """
    if not markdown or not product_url:
        return ""

    pos = markdown.find(product_url)

    if pos < 0:
        # The URL may have been rendered without the exact final slash.
        stripped = product_url.rstrip("/")
        pos = markdown.find(stripped)

    if pos < 0:
        return ""

    start = max(0, pos - 900)
    end = min(len(markdown), pos + 1400)

    return markdown[start:end]


def find_anchor_for_product(
    markdown: str,
    product_url: str,
) -> str:
    for anchor, url in markdown_links(markdown):
        if url.rstrip("/") == product_url.rstrip("/"):
            return anchor

    context = product_context(markdown, product_url)

    if not context:
        return ""

    # Remove markdown formatting.
    context = re.sub(r"\[[^\]]+\]\([^)]+\)", " ", context)
    context = re.sub(r"https?://\S+", " ", context)
    context = re.sub(r"\s+", " ", context)

    return context.strip()


# ============================================================
# SEARCH PAGE DISCOVERY
# ============================================================

def search_url(query: str) -> str:
    return (
        f"{BASE_URL}/search.asp"
        f"?exps={quote_plus(query)}"
    )


def search_notino(
    session: requests.Session,
    query: str,
) -> list[dict]:
    """
    One Notino search-page request through Jina Reader.

    We intentionally do NOT use Google/Bing/Jina Search as the product
    source. Jina Reader receives the actual Notino URL and returns the
    Notino page content.
    """
    target = search_url(query)

    markdown = get_reader(
        session,
        target,
        SEARCH_TIMEOUT,
    )

    if not markdown:
        return []

    urls = extract_product_urls(markdown)

    candidates: list[dict] = []
    seen: set[str] = set()

    for url in urls:
        if url in seen:
            continue

        seen.add(url)

        anchor = find_anchor_for_product(
            markdown,
            url,
        )

        if anchor:
            anchor_clean = re.sub(
                r"\s+",
                " ",
                anchor,
            ).strip()
        else:
            anchor_clean = ""

        # Search-page discovery can include unrelated products.
        # Filter obvious non-fragrance results here.
        if anchor_clean and contains_non_perfume_marker(anchor_clean):
            continue

        candidates.append(
            {
                "url": url,
                "search_text": anchor_clean,
            }
        )

        if len(candidates) >= MAX_CANDIDATES:
            break

    return candidates


# ============================================================
# PRODUCT PAGE PARSER
# ============================================================

PRICE_RE = re.compile(
    r"(?<![\d.,])"
    r"(\d{1,4}(?:[ .]\d{3})?(?:[,.]\d{1,2})?)"
    r"\s*€",
    flags=re.I,
)


def clean_text(value: object) -> str:
    text = html.unescape(str(value or ""))

    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def extract_prices(markdown: str) -> list[float]:
    values: list[float] = []

    for match in PRICE_RE.findall(markdown or ""):
        price = parse_price(match)

        if price is None:
            continue

        # Ignore obvious per-100ml / delivery / nonsense values.
        if price <= 0 or price > 5000:
            continue

        values.append(price)

    return values


def choose_product_price(markdown: str) -> float | None:
    if not markdown:
        return None

    # Prefer the first price appearing close to the main product section.
    prices = extract_prices(markdown)

    if not prices:
        return None

    # Notino pages normally expose current price before shipping prices.
    return prices[0]


def extract_availability(markdown: str) -> bool | None:
    text = norm(markdown)

    in_stock_markers = (
        "en stock",
        "in stock",
        "disponible",
        "disponibilité",
        "disponibilite",
        "ajouter au panier",
        "add to cart",
    )

    out_stock_markers = (
        "en rupture de stock",
        "rupture de stock",
        "out of stock",
        "indisponible",
        "non disponible",
    )

    for marker in out_stock_markers:
        if norm(marker) in text:
            return False

    for marker in in_stock_markers:
        if norm(marker) in text:
            return True

    return None


def extract_heading(markdown: str) -> str:
    if not markdown:
        return ""

    # Prefer Markdown H1.
    matches = re.findall(
        r"(?m)^#\s+(.+?)\s*$",
        markdown,
    )

    for match in matches:
        title = clean_text(match)

        if not title:
            continue

        if title.lower() not in {
            "notino",
            "accueil",
            "home",
        }:
            return title

    return ""


def extract_brand_and_name(
    markdown: str,
    fallback_text: str,
) -> tuple[str, str]:
    """
    Notino usually renders the brand/name in the heading and immediately
    around the product information.

    We keep the parser conservative and avoid fabricating a brand.
    """
    heading = extract_heading(markdown)

    if heading:
        name = heading
    else:
        name = clean_text(fallback_text)

    brand = ""

    # Common first word / known brand line before the product title.
    lines = [
        clean_text(line)
        for line in (markdown or "").splitlines()
    ]

    lines = [
        line
        for line in lines
        if line and len(line) < 160
    ]

    # Look for a line that appears immediately before the main heading.
    if heading:
        try:
            index = next(
                i
                for i, line in enumerate(lines)
                if norm(line) == norm(heading)
            )

            if index > 0:
                previous = lines[index - 1]

                if (
                    previous
                    and not previous.startswith("[")
                    and not re.search(r"\d+\s*ml", previous, re.I)
                    and len(previous.split()) <= 8
                ):
                    brand = previous

        except StopIteration:
            pass

    # For French Avenue products this naturally produces:
    # brand = French Avenue
    # name  = French Avenue Liquid Brun
    if not brand:
        tokens = name.split()

        if len(tokens) >= 2:
            # Do not blindly assume first word is brand.
            # Search page anchor is a better fallback.
            fallback_tokens = clean_text(
                fallback_text
            ).split()

            if len(fallback_tokens) >= 2:
                brand = fallback_tokens[0]

    return brand, name


def extract_image(markdown: str) -> str:
    if not markdown:
        return ""

    # Markdown images.
    matches = re.findall(
        r"!\[[^\]]*\]\((https?://[^)\s]+)\)",
        markdown,
        flags=re.I,
    )

    for url in matches:
        lower = url.lower()

        if (
            "notino" in lower
            and not lower.endswith(".svg")
        ):
            return url

    # Plain image URLs.
    matches = re.findall(
        r"https?://[^\s)\"]+\.(?:jpg|jpeg|png|webp)(?:\?[^\s)\"]*)?",
        markdown,
        flags=re.I,
    )

    for url in matches:
        if "notino" in url.lower():
            return url

    return ""


def parse_product_page(
    markdown: str,
    product_url: str,
    fallback_text: str,
    query: str,
) -> dict | None:
    if not markdown:
        return None

    brand, name = extract_brand_and_name(
        markdown,
        fallback_text,
    )

    if not name:
        return None

    # Make sure this is actually a matching perfume/product.
    if not query_matches(name, query):
        combined = f"{brand} {name}".strip()

        if not query_matches(combined, query):
            # Search text can be more reliable than a shortened heading.
            if not query_matches(fallback_text, query):
                return None

            if fallback_text:
                name = clean_text(fallback_text)

    size_ml = extract_size_ml(
        f"{name} {fallback_text} {markdown[:5000]}"
    )

    price_num = choose_product_price(markdown)

    available = extract_availability(markdown)

    image = extract_image(markdown)

    result = {
        "store": "notino",
        "shop": "Notino",
        "brand": brand,
        "name": name,
        "price": money(price_num),
        "price_num": price_num,
        "size_ml": size_ml,
        "url": product_url,
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

    return result


# ============================================================
# PRODUCT WORKER
# ============================================================

def product_worker(
    candidate: dict,
    query: str,
) -> dict | None:
    session = requests.Session()

    try:
        markdown = get_reader(
            session,
            candidate["url"],
            PRODUCT_TIMEOUT,
        )

        if not markdown:
            return None

        return parse_product_page(
            markdown,
            candidate["url"],
            candidate.get("search_text", ""),
            query,
        )

    except Exception:
        return None

    finally:
        session.close()


# ============================================================
# SEARCH
# ============================================================

def search(query: str) -> list[dict]:
    query = clean_text(query)

    if not query:
        return []

    # --------------------------------------------------------
    # PHASE 1
    # One direct Notino search page through Reader.
    # --------------------------------------------------------

    session = requests.Session()

    try:
        candidates = search_notino(
            session,
            query,
        )
    finally:
        session.close()

    if not candidates:
        return []

    # --------------------------------------------------------
    # PHASE 2
    # Product pages are independent.
    # --------------------------------------------------------

    candidates = candidates[:MAX_PRODUCT_REQUESTS]

    results: list[dict] = []

    with ThreadPoolExecutor(
        max_workers=min(5, len(candidates))
    ) as executor:

        future_map = {
            executor.submit(
                product_worker,
                candidate,
                query,
            ): candidate
            for candidate in candidates
        }

        for future in as_completed(future_map):
            try:
                result = future.result()

                if isinstance(result, dict):
                    results.append(result)

            except Exception:
                continue

    # --------------------------------------------------------
    # DEDUPLICATION
    # --------------------------------------------------------

    seen: set[tuple] = set()
    final: list[dict] = []

    for result in results:
        url = str(
            result.get("url")
            or ""
        ).rstrip("/")

        size = result.get("size_ml")

        key = (
            url,
            str(size or ""),
        )

        if key in seen:
            continue

        seen.add(key)
        final.append(result)

    # --------------------------------------------------------
    # SORT
    # --------------------------------------------------------

    def sort_key(item: dict):
        available = item.get("available")
        price = item.get("price_num")

        availability_rank = (
            0 if available is True
            else 1 if available is None
            else 2
        )

        price_rank = (
            float(price)
            if isinstance(price, (int, float))
            else 999999.0
        )

        return (
            availability_rank,
            price_rank,
        )

    final.sort(key=sort_key)

    return final


# ============================================================
# LOCAL TEST
# ============================================================

if __name__ == "__main__":
    tests = [
        "Liquid Brun",
        "Dior Sauvage",
    ]

    for test_query in tests:
        print()
        print("=" * 70)
        print("QUERY:", test_query)
        print("=" * 70)

        rows = search(test_query)

        print("RESULTS:", len(rows))

        for row in rows:
            print(row)
