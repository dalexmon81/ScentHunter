import asyncio
import json
import os
import re
import shutil
import unicodedata
from urllib.parse import quote_plus, urljoin, urlparse, parse_qs

from bs4 import BeautifulSoup

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
except Exception:
    sync_playwright = None
    PlaywrightTimeoutError = Exception

STORE = "Notino"
BASE_URL = "https://www.notino.fr"
SEARCH_URL = f"{BASE_URL}/search.asp?exps={{query}}"
CATEGORY_URL = f"{BASE_URL}/parfums/"

BROWSER_TIMEOUT = int(os.getenv("NOTINO_BROWSER_TIMEOUT", "40000"))
MAX_DISCOVERY_PAGES = int(os.getenv("NOTINO_MAX_SEARCH_PAGES", "5"))
MAX_CANDIDATES = int(os.getenv("NOTINO_MAX_CANDIDATES", "120"))
MAX_VALIDATIONS = int(os.getenv("NOTINO_MAX_VALIDATIONS", "50"))
SCROLL_STEPS = int(os.getenv("NOTINO_SCROLL_STEPS", "8"))

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

IGNORED_QUERY_WORDS = {
    "eau", "de", "du", "des", "la", "le", "les", "parfum", "parfums",
    "perfume", "perfumes", "fragrance", "fragrances", "edp", "edt", "extrait",
    "spray", "for", "pour", "by", "homme", "hommes", "femme", "femmes", "men",
    "women", "male", "female", "unisex", "unisexe", "mixte", "ml", "cl",
}

NON_FRAGRANCE_TERMS = {
    "coffret", "coffrets", "kit", "set", "discovery box", "cadeau", "body mist",
    "brume", "gel douche", "lotion", "deodorant", "déodorant", "shampoo",
    "shampoing", "conditioner", "après-shampoing", "hair", "cheveux", "makeup",
    "maquillage", "skincare", "soin du visage", "savon", "after shave", "après-rasage",
}


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("&", " and ")
    text = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def same_host(url):
    try:
        host = urlparse(url).netloc.lower().split(":")[0]
        return host in {"notino.fr", "www.notino.fr"} or host.endswith(".notino.fr")
    except Exception:
        return False


def canonical_url(url, base=BASE_URL):
    if not url:
        return ""
    value = urljoin(base, url)
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not same_host(value):
        return ""
    return parsed._replace(query="", fragment="").geturl().rstrip("/")


def product_url(url):
    path = urlparse(url).path.rstrip("/")
    return bool(re.search(r"(?:^|/)p-\d+$", path, re.I))


def query_tokens(query):
    return [x for x in norm(query).split() if x not in IGNORED_QUERY_WORDS and len(x) >= 2]


def explicit_size(query):
    m = re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b", norm(query), re.I)
    if not m:
        return None
    value = float(m.group(1).replace(",", "."))
    return value * 10 if m.group(2).lower() == "cl" else value


def extract_size_ml(*texts):
    for value, unit in re.findall(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b", " ".join(str(x or "") for x in texts), re.I):
        number = float(value.replace(",", "."))
        number = number * 10 if unit.lower() == "cl" else number
        return int(number) if number.is_integer() else number
    return None


def extract_concentration(*texts):
    text = norm(" ".join(str(x or "") for x in texts))
    for label, pattern in (
        ("Extrait de Parfum", r"\bextrait(?: de)? parfum\b"),
        ("Eau de Parfum", r"\beau de parfum\b|\bedp\b"),
        ("Eau de Toilette", r"\beau de toilette\b|\bedt\b"),
        ("Eau de Cologne", r"\beau de cologne\b|\bedc\b"),
        ("Parfum", r"\bparfum\b"),
    ):
        if re.search(pattern, text):
            return label
    return None


def extract_gender(*texts):
    text = norm(" ".join(str(x or "") for x in texts))
    if re.search(r"\b(men|male|homme|hommes)\b", text):
        return "men"
    if re.search(r"\b(women|female|femme|femmes)\b", text):
        return "women"
    if re.search(r"\b(unisex|unisexe|mixte)\b", text):
        return "unisex"
    return "unknown"


def parse_json_ld(soup):
    found = []
    for script in soup.find_all("script", attrs={"type": re.compile(r"application/ld\+json", re.I)}):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw.strip())
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                typ = item.get("@type")
                types = typ if isinstance(typ, list) else [typ]
                if any(str(x).lower() == "product" for x in types):
                    found.append(item)
                graph = item.get("@graph")
                if isinstance(graph, list):
                    stack.extend(graph)
    return found


