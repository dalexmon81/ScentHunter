import json
import re
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from urllib.parse import unquote


BASE_URL = "https://www.parfum-zentrum.de"
SITEMAP_URL = BASE_URL + "/sitemap.xml"

SESSION = requests.Session()
HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}

IGNORED_MATCH_WORDS = {
    "eau", "de", "spray", "ml", "pour", "for", "the", "and",
}


def _tokens(text):
    return [
        x.lower()
        for x in re.findall(r"[A-Za-zÀ-ÿ0-9]+", unquote(str(text or "")))
        if len(x) > 1
    ]


def _concentration(text):
    value = unquote(str(text or ""))
    if re.search(r"\beau\s+de\s+toilette\b|\bedt\b", value, re.I):
        return "edt"
    if re.search(r"\beau\s+de\s+parfum\b|\bedp\b", value, re.I):
        return "edp"
    if re.search(r"\bextrait(?:\s+de\s+parfum)?\b", value, re.I):
        return "extrait"
    return ""


def _all_tokens_match(text, query):
    text_tokens = set(_tokens(text))
    query_tokens = {
        token for token in _tokens(query)
        if token not in IGNORED_MATCH_WORDS
    }

    if not query_tokens or not query_tokens.issubset(text_tokens):
        return False

    wanted = _concentration(query)
    return not wanted or _concentration(text) == wanted


def _xml_urls(xml_text):
    root = ET.fromstring(xml_text)
    return [
        el.text.strip()
        for el in root.iter()
        if el.tag.endswith("loc") and el.text
    ]


def _get_sitemap_urls():
    response = SESSION.get(SITEMAP_URL, headers=HEADERS, timeout=8)
    response.raise_for_status()
    urls = _xml_urls(response.text)
    response.close()

    child_maps = [
        url for url in urls
        if "sitemap" in url.lower()
        and url.lower().endswith((".xml", ".xml.gz"))
    ]

    if not child_maps:
        return urls

    output = []
    for sitemap in child_maps:
        try:
            child = SESSION.get(sitemap, headers=HEADERS, timeout=8)
            if child.status_code == 200:
                output.extend(_xml_urls(child.text))
            child.close()
        except requests.RequestException:
            continue

    return output


def _parse_number(value):
    raw = str(value or "").strip().replace("\xa0", " ")
    match = re.search(r"\d[\d.,]*", raw)
    if not match:
        return None

    number = match.group(0)

    if "," in number:
        if "." in number:
            number = number.replace(".", "").replace(",", ".")
        else:
            number = number.replace(",", ".")
    elif number.count(".") > 1:
        number = number.replace(".", "")
    elif number.count(".") == 1:
        left, right = number.split(".")
        if len(right) != 2:
            number = number.replace(".", "")

    try:
        result = float(number)
    except ValueError:
        return None

    return result if result > 0 else None


def _is_struck(node):
    if node.find_parent(["del", "s", "strike"]):
        return True

    current = node
    for _ in range(5):
        if current is None:
            break
        classes = " ".join(current.get("class", [])).lower()
        ident = str(current.get("id", "")).lower()
        marker = f"{classes} {ident}"
        if any(word in marker for word in (
            "old-price", "old_price", "regular-price", "list-price",
            "list_price", "strike", "strikethrough", "was-price",
            "compare-price", "crossed", "uvp",
        )):
            return True
        current = current.parent

    return False


def _is_non_purchase_price(node, text):
    low = text.lower()

    if any(word in low for word in (
        "grundpreis", "pro liter", "per liter", "€/l", "/l",
        "pro 100 ml", "per 100 ml",
    )):
        return True

    current = node
    for _ in range(6):
        if current is None:
            break
        marker = (
            " ".join(current.get("class", [])).lower()
            + " "
            + str(current.get("id", "")).lower()
        )
        if any(word in marker for word in (
            "coupon", "voucher", "gutschein", "rabattcode",
            "discount-code", "discount_code", "promo-code",
            "promo_code", "sale-code", "sale_code",
        )):
            return True
        current = current.parent

    return False


def _extract_visible_prices(soup):
    """
    Extracts prices visible to the customer and ranks them generically.

    Important rules:
    - crossed/list prices are never preferred over the active price;
    - Grundpreis / €/l is never a product price;
    - coupon/code prices are excluded;
    - price near the purchase/cart area is preferred;
    - no product/store-specific numbers are used.
    """
    candidates = []

    for node in soup.find_all(["span", "div", "p", "strong", "b", "ins"]):
        text = node.get_text(" ", strip=True)
        if not text or "€" not in text:
            continue
        if _is_non_purchase_price(node, text):
            continue
        if _is_struck(node):
            continue

        matches = re.findall(r"(?<![\d.,])\d{1,5}(?:[.,]\d{2})(?![\d.,])\s*€", text)
        for match in matches:
            value = _parse_number(match)
            if value is None:
                continue

            # Score context, not a specific product.
            score = 0
            current = node

            for distance in range(7):
                if current is None:
                    break

                context = current.get_text(" ", strip=True).lower()
                marker = (
                    " ".join(current.get("class", [])).lower()
                    + " "
                    + str(current.get("id", "")).lower()
                )

                if "in den warenkorb" in context or "add to cart" in context:
                    score += 100 - distance * 5
                if "inkl. mwst" in context or "inkl. mwst." in context:
                    score += 20
                if any(word in marker for word in (
                    "price", "preis", "product-price", "product_price",
                    "final-price", "final_price",
                )):
                    score += 15
                if any(word in marker for word in (
                    "coupon", "voucher", "gutschein", "rabatt",
                    "discount", "promo",
                )):
                    score -= 100

                current = current.parent

            candidates.append((score, value, node))

    if not candidates:
        return []

    # Active purchase prices beat higher/lower promotional artifacts.
    candidates.sort(key=lambda item: (item[0], -item[1]), reverse=True)
    return [(value, node) for _, value, node in candidates]


