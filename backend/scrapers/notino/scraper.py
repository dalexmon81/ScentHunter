import json
import os
import re
import shutil
import unicodedata
from urllib.parse import quote_plus, urlparse, parse_qs, urljoin

from bs4 import BeautifulSoup

try:
    from playwright.sync_api import sync_playwright
except Exception:
    sync_playwright = None

STORE = "Notino"
BASE_URL = "https://www.notino.fr"
SEARCH_URL = f"{BASE_URL}/search.asp?exps={{query}}"

BROWSER_TIMEOUT = int(os.getenv("NOTINO_BROWSER_TIMEOUT", "40000"))
MAX_DISCOVERY_PAGES = int(os.getenv("NOTINO_MAX_SEARCH_PAGES", "8"))
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
    "maquillage", "skincare", "soin du visage", "savon", "after shave",
    "après-rasage",
}

NON_PERFUME_MARKERS = {
    "gift set", "set regalo", "set", "discovery set", "fragrance set",
    "perfume set", "parfum set", "coffret", "bundle", "pack", "travel set",
    "kit", "duo", "trio", "mystery box", "tester", "testeur", "sample",
    "shampoo", "shower gel", "body wash", "body lotion", "body cream",
    "body milk", "deodorant", "deo spray", "aftershave", "after shave",
    "body spray", "hair mist", "makeup", "cosmetics", "skincare",
}

def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()