def first_text(soup, selectors):
    for selector in selectors:
        try:
            node = soup.select_one(selector)
        except Exception:
            node = None
        if not node:
            continue
        value = node.get("content") if node.name == "meta" else node.get_text(" ", strip=True)
        if clean(value):
            return clean(value)
    return ""


def parse_price(value):
    if value in (None, ""):
        return None
    text = clean(value).replace("€", "").replace("EUR", "")
    text = re.sub(r"[^0-9,.\-]", "", text)
    if not text:
        return None
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".") if text.rfind(",") > text.rfind(".") else text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        value = float(text)
        return round(value, 2) if 0 < value < 10000 else None
    except ValueError:
        return None


def extract_price(soup, json_product=None):
    values = []
    if isinstance(json_product, dict):
        offers = json_product.get("offers")
        offers = offers if isinstance(offers, list) else [offers]
        for offer in offers:
            if isinstance(offer, dict):
                values.extend([offer.get("price"), offer.get("lowPrice")])
    for selector in ('meta[itemprop="price"]', 'meta[property="product:price:amount"]', '[itemprop="price"]', '[data-price]'):
        for node in soup.select(selector):
            values.append(node.get("content") or node.get("data-price") or node.get_text(" ", strip=True))
    for value in values:
        price = parse_price(value)
        if price is not None:
            return price
    return None


def extract_availability(soup, json_product=None):
    if isinstance(json_product, dict):
        offers = json_product.get("offers")
        offers = offers if isinstance(offers, list) else [offers]
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            value = norm(offer.get("availability"))
            if "instock" in value:
                return "in_stock"
            if "outofstock" in value:
                return "out_of_stock"
    for selector in ('[itemprop="availability"]', '[data-testid*="availability" i]', '[data-testid*="stock" i]'):
        node = soup.select_one(selector)
        if node:
            value = norm(node.get("content") or node.get_text(" ", strip=True))
            if any(x in value for x in ("instock", "in stock", "en stock", "disponible")):
                return "in_stock"
            if any(x in value for x in ("outofstock", "out of stock", "rupture", "indisponible", "epuise", "epuisé")):
                return "out_of_stock"
    text = norm(soup.get_text(" ", strip=True))
    if re.search(r"\ben stock\b|\bdisponible\b|\bavailable\b", text):
        return "in_stock"
    if re.search(r"\bout of stock\b|\brupture de stock\b|\bindisponible\b|\bepuise\b|\bepuisé\b", text):
        return "out_of_stock"
    return "unknown"


def product_identity(soup, json_product):
    name = clean(json_product.get("name")) if isinstance(json_product, dict) else ""
    if not name:
        name = first_text(soup, ["h1", '[itemprop="name"]', 'meta[property="og:title"]', 'meta[name="twitter:title"]', "title"])
    brand = ""
    if isinstance(json_product, dict):
        brand = json_product.get("brand")
        if isinstance(brand, dict):
            brand = brand.get("name")
        brand = clean(brand)
    if not brand:
        brand = first_text(soup, ['[itemprop="brand"]', 'meta[property="product:brand"]'])
    return name, brand


def is_fragrance(name, page_text, concentration):
    identity = norm(f"{name} {page_text}")
    if any(norm(term) in norm(name) for term in NON_FRAGRANCE_TERMS):
        return False
    if concentration:
        return True
    return bool(re.search(r"\b(eau de parfum|eau de toilette|eau de cologne|extrait de parfum|parfum|perfume|fragrance)\b", identity))


def query_matches(name, brand, query, size_ml):
    identity = norm(f"{brand} {name}")
    wanted = query_tokens(query)
    if not wanted:
        return True
    if not all(token in identity for token in wanted):
        return False
    requested = explicit_size(query)
    if requested is not None:
        if size_ml is None or abs(float(size_ml) - float(requested)) > 0.01:
            return False
    return True


