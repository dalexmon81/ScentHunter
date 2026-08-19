import json
import os
import re
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
        if image:
            pieces.extend([image.get("alt"), image.get("title")])
        text = clean(" ".join(x for x in pieces if x))
        seen.add(url)
        output.append({"url": url, "text": text, "score": candidate_score(text, url, query)})
    output.sort(key=lambda x: x["score"], reverse=True)
    return output[:MAX_CANDIDATES]


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


def browser_discover(query):
    if sync_playwright is None:
        return []
    candidates = []
    seen = set()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"])
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
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"])
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
    return validate_candidates(candidates, query)


def scrape(query):
    return search(query)


def _diagnose_parse_failure(html, response_url, query):
    """Generic diagnostic for a discovered Notino product candidate."""
    soup = BeautifulSoup(html, "html.parser")
    json_ld = extract_json_ld(soup)
    name = product_name(soup, json_ld)
    brand = product_brand(soup, json_ld)
    page_text = soup.get_text(" ", strip=True)
    size_ml = extract_size_ml(name, page_text)
    concentration = extract_concentration(name, page_text)
    requested_size = explicit_size(query)
    wanted = query_tokens(query)
    identity = norm(" ".join(x for x in (brand, name) if x))

    missing = [token for token in wanted if token not in identity and token not in norm(name)]
    size_ok = (
        True if requested_size is None
        else size_ml is not None and abs(float(size_ml) - float(requested_size)) <= 0.01
    )

    if not name:
        reason = "name_not_found"
    elif not looks_like_fragrance(name, concentration):
        reason = "not_recognized_as_fragrance"
    elif not same_host(response_url):
        reason = "wrong_host"
    elif not product_url(response_url):
        reason = "url_not_matching_current_product_pattern"
    elif missing:
        reason = "query_identity_mismatch"
    elif not size_ok:
        reason = "requested_size_mismatch"
    else:
        reason = None

    return {
        "name": name or None,
        "brand": brand or None,
        "json_ld_product": bool(json_ld),
        "concentration": concentration or None,
        "size_ml": size_ml,
        "requested_size_ml": requested_size,
        "query_tokens": wanted,
        "missing_query_tokens": missing,
        "url": response_url,
        "fragrance_like": bool(name and looks_like_fragrance(name, concentration)),
        "product_url_pattern": product_url(response_url),
        "valid": reason is None,
        "rejection_reason": reason,
    }


def diagnose(query):
    """Browser-first generic diagnostic; no product-specific logic."""
    query = clean(query)
    if not query:
        return {"query": "", "error": "empty_query"}
    if sync_playwright is None:
        return {"query": query, "error": "playwright_unavailable"}

    report = {
        "query": query,
        "search_url": search_page_urls(query)[0],
        "pages": [],
        "totals": {
            "raw_links": 0,
            "accepted_product_candidates": 0,
            "validated_products": 0,
            "validation_failures": 0,
        },
        "candidates": [],
    }

    seen_urls = set()
    visited_pages = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=USER_AGENT,
            locale="fr-FR",
            viewport={"width": 1440, "height": 1100},
        )
        page = context.new_page()
        try:
            page.goto(report["search_url"], wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT)

            for page_number in range(1, MAX_SEARCH_PAGES + 1):
                if page.url in visited_pages:
                    break
                visited_pages.add(page.url)
                page.wait_for_timeout(1200)

                page_url = page.url
                html = page.content()
                anchors = BeautifulSoup(html, "html.parser").find_all("a", href=True)
                candidates = extract_candidates(html, page_url)

                report["totals"]["raw_links"] += len(anchors)
                report["totals"]["accepted_product_candidates"] += len(candidates)
                report["pages"].append({
                    "page": page_number,
                    "url": page_url,
                    "raw_links": len(anchors),
                    "accepted_product_candidates": len(candidates),
                })

                # Diagnostic explores candidates in discovery order, so we can see
                # whether the queried product is discovered before ranking/limits.
                for candidate in candidates:
                    url = candidate["url"]
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)

                    item = {
                        "url": url,
                        "anchor_text": candidate.get("text", ""),
                        "score": candidate_score(candidate, query),
                        "opened": False,
                    }

                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT)
                        page.wait_for_timeout(500)
                        final_url = page.url
                        item["opened"] = True
                        item["final_url"] = final_url
                        details = _diagnose_parse_failure(page.content(), final_url, query)
                        item["validation"] = details
                        item["valid"] = details["valid"]
                        item["failure"] = details["rejection_reason"]
                        if details["valid"]:
                            report["totals"]["validated_products"] += 1
                        else:
                            report["totals"]["validation_failures"] += 1
                    except Exception as exc:
                        item["valid"] = False
                        item["failure"] = "page_open_error"
                        item["error"] = type(exc).__name__

                    report["candidates"].append(item)

                    if len(report["candidates"]) >= MAX_CANDIDATES:
                        break

                if len(report["candidates"]) >= MAX_CANDIDATES:
                    break

                # Return to the result page before looking for the next page.
                page.goto(page_url, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT)
                nxt = next_page_url(page)
                if not nxt or nxt in visited_pages:
                    break
                page.goto(nxt, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT)
        finally:
            context.close()
            browser.close()

    report["candidates"].sort(key=lambda item: item.get("score", 0), reverse=True)
    return report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    args = parser.parse_args()
    print(json.dumps(search(args.query), ensure_ascii=False, indent=2))