def _structured_prices(soup):
    """Fallback only: reads Product/Offer JSON-LD prices."""
    prices = []

    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        if not raw:
            continue

        try:
            data = json.loads(raw)
        except Exception:
            continue

        stack = [data]
        while stack:
            item = stack.pop(0)

            if isinstance(item, list):
                stack.extend(item)
                continue
            if not isinstance(item, dict):
                continue

            offers = item.get("offers")
            if isinstance(offers, dict):
                offers = [offers]

            if isinstance(offers, list):
                for offer in offers:
                    if not isinstance(offer, dict):
                        continue
                    value = _parse_number(offer.get("price"))
                    if value is not None:
                        prices.append(value)

            for child in item.values():
                if isinstance(child, (dict, list)):
                    stack.append(child)

    return prices


def _extract_price_from_html(html_text):
    soup = BeautifulSoup(html_text or "", "html.parser")

    # 1. Prefer the active visible purchase price.
    visible = _extract_visible_prices(soup)
    if visible:
        return f"{visible[0][0]:.2f}€"

    # 2. Structured fallback.
    # If JSON-LD contains a suspicious integer amount, do not blindly
    # multiply/divide it. It is safer to reject it than publish a false price.
    structured = _structured_prices(soup)
    for value in structured:
        if 0 < value < 1000:
            return f"{value:.2f}€"

    return ""


def _extract_product(url, query):
    try:
        response = SESSION.get(url, headers=HEADERS, timeout=8)
    except requests.RequestException:
        return None

    if response.status_code != 200:
        response.close()
        return None

    html_text = response.text
    response.close()

    soup = BeautifulSoup(html_text, "html.parser")
    h1 = soup.find("h1")
    if not h1:
        return None

    name = " ".join(h1.stripped_strings)

    if not _all_tokens_match(name, query):
        return None

    size_match = re.search(r"(?<!\d)(\d{1,4}(?:[.,]\d+)?)\s*ml\b", name, re.I)
    size_ml = None
    if size_match:
        try:
            size_ml = float(size_match.group(1).replace(",", "."))
        except ValueError:
            pass

    concentration = ""
    if re.search(r"\beau\s+de\s+toilette\b|\bedt\b", name, re.I):
        concentration = "Eau de Toilette"
    elif re.search(r"\beau\s+de\s+parfum\b|\bedp\b", name, re.I):
        concentration = "Eau de Parfum"
    elif re.search(r"\bextrait(?:\s+de\s+parfum)?\b", name, re.I):
        concentration = "Extrait de Parfum"

    text = soup.get_text(" ", strip=True).lower()
    if any(marker in text for marker in (
        "nicht lieferbar", "nicht vorrätig", "ausverkauft",
        "leider nicht lieferbar",
    )):
        return None

    price = _extract_price_from_html(html_text)
    if not price:
        return None

    return {
        "store": "ParfumZentrum",
        "name": name,
        "price": price,
        "url": url,
        "size_ml": size_ml,
        "concentration": concentration,
    }


def _candidate_score(url, query):
    query_tokens = [
        token for token in _tokens(query)
        if token not in IGNORED_MATCH_WORDS
    ]
    url_tokens = _tokens(url)

    score = sum(10 for token in query_tokens if token in url_tokens)

    if query_tokens and all(token in url_tokens for token in query_tokens):
        score += 30

    wanted = _concentration(query)
    if wanted == "edt" and ("toilette" in url_tokens or "edt" in url_tokens):
        score += 40
    elif wanted == "edp" and ("parfum" in url_tokens or "edp" in url_tokens):
        score += 40
    elif wanted == "extrait" and "extrait" in url_tokens:
        score += 40

    return score


def search(query):
    query = str(query or "").strip()
    if not query:
        return []

    try:
        urls = _get_sitemap_urls()
    except Exception as error:
        print("PARFUMZENTRUM SITEMAP ERROR:", error)
        return []

    candidates = [
        url for url in urls
        if re.search(r"_z\d+/?$", url)
        and _all_tokens_match(url, query)
    ]

    candidates.sort(
        key=lambda url: _candidate_score(url, query),
        reverse=True,
    )

    results = []
    seen = set()

    for url in candidates[:24]:
        try:
            item = _extract_product(url, query)
        except Exception as error:
            print("PARFUMZENTRUM PRODUCT ERROR:", repr(error))
            item = None

        if not item:
            continue

        key = (
            item["name"].lower(),
            item["price"],
            item["size_ml"],
        )

        if key not in seen:
            seen.add(key)
            results.append(item)

    SESSION.close()
    return results