def candidate_score(text, url, query):
    identity = norm(text)
    score = 0
    for token in query_tokens(query):
        if token in identity.split():
            score += 4
        elif token in identity:
            score += 1
    if product_url(url):
        score += 2
    return score


def extract_card_context(anchor):
    """Return bounded text from the smallest likely product-card ancestor."""
    anchor_text=clean(anchor.get_text(" ", strip=True))
    if not anchor_text:
        return anchor_text
    best=anchor_text
    node=anchor.parent
    for _ in range(6):
        if not node or not getattr(node, "get_text", None):
            break
        candidate=clean(node.get_text(" ", strip=True))
        if len(candidate) <= 3000 and anchor_text in candidate:
            classes=" ".join(node.get("class", []) or [])
            attrs=" ".join(
                clean(node.get(k))
                for k in ("data-testid", "data-test", "data-product-id", "aria-label")
                if node.get(k)
            )
            marker=norm(f"{classes} {attrs}")
            has_offer=re.search(r"\d+(?:[.,]\d{1,2})?\s*€", candidate) is not None
            has_stock=re.search(
                r"\b(en stock|rupture de stock|en rupture de stock|disponible|indisponible|epuise|épuisé|out of stock|in stock|available)\b",
                norm(candidate),
            ) is not None
            if has_offer or has_stock or any(
                token in marker for token in ("product", "card", "item", "listing", "result")
            ):
                best=candidate
        node=node.parent
    return best

def extract_product_candidates(html, page_url, query=""):
    soup = BeautifulSoup(html, "html.parser")
    output = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        url = canonical_url(anchor.get("href"), page_url)
        if not url or not product_url(url) or url in seen:
            continue

        pieces = [anchor.get("title"), anchor.get("aria-label"), anchor.get_text(" ", strip=True)]
        image = anchor.find("img")
        image_url = ""
        if image:
            pieces.extend([image.get("alt"), image.get("title")])
            image_url = clean(
                image.get("src")
                or image.get("data-src")
                or image.get("data-lazy-src")
                or image.get("data-original")
                or ""
            )
            if image_url:
                image_url = canonical_url(image_url, page_url) or image_url

        text = clean(" ".join(x for x in pieces if x))
        card_text = extract_card_context(anchor)
        seen.add(url)
        output.append({
            "url": url,
            "text": text,
            "card_text": card_text,
            "score": candidate_score(text, url, query),
            "image": image_url,
        })
    output.sort(key=lambda x: x["score"], reverse=True)
    return output[:MAX_CANDIDATES]


def extract_card_price(text):
    matches = re.findall(r"(\d+(?:[.,]\d{1,2})?)\s*€", str(text or ""))
    for value in matches:
        price = parse_price(value)
        if price is not None:
            return price
    return None


def extract_card_availability(text):
    value = norm(text)
    if re.search(r"\b(en rupture de stock|rupture de stock|indisponible|epuise|epuise)\b", value):
        return "out_of_stock"
    if re.search(r"\b(en stock|disponible|available|in stock)\b", value):
        return "in_stock"
    return "unknown"


def extract_brand_from_product_url(url):
    parts = [p for p in urlparse(url).path.split("/") if p]
    if not parts or parts[-1].lower().startswith("p-"):
        parts = parts[:-1]
    if not parts:
        return ""
    raw = parts[0].replace("-", " ")
    return clean(raw.title())