def norm(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("&", " and ")
    text = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()

def _product_norm(value):
    return norm(value)

def _clean_product_name(value):
    text = clean(value)
    text = re.sub(r"\b\d{1,4}(?:[.,]\d{1,2})?\s*€", " ", text, flags=re.I)
    text = re.sub(r"\b(?:jusqu['’]?à|save|économie|reduction|réduction)\s*\d{1,3}%?\b", " ", text, flags=re.I)
    return clean(text)

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
    return bool(re.search(r"(?:^|/)p-\d+$", urlparse(url).path.rstrip("/"), re.I))

def query_tokens(query):
    return [x for x in norm(query).split() if x not in IGNORED_QUERY_WORDS and len(x) >= 2]

def explicit_size(query):
    m = re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b", norm(query), re.I)
    if not m:
        return None
    value = float(m.group(1).replace(",", "."))
    return value * 10 if m.group(2).lower() == "cl" else value

def extract_size_ml(*texts):
    for value, unit in re.findall(
        r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b",
        " ".join(str(x or "") for x in texts),
        re.I,
    ):
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

def _has_non_perfume_marker(value):
    tokens = set(_product_norm(value).split())
    for marker in NON_PERFUME_MARKERS:
        mt = set(_product_norm(marker).split())
        if mt and mt.issubset(tokens):
            return True
    return False

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
            if not isinstance(item, dict):
                continue
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
    for selector in (
        'meta[itemprop="price"]',
        'meta[property="product:price:amount"]',
        '[itemprop="price"]',
        "[data-price]",
    ):
        for node in soup.select(selector):
            values.append(node.get("content") or node.get("data-price") or node.get_text(" ", strip=True))
    for value in values:
        price = parse_price(value)
        if price is not None:
            return price
    return None

def extract_availability(soup, json_product=None):
    positives = ("instock", "in stock", "en stock", "disponible", "available")
    negatives = ("outofstock", "out of stock", "rupture", "indisponible", "epuise", "épuisé")
    if isinstance(json_product, dict):
        offers = json_product.get("offers")
        offers = offers if isinstance(offers, list) else [offers]
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            value = norm(offer.get("availability"))
            if any(x in value for x in positives):
                return "in_stock"
            if any(x in value for x in negatives):
                return "out_of_stock"
    for selector in ('[itemprop="availability"]', '[data-testid*="availability" i]', '[data-testid*="stock" i]'):
        for node in soup.select(selector):
            value = norm(node.get("content") or node.get_text(" ", strip=True))
            if any(x in value for x in positives):
                return "in_stock"
            if any(x in value for x in negatives):
                return "out_of_stock"
    text = norm(soup.get_text(" ", strip=True))
    if re.search(r"\ben stock\b|\bdisponible\b|\bavailable\b|\bin stock\b", text):
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
    clean_name = _clean_product_name(name)
    if not clean_name or _has_non_perfume_marker(clean_name):
        return False
    identity = _product_norm(f"{brand} {clean_name}")
    wanted = query_tokens(query)
    if wanted and not all(token in identity.split() for token in wanted):
        return False
    requested = explicit_size(query)
    if requested is not None and (size_ml is None or abs(float(size_ml) - float(requested)) > 0.01):
        return False
    return True

def candidate_score(text, url, query):
    identity = norm(text)
    score = sum(4 if token in identity.split() else 1 for token in query_tokens(query) if token in identity)
    if product_url(url):
        score += 2
    return score

def extract_card_context(anchor):
    anchor_text = clean(anchor.get_text(" ", strip=True))
    if not anchor_text:
        return ""
    node = anchor.parent
    best = anchor_text
    for _ in range(8):
        if not node or not getattr(node, "get_text", None):
            break
        candidate = clean(node.get_text(" ", strip=True))
        classes = " ".join(node.get("class", []) or [])
        attrs = " ".join(clean(node.get(k)) for k in ("data-testid", "data-test", "data-product-id", "aria-label") if node.get(k))
        marker = norm(f"{classes} {attrs}")
        has_offer = re.search(r"\d+(?:[.,]\d{1,2})?\s*€", candidate) is not None
        has_stock = re.search(r"\b(en stock|rupture de stock|en rupture de stock|disponible|indisponible|epuise|épuisé|out of stock|in stock|available)\b", norm(candidate)) is not None
        if len(candidate) <= 1200 and anchor_text in candidate and (has_offer or has_stock or any(token in marker for token in ("product", "card", "item", "listing", "result"))):
            return candidate
        node = node.parent
    return best

def extract_product_candidates(html, page_url, query=""):
    soup = BeautifulSoup(html, "html.parser")
    output, seen = [], set()
    for anchor in soup.find_all("a", href=True):
        url = canonical_url(anchor.get("href"), page_url)
        if not url or not product_url(url) or url in seen:
            continue
        image = anchor.find("img")
        image_url = ""
        if image:
            image_url = clean(image.get("src") or image.get("data-src") or image.get("data-lazy-src") or image.get("data-original") or "")
            if image_url:
                image_url = urljoin(page_url, image_url)
        pieces = [anchor.get("title"), anchor.get("aria-label"), anchor.get_text(" ", strip=True)]
        if image:
            pieces.extend([image.get("alt"), image.get("title")])
        text = clean(" ".join(x for x in pieces if x))
        card_text = extract_card_context(anchor)
        seen.add(url)
        output.append({
            "url": url,
            "text": text,
            "anchor_text": clean(anchor.get_text(" ", strip=True)),
            "title": clean(anchor.get("title")),
            "aria_label": clean(anchor.get("aria-label")),
            "card_text": card_text,
            "score": candidate_score(text, url, query),
            "image": image_url,
        })
    output.sort(key=lambda x: x["score"], reverse=True)
    return output[:MAX_CANDIDATES]

def extract_card_price(text):
    text = clean(text)
    if not text:
        return None
    matches = list(re.finditer(r"(\d+(?:[.,]\d{1,2})?)\s*€", text))
    values = []
    for match in matches:
        tail = text[match.end():match.end() + 24].lower()
        if re.match(r"\s*(?:/|par|pour)\s*\d+\s*ml\b", tail):
            continue
        value = parse_price(match.group(1))
        if value is not None:
            values.append(value)
    return min(values) if values else None

def extract_card_availability(text):
    value = norm(text)
    negative = re.search(r"\b(en rupture de stock|rupture de stock|indisponible|epuise|épuisé|out of stock)\b", value)
    positive = re.search(r"\b(en stock|disponible|available|in stock)\b", value)
    if positive:
        return "in_stock"
    if negative:
        return "out_of_stock"
    return "unknown"

def extract_brand_from_product_url(url):
    parts = [p for p in urlparse(url).path.split("/") if p]
    if parts and parts[-1].lower().startswith("p-"):
        parts = parts[:-1]
    return clean(parts[0].replace("-", " ").title()) if parts else ""

def parse_search_candidate(candidate, query):
    url = canonical_url(candidate.get("url"))
    text = clean(candidate.get("text"))
    card_text = clean(candidate.get("card_text")) or text
    if not url or not product_url(url) or not text:
        return None
    brand = extract_brand_from_product_url(url)
    names = [candidate.get("title"), candidate.get("aria_label"), candidate.get("anchor_text"), text]
    name = next(
        (
            _clean_product_name(x)
            for x in names
            if _clean_product_name(x)
            and query_matches(_clean_product_name(x), brand, query, extract_size_ml(x, card_text))
        ),
        "",
    )
    if not name or _has_non_perfume_marker(name):
        return None
    size_ml = extract_size_ml(name, text, card_text)
    concentration = extract_concentration(name, text, card_text)
    if not is_fragrance(name, text, concentration):
        return None
    if not query_matches(name, brand, query, size_ml):
        return None
    price = extract_card_price(card_text) or extract_card_price(text)
    availability = extract_card_availability(card_text)
    match = re.search(r"/p-(\d+)$", urlparse(url).path, re.I)
    product_id = match.group(1) if match else None
    image = clean(candidate.get("image"))
    return {
        "store": STORE,
        "source": {"source_name": name, "source_brand": brand or None, "url": url, "image": image or None},
        "identity": {"gtin": None, "mpn": None, "sku": None, "store_product_id": product_id, "store_variant_id": None},
        "attributes": {
            "size_ml": {"value": size_ml, "source": "search_page"},
            "concentration": {"value": concentration, "source": "search_page"},
            "gender": {"value": extract_gender(name, text, card_text), "source": "search_page"},
            "packaging_type": {"value": "product", "source": "search_page"},
        },
        "offer": {"price": price, "currency": "EUR", "availability": availability},
        "provenance": {"source_page": url, "name_source": "search_page", "brand_source": "product_url", "price_source": "search_page", "product_source": "search_page"},
        "raw_data": {"name": name, "brand": brand, "size_ml": size_ml, "concentration": concentration},
        "name": name,
        "price": f"{price:.2f} €" if price is not None else "",
        "url": url,
        "image": image,
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
            pass

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
    for item in links:
        href = item.get("href") or ""
        if not same_host(href):
            continue
        text = norm(item.get("text"))
        rel = norm(item.get("rel"))
        if "next" in rel or text in {"suivant", "suivante", "next"}:
            return href
        try:
            p = int(parse_qs(urlparse(href).query).get("page", [""])[0])
            if p == current_number + 1:
                return href
        except Exception:
            pass
    return None

def launch_browser(playwright):
    kwargs = {"headless": True, "args": ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]}
    executable_path = os.getenv("PLAYWRIGHT_EXECUTABLE_PATH") or (
        shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
    )
    if executable_path:
        kwargs["executable_path"] = executable_path
    return playwright.chromium.launch(**kwargs)

def browser_discover(query):
    if sync_playwright is None:
        return []
    candidates, seen = [], set()
    try:
        with sync_playwright() as pw:
            browser = launch_browser(pw)
            context = browser.new_context(
                user_agent=USER_AGENT,
                locale="fr-FR",
                viewport={"width": 1440, "height": 1000},
                extra_http_headers={"Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7"},
            )
            page = context.new_page()
            raw_query = clean(query)
            variants = [raw_query]
            tokens = query_tokens(raw_query)
            for token in tokens:
                if token not in variants:
                    variants.append(token)
            compact = re.sub(r"(?<=\d)\s+(?=[a-z])|(?<=[a-z])\s+(?=\d)", "", norm(raw_query))
            if compact and compact not in variants:
                variants.append(compact)
            visited = set()
            for start in [SEARCH_URL.format(query=quote_plus(x)) for x in variants[:4]]:
                page.goto(start, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT)
                dismiss_consent(page)
                for _ in range(MAX_DISCOVERY_PAGES):
                    if page.url in visited:
                        break
                    visited.add(page.url)
                    try:
                        page.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        pass
                    page.wait_for_timeout(1000)
                    scroll_for_products(page)
                    for item in extract_product_candidates(page.content(), page.url, query):
                        if item["url"] not in seen:
                            seen.add(item["url"])
                            candidates.append(item)
                    nxt = next_page(page)
                    if not nxt or nxt in visited:
                        break
                    page.goto(nxt, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT)
                    dismiss_consent(page)
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
    if not is_fragrance(name, text, concentration):
        return None
    url = canonical_url(response_url)
    if not url or not product_url(url) or not query_matches(name, brand, query, size_ml):
        return None
    price = extract_price(soup, json_product)
    availability = extract_availability(soup, json_product)
    image = ""
    if isinstance(json_product, dict):
        image = json_product.get("image") or ""
        if isinstance(image, list):
            image = image[0] if image else ""
    image = clean(image) or first_text(soup, ['meta[property="og:image"]', 'meta[name="twitter:image"]'])
    product_id = re.search(r"/p-(\d+)$", urlparse(url).path, re.I)
    product_id = product_id.group(1) if product_id else None
    return {
        "store": STORE,
        "source": {"source_name": name, "source_brand": brand or None, "url": url, "image": image or None},
        "identity": {"gtin": None, "mpn": None, "sku": None, "store_product_id": product_id, "store_variant_id": None},
        "attributes": {
            "size_ml": {"value": size_ml, "source": "product_page"},
            "concentration": {"value": concentration, "source": "product_page"},
            "gender": {"value": extract_gender(name, text), "source": "product_page"},
            "packaging_type": {"value": "product", "source": "product_page"},
        },
        "offer": {"price": price, "currency": "EUR", "availability": availability},
        "provenance": {"source_page": url, "name_source": "product_page", "brand_source": "product_page", "price_source": "product_page", "product_source": "product_page"},
        "raw_data": {"name": name, "brand": brand, "size_ml": size_ml, "concentration": concentration},
        "name": name,
        "price": f"{price:.2f} €" if price is not None else "",
        "url": url,
        "image": image,
        "available": availability == "in_stock",
    }

def validate_candidates(candidates, query):
    if sync_playwright is None:
        return []
    results, seen = [], set()
    try:
        with sync_playwright() as pw:
            browser = launch_browser(pw)
            context = browser.new_context(user_agent=USER_AGENT, locale="fr-FR", viewport={"width": 1440, "height": 1000})
            page = context.new_page()
            for candidate in candidates[:MAX_VALIDATIONS]:
                url = candidate.get("url")
                if not url or url in seen:
                    continue
                seen.add(url)
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT)
                    dismiss_consent(page)
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
    results, seen = [], set()
    for candidate in candidates:
        product = parse_search_candidate(candidate, query)
        if not product:
            continue
        if product["url"] in seen:
            continue
        seen.add(product["url"])
        results.append(product)
    if not results:
        return validate_candidates(candidates, query)
    return results

def scrape(query):
    return search(query)

def diagnose(query):
    query = clean(query)
    if not query:
        return {"status": "error", "query": "", "errors": [{"stage": "input", "type": "empty_query"}]}
    candidates = browser_discover(query)
    return {
        "status": "ok" if candidates else "no_candidates",
        "query": query,
        "discovery": {"product_candidates": len(candidates), "unique_candidates": len({x.get("url") for x in candidates if x.get("url")})},
        "candidates": candidates[:20],
    }

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    args = parser.parse_args()
    print(json.dumps(search(args.query), ensure_ascii=False, indent=2))