def parse_search_candidate(candidate, query):
    """Build a product directly from Notino's search-card data.

    This is a generic fallback for Notino's product-page Cloudflare challenge.
    It never relies on a product name, brand, URL, seed, or hard-coded product.
    """
    url = canonical_url(candidate.get("url"))
    text = clean(candidate.get("text"))
    card_text = clean(candidate.get("card_text")) or text
    if not url or not product_url(url) or not text:
        return None

    brand = extract_brand_from_product_url(url)
    name = text
    price = extract_card_price(card_text) or extract_card_price(text)
    availability = extract_card_availability(card_text)
    size_ml = extract_size_ml(text, card_text)
    concentration = extract_concentration(text, card_text)
    gender = extract_gender(text, card_text)

    if not is_fragrance(name, text, concentration):
        return None
    if not query_matches(name, brand, query, size_ml):
        return None

    match = re.search(r"/p-(\d+)$", urlparse(url).path, re.I)
    product_id = match.group(1) if match else None
    image = clean(candidate.get("image")) or None

    return {
        "store": STORE,
        "source": {
            "source_name": name,
            "source_brand": brand or None,
            "url": url,
            "image": image,
        },
        "identity": {
            "gtin": None,
            "mpn": None,
            "sku": None,
            "store_product_id": product_id,
            "store_variant_id": None,
        },
        "attributes": {
            "size_ml": {"value": size_ml, "source": "search_page"},
            "concentration": {"value": concentration, "source": "search_page"},
            "gender": {"value": gender, "source": "search_page"},
            "packaging_type": {"value": "product", "source": "search_page"},
        },
        "offer": {
            "price": price,
            "currency": "EUR",
            "availability": availability,
        },
        "provenance": {
            "source_page": url,
            "name_source": "search_page",
            "brand_source": "product_url",
            "price_source": "search_page",
            "product_source": "search_page",
        },
        "raw_data": {
            "name": name,
            "brand": brand,
            "size_ml": size_ml,
            "concentration": concentration,
            "gender": gender,
        },
        "name": name,
        "price": f"{price:.2f} €" if price is not None else "",
        "url": url,
        "image": image or "",
        "available": availability == "in_stock",
    }


def dismiss_consent(page):
    selectors = [
        'button:has-text("Accepter")', 'button:has-text("Tout accepter")',
        'button:has-text("J’accepte")', 'button:has-text("J\'accepte")',
        '[id*="accept" i]', '[data-testid*="accept" i]',
    ]
    for selector in selectors:
        try:
            loc = page.locator(selector).first
            if loc.count() and loc.is_visible():
                loc.click(timeout=1500)
                page.wait_for_timeout(300)
                return
        except Exception:
            continue


def scroll_for_products(page):
    last_height = 0
    stable = 0
    for _ in range(max(1, SCROLL_STEPS)):
        try:
            height = page.evaluate("document.body ? document.body.scrollHeight : 0")
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(700)
            new_height = page.evaluate("document.body ? document.body.scrollHeight : 0")
        except Exception:
            break
        if new_height == last_height == height:
            stable += 1
            if stable >= 2:
                break
        else:
            stable = 0
        last_height = new_height


def next_page(page):
    try:
        links = page.locator("a[href]").evaluate_all("""els => els.map(a => ({href:a.href,text:(a.innerText||a.getAttribute('aria-label')||'').trim(),rel:a.rel||''}))""")
    except Exception:
        return None
    current = page.url
    try:
        current_number = int(parse_qs(urlparse(current).query).get("page", ["1"])[0])
    except Exception:
        current_number = 1
    candidates = []
    for item in links:
        href = item.get("href") or ""
        if not same_host(href):
            continue
        text = norm(item.get("text"))
        rel = norm(item.get("rel"))
        if "next" in rel or text in {"suivant", "suivante", "next"}:
            candidates.append(href)
            continue
        try:
            p = int(parse_qs(urlparse(href).query).get("page", [""])[0])
            if p == current_number + 1:
                candidates.append(href)
        except Exception:
            pass
    return candidates[0] if candidates else None



def launch_browser(playwright):
    kwargs = {
        "headless": True,
        "args": ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
    }
    executable_path = os.getenv("PLAYWRIGHT_EXECUTABLE_PATH")
    if not executable_path:
        executable_path = (
            shutil.which("chromium")
            or shutil.which("chromium-browser")
            or shutil.which("google-chrome")
        )
    if executable_path:
        kwargs["executable_path"] = executable_path
    return playwright.chromium.launch(**kwargs)

def browser_discover(query):
    if sync_playwright is None:
        return []
    candidates = []
    seen = set()
    try:
        with sync_playwright() as pw:
            browser = launch_browser(pw)
            context = browser.new_context(user_agent=USER_AGENT, locale="fr-FR", viewport={"width":1440,"height":1000}, extra_http_headers={"Accept-Language":"fr-FR,fr;q=0.9,en;q=0.7"})
            page = context.new_page()
            urls = [SEARCH_URL.format(query=quote_plus(clean(query)))]
            visited_pages = set()
            for start in urls:
                page.goto(start, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT)
                dismiss_consent(page)
                for _ in range(MAX_DISCOVERY_PAGES):
                    if page.url in visited_pages:
                        break
                    visited_pages.add(page.url)
                    try:
                        page.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        pass
                    page.wait_for_timeout(1200)
                    scroll_for_products(page)
                    html = page.content()
                    for item in extract_product_candidates(html, page.url, query):
                        if item["url"] not in seen:
                            seen.add(item["url"])
                            candidates.append(item)
                    nxt = next_page(page)
                    if not nxt or nxt in visited_pages:
                        break
                    page.goto(nxt, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT)
                    dismiss_consent(page)

            # Generic site-wide fallback: if the search endpoint rendered no product
            # links, discover products from Notino's perfume catalogue and rank the
            # resulting candidates against the requested query. This is not tied to
            # any individual product or brand.
            if not candidates:
                page.goto(CATEGORY_URL, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT)
                dismiss_consent(page)
                try:
                    page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                page.wait_for_timeout(1200)
                scroll_for_products(page)
                html = page.content()
                for item in extract_product_candidates(html, page.url, query):
                    if item["url"] not in seen:
                        seen.add(item["url"])
                        candidates.append(item)

            context.close()
            browser.close()
    except Exception:
        return []
    candidates.sort(key=lambda x: x.get("score", 0), reverse=True)
    return candidates[:MAX_CANDIDATES]


def parse_product_page(html, response_url, query):
    soup = BeautifulSoup(html, "html.parser")
    products = parse_json_ld(soup)
    json_product = products[0] if products else None
    name, brand = product_identity(soup, json_product)
    if not name:
        return None
    text = soup.get_text(" ", strip=True)
    size_ml = extract_size_ml(name, text)
    concentration = extract_concentration(name, text)
    gender = extract_gender(name, text)
    if not is_fragrance(name, text, concentration):
        return None
    url = canonical_url(response_url)
    if not url or not product_url(url):
        return None
    if not query_matches(name, brand, query, size_ml):
        return None
    price = extract_price(soup, json_product)
    availability = extract_availability(soup, json_product)
    image = ""
    if isinstance(json_product, dict):
        image = json_product.get("image") or ""
        if isinstance(image, list):
            image = image[0] if image else ""
    image = clean(image) or first_text(soup, ['meta[property="og:image"]', 'meta[name="twitter:image"]'])
    match = re.search(r"/p-(\d+)$", urlparse(url).path, re.I)
    product_id = match.group(1) if match else None
    return {
        "store": STORE,
        "source": {"source_name": name, "source_brand": brand or None, "url": url, "image": image or None},
        "identity": {"gtin": None, "mpn": None, "sku": None, "store_product_id": product_id, "store_variant_id": None},
        "attributes": {
            "size_ml": {"value": size_ml, "source": "product_page"},
            "concentration": {"value": concentration, "source": "product_page"},
            "gender": {"value": gender, "source": "product_page"},
            "packaging_type": {"value": "product", "source": "product_page"},
        },
        "offer": {"price": price, "currency": "EUR", "availability": availability},
        "provenance": {"source_page": url, "name_source": "product_page", "brand_source": "product_page", "price_source": "product_page", "product_source": "product_page"},
        "raw_data": {"name": name, "brand": brand, "size_ml": size_ml, "concentration": concentration, "gender": gender},
        "name": name,
        "price": f"{price:.2f} €" if price is not None else "",
        "url": url,
        "image": image,
        "available": availability == "in_stock",
    }


def validate_candidates(candidates, query):
    if sync_playwright is None:
        return []
    results = []
    seen = set()
    try:
        with sync_playwright() as pw:
            browser = launch_browser(pw)
            context = browser.new_context(user_agent=USER_AGENT, locale="fr-FR", viewport={"width":1440,"height":1000}, extra_http_headers={"Accept-Language":"fr-FR,fr;q=0.9,en;q=0.7"})
            page = context.new_page()
            for candidate in candidates[:MAX_VALIDATIONS]:
                url = candidate.get("url")
                if not url or url in seen:
                    continue
                seen.add(url)
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT)
                    dismiss_consent(page)
                    try:
                        page.wait_for_load_state("networkidle", timeout=8000)
                    except Exception:
                        pass
                    page.wait_for_timeout(700)
                    product = parse_product_page(page.content(), page.url, query)
                except Exception:
                    continue
                if product:
                    results.append(product)
            context.close()
            browser.close()
    except Exception:
        return []
    return results


def search(query):
    query = clean(query)
    if not query:
        return []

    candidates = browser_discover(query)
    if not candidates:
        return []

    # Notino currently protects direct product navigation with a Cloudflare
    # challenge. The search page itself already exposes the product card data,
    # so use that data as the primary generic result path.
    results = []
    seen = set()
    for candidate in candidates:
        product = parse_search_candidate(candidate, query)
        if not product:
            continue
        url = product.get("url")
        if url in seen:
            continue
        seen.add(url)
        results.append(product)

    # Keep direct validation only as a secondary enrichment path for any
    # candidate whose search card could not be parsed completely. This remains
    # generic and does not privilege individual products.
    if not results:
        return validate_candidates(candidates, query)

    return results


def scrape(query):
    return search(query)



def _diagnose_parse_failure(html, response_url, query):
    """Generic diagnostic aligned with the scraper's real parser functions."""
    soup = BeautifulSoup(html, "html.parser")
    json_products = parse_json_ld(soup)
    json_product = json_products[0] if json_products else None
    name, brand = product_identity(soup, json_product)
    text = soup.get_text(" ", strip=True)
    size_ml = extract_size_ml(name, text)
    concentration = extract_concentration(name, text)
    gender = extract_gender(name, text)
    canonical = canonical_url(response_url)

    fragrance_ok = bool(name and is_fragrance(name, text, concentration))
    url_ok = bool(canonical and product_url(canonical))
    query_ok = bool(
        name and query_matches(name, brand, query, size_ml)
    )

    if not name:
        reason = "name_not_found"
    elif not fragrance_ok:
        reason = "not_recognized_as_fragrance"
    elif not url_ok:
        reason = "product_url_rejected"
    elif not query_ok:
        reason = "query_identity_or_size_mismatch"
    else:
        reason = None

    parsed = parse_product_page(html, response_url, query)

    return {
        "name": name or None,
        "brand": brand or None,
        "json_ld_product": bool(json_product),
        "json_ld_products_found": len(json_products),
        "concentration": concentration or None,
        "gender": gender,
        "size_ml": size_ml,
        "url": canonical or response_url,
        "fragrance_check": fragrance_ok,
        "product_url_check": url_ok,
        "query_match_check": query_ok,
        "parser_result": bool(parsed),
        "valid": parsed is not None,
        "rejection_reason": None if parsed is not None else reason,
    }





def diagnose(query):
    """Generic diagnostic of Notino search discovery and direct product-page responses."""
    query=clean(query)
    if not query:
        return {"status":"error","query":"","errors":[{"stage":"input","type":"empty_query"}]}

    report={
        "status":"started",
        "query":query,
        "search_url":SEARCH_URL.format(query=quote_plus(query)),
        "discovery":{"raw_links":0,"product_candidates":0,"unique_candidates":0},
        "product_pages":[],
        "errors":[],
    }

    if sync_playwright is None:
        report["status"]="error"
        report["errors"].append({"stage":"startup","type":"playwright_unavailable"})
        return report

    seen=set()
    discovered=[]

    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(
                headless=True,
                args=["--no-sandbox","--disable-dev-shm-usage","--disable-gpu"],
            )
            context=browser.new_context(
                user_agent=USER_AGENT,
                locale="fr-FR",
                viewport={"width":1440,"height":1100},
            )
            page=context.new_page()
            document_responses={}

            def capture(response):
                try:
                    if response.request.resource_type=="document":
                        document_responses[response.url]={
                            "status":response.status,
                            "status_text":response.status_text,
                            "url":response.url,
                        }
                except Exception:
                    pass

            page.on("response",capture)

            try:
                try:
                    page.goto(report["search_url"],wait_until="domcontentloaded",timeout=BROWSER_TIMEOUT)
                    page.wait_for_timeout(1200)
                    dismiss_consent(page)
                    scroll_for_products(page)
                    page.wait_for_timeout(500)
                except Exception as exc:
                    report["status"]="completed_with_errors"
                    report["errors"].append({"stage":"search_page","type":type(exc).__name__,"message":str(exc)})
                    return report

                html=page.content()
                soup=BeautifulSoup(html,"html.parser")
                candidates=extract_product_candidates(html,page.url,query)
                report["discovery"]["raw_links"]=len(soup.find_all("a",href=True))
                report["discovery"]["product_candidates"]=len(candidates)

                for candidate in candidates:
                    url=candidate["url"]
                    if url not in seen:
                        seen.add(url)
                        discovered.append({
                            "url":url,
                            "anchor_text":candidate.get("text",""),
                            "score":candidate.get("score",0),
                        })

                report["discovery"]["unique_candidates"]=len(discovered)

                # Inspect every discovered product URL. No fragrance parser is
                # used here: this diagnostic only reports what Notino returns.
                for candidate in discovered:
                    item=dict(candidate)
                    target=candidate["url"]

                    try:
                        page.goto(target,wait_until="domcontentloaded",timeout=BROWSER_TIMEOUT)
                        page.wait_for_timeout(1000)

                        final_url=page.url
                        product_html=page.content()
                        product_soup=BeautifulSoup(product_html,"html.parser")

                        h1=product_soup.find("h1")
                        h1_text=h1.get_text(" ",strip=True) if h1 else None
                        scripts=product_soup.find_all("script",type="application/ld+json")

                        json_types=[]
                        product_names=[]
                        for script in scripts:
                            try:
                                data=json.loads(script.string or script.get_text())
                            except Exception:
                                continue
                            nodes=data if isinstance(data,list) else [data]
                            for node in nodes:
                                if isinstance(node,dict):
                                    if "@type" in node:
                                        json_types.append(node.get("@type"))
                                    if node.get("@type")=="Product":
                                        product_names.append(node.get("name"))

                        low=product_html.lower()
                        markers=[
                            x for x in (
                                "just a moment",
                                "cf-chl-",
                                "challenge-platform",
                                "cloudflare",
                                "verify you are human",
                                "checking your browser",
                            ) if x in low
                        ]

                        response_info=document_responses.get(final_url) or document_responses.get(target)

                        item["page_diagnostic"]={
                            "requested_url":target,
                            "final_url":final_url,
                            "redirected":final_url!=target,
                            "response":response_info,
                            "http_status":response_info.get("status") if response_info else None,
                            "title":page.title(),
                            "h1":h1_text,
                            "html_length":len(product_html),
                            "html_start":product_html[:500],
                            "json_ld_script_count":len(scripts),
                            "json_ld_types":json_types[:20],
                            "json_ld_product_names":product_names[:20],
                            "challenge_markers":markers,
                            "contains_fragrance_wording":any(
                                x in low for x in (
                                    "eau de parfum",
                                    "eau de toilette",
                                    "extrait de parfum",
                                    "parfum",
                                )
                            ),
                            "text_sample":product_soup.get_text(" ",strip=True)[:1200],
                        }

                    except Exception as exc:
                        item["page_diagnostic"]={
                            "requested_url":target,
                            "error":{"type":type(exc).__name__,"message":str(exc)}
                        }

                    report["product_pages"].append(item)

            finally:
                context.close()
                browser.close()

    except Exception as exc:
        report["status"]="completed_with_errors"
        report["errors"].append({"stage":"runtime","type":type(exc).__name__,"message":str(exc)})
        return report

    report["status"]="ok" if not report["errors"] else "completed_with_errors"
    return report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    args = parser.parse_args()
    print(json.dumps(diagnose(args.query), ensure_ascii=False, indent=2))
