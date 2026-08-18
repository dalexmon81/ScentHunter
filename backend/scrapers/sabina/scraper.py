import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

STORE = "Sabina"
BASE = "https://www.sabina.com"
TIMEOUT = 15

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept": "application/json,text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

STOPWORDS = {
    "eau", "de", "du", "des", "the", "for", "and", "with",
    "spray", "ml", "man", "men", "woman", "women",
    "homme", "femme", "herren", "damen", "parfum",
}

PRODUCT_RE = re.compile(r"^https?://(?:www\.)?sabina\.com/fr/.+/\d+-[^?#]+\.html$", re.I)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def norm(value):
    value = unicodedata.normalize("NFKD", clean(value)).lower()
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def tokens(value):
    return [x for x in norm(value).split() if len(x) > 1 and x not in STOPWORDS]


def matches(text, query):
    wanted = tokens(query)
    hay = set(tokens(text))
    return bool(wanted) and all(t in hay for t in wanted)


def price_value(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = clean(value)
    m = re.search(r"(?<!\d)(\d+(?:[.,]\d{1,2})?)\s*(?:€|EUR)?", text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def format_price(value):
    p = price_value(value)
    return f"{p:.2f}".replace(".", ",") + " €" if p is not None else ""


def product_url(url):
    try:
        return bool(PRODUCT_RE.match(urljoin(BASE, str(url or ""))))
    except Exception:
        return False


def _request(session, url, **kwargs):
    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
            **kwargs,
        )
        return response
    except requests.RequestException as exc:
        print(f"SABINA_DIAG: REQUEST_ERROR url={url} error={type(exc).__name__}: {exc}")
        return None


def _discover_from_html(html, base_url, query, stage):
    soup = BeautifulSoup(html, "html.parser")
    found = []
    seen = set()

    anchors = soup.find_all("a", href=True)
    for anchor in anchors:
        url = urljoin(base_url, anchor.get("href") or "").split("#")[0]
        if not product_url(url) or url in seen:
            continue

        anchor_text = clean(
            anchor.get("title")
            or anchor.get("aria-label")
            or anchor.get_text(" ", strip=True)
        )

        slug = unquote(urlparse(url).path.rsplit("/", 1)[-1])
        score_anchor = sum(t in norm(anchor_text) for t in tokens(query))
        score_slug = sum(t in norm(slug) for t in tokens(query))

        # Discovery is intentionally diagnostic:
        # it records whether query terms are visible in the product URL,
        # in the product link itself, or only somewhere in the nearby card.
        nearby = anchor.parent
        nearby_text = ""
        for _ in range(4):
            if nearby is None:
                break
            candidate = clean(nearby.get_text(" ", strip=True))
            if len(candidate) <= 1200:
                nearby_text = candidate
                break
            nearby = nearby.parent

        score_nearby = sum(t in norm(nearby_text) for t in tokens(query))

        if score_anchor == 0 and score_slug == 0 and score_nearby == 0:
            continue

        seen.add(url)
        found.append({
            "url": url,
            "anchor_text": anchor_text,
            "slug": slug,
            "nearby_text": nearby_text,
            "score_anchor": score_anchor,
            "score_slug": score_slug,
            "score_nearby": score_nearby,
            "stage": stage,
        })

    return found


def _product_page_diagnostics(session, candidate, query):
    url = candidate["url"]
    response = _request(session, url)
    if response is None:
        return {
            "url": url,
            "status": "request_error",
            "title": "",
            "matches_title": False,
            "price": None,
        }

    final_url = response.url
    status = response.status_code
    html = response.text
    response.close()

    if status != 200:
        return {
            "url": final_url,
            "status": status,
            "title": "",
            "matches_title": False,
            "price": None,
        }

    soup = BeautifulSoup(html, "html.parser")

    h1 = soup.find("h1")
    title = clean(h1.get_text(" ", strip=True)) if h1 else ""

    if not title:
        meta = soup.select_one("meta[property='og:title']")
        title = clean(meta.get("content")) if meta else ""

    if not title:
        title_tag = soup.find("title")
        title = clean(title_tag.get_text(" ", strip=True)) if title_tag else ""

    price = None

    # Structured data first.
    for script in soup.find_all("script", type=lambda x: x and "ld+json" in x):
        try:
            data = json.loads(script.get_text())
        except Exception:
            continue

        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
                continue
            if not isinstance(item, dict):
                continue

            typ = item.get("@type")
            if typ == "Product" or (isinstance(typ, list) and "Product" in typ):
                offers = item.get("offers")
                offers = offers if isinstance(offers, list) else [offers]
                for offer in offers:
                    if isinstance(offer, dict):
                        p = price_value(
                            offer.get("price")
                            or offer.get("lowPrice")
                            or offer.get("highPrice")
                        )
                        if p is not None:
                            price = p
                            break

            for value in item.values():
                if isinstance(value, (dict, list)):
                    stack.append(value)

            if price is not None:
                break

        if price is not None:
            break

    if price is None:
        for selector in (
            "[itemprop='price']",
            "meta[property='product:price:amount']",
            ".product-price",
            ".current-price",
            ".price",
        ):
            node = soup.select_one(selector)
            if node:
                value = node.get("content") or node.get_text(" ", strip=True)
                price = price_value(value)
                if price is not None:
                    break

    return {
        "url": final_url,
        "status": status,
        "title": title,
        "matches_title": matches(title, query),
        "price": price,
    }


def _sitemap_diagnostics(session, query):
    sitemap_urls = []
    sitemap_sources = [
        BASE + "/sitemap.xml",
        BASE + "/sitemap_index_shop_1.xml",
        BASE + "/fr/sitemap.xml",
    ]

    for url in sitemap_sources:
        response = _request(session, url)
        if response is None:
            continue

        print(
            f"SABINA_DIAG: SITEMAP_FETCH status={response.status_code} "
            f"url={url} final={response.url} bytes={len(response.content)} "
            f"type={(response.headers.get('content-type') or '')!r}"
        )

        if response.status_code != 200:
            response.close()
            continue

        text = response.text
        response.close()

        try:
            root = ET.fromstring(text)
            locs = [
                node.text.strip()
                for node in root.iter()
                if node.tag.endswith("loc") and node.text
            ]
        except ET.ParseError:
            locs = re.findall(r"<loc>\s*(.*?)\s*</loc>", text, flags=re.I | re.S)

        print(f"SABINA_DIAG: SITEMAP_LOCS={len(locs)}")

        if not locs:
            continue

        child = [u for u in locs if u.lower().endswith(".xml")]
        products = [u for u in locs if product_url(u)]

        if products:
            sitemap_urls.extend(products)
            break

        # Record child sitemap availability, but do not recursively crawl the
        # whole site: this test is meant to identify whether sitemap discovery
        # is actually capable of reaching product URLs.
        for child_url in child[:20]:
            cr = _request(session, child_url)
            if cr is None or cr.status_code != 200:
                if cr is not None:
                    cr.close()
                continue

            ctext = cr.text
            cr.close()

            child_locs = re.findall(
                r"<loc>\s*(.*?)\s*</loc>",
                ctext,
                flags=re.I | re.S,
            )

            matching = [
                u for u in child_locs
                if product_url(u)
                and matches(unquote(u), query)
            ]

            if matching:
                print(
                    f"SABINA_DIAG: SITEMAP_CHILD_MATCHES={len(matching)} "
                    f"child={child_url}"
                )
                sitemap_urls.extend(matching)
                break

        if sitemap_urls:
            break

    deduped = []
    seen = set()
    for url in sitemap_urls:
        if url not in seen:
            seen.add(url)
            deduped.append(url)

    print(
        f"SABINA_DIAG: SITEMAP_MATCHING_PRODUCTS={len(deduped)}"
    )
    return deduped[:20]


def search(query):
    """
    DEFINITIVE DIAGNOSTIC ONLY.

    This does NOT try to be a production scraper.
    It is intentionally modeled after the three working scrapers:
      Bplatz/Orioudh -> search/discovery -> product URL -> product page
      ParfumZentrum -> sitemap -> product URL -> product page

    Goal:
      identify exactly which stage is failing on Sabina.
    """
    query = clean(query)
    if not query:
        return []

    print(f"SABINA_DIAG: START query={query!r}")
    print(f"SABINA_DIAG: TOKENS={tokens(query)}")

    session = requests.Session()
    results = []

    try:
        # ------------------------------------------------------------
        # TEST A: native search endpoints discovered from the live site.
        # We test them, but do not trust them as the identity engine.
        # ------------------------------------------------------------
        home = _request(session, BASE + "/fr/")
        if home is not None:
            print(
                f"SABINA_DIAG: HOME status={home.status_code} "
                f"final={home.url} bytes={len(home.content)}"
            )

            if home.status_code == 200:
                soup = BeautifulSoup(home.text, "html.parser")
                forms = []

                for form in soup.find_all("form"):
                    fields = []
                    for inp in form.find_all("input"):
                        name = inp.get("name")
                        if name:
                            fields.append(
                                (
                                    name,
                                    inp.get("type") or "",
                                    inp.get("value") or "",
                                )
                            )

                    if any(
                        x[0].lower()
                        in {"s", "q", "search", "search_query"}
                        or str(x[1]).lower() == "search"
                        for x in fields
                    ):
                        forms.append({
                            "action": urljoin(home.url, form.get("action") or "/fr/"),
                            "method": (form.get("method") or "get").lower(),
                            "fields": fields,
                        })

                print(f"SABINA_DIAG: SEARCH_FORMS={len(forms)}")
                for item in forms:
                    print(f"SABINA_DIAG: FORM={item}")

                home.close()
        else:
            print("SABINA_DIAG: HOME_REQUEST_FAILED")

        search_urls = [
            BASE + "/fr/recherche?search_query=" + quote_plus(query),
            BASE + "/fr/recherche?s=" + quote_plus(query),
            BASE + "/fr/search?s=" + quote_plus(query),
            BASE + "/fr/search?q=" + quote_plus(query),
            BASE + "/it/ricerca?search_query=" + quote_plus(query),
            BASE + "/it/ricerca_old?s=" + quote_plus(query),
            BASE + "/it/ricerca_old?search_query=" + quote_plus(query),
        ]

        search_candidate_pool = []

        for index, url in enumerate(search_urls, 1):
            response = _request(session, url)
            if response is None:
                print(f"SABINA_DIAG: SEARCH_{index}=REQUEST_ERROR")
                continue

            status = response.status_code
            final_url = response.url
            html = response.text if status == 200 else ""

            print(
                f"SABINA_DIAG: SEARCH_{index} "
                f"status={status} final={final_url} "
                f"bytes={len(response.content)}"
            )

            if status == 200:
                found = _discover_from_html(
                    html,
                    final_url,
                    query,
                    f"SEARCH_{index}",
                )
                print(
                    f"SABINA_DIAG: SEARCH_{index}_PRODUCT_CANDIDATES="
                    f"{len(found)}"
                )
                search_candidate_pool.extend(found)

            response.close()

        # ------------------------------------------------------------
        # TEST B: Shopify-style / generic JSON search probes.
        # This tells us whether Sabina exposes a structured search API.
        # ------------------------------------------------------------
        json_urls = [
            (
                BASE + "/search.json",
                {"q": query, "type": "product", "limit": 50},
            ),
            (
                BASE + "/fr/search.json",
                {"q": query, "type": "product", "limit": 50},
            ),
        ]

        for index, (url, params) in enumerate(json_urls, 1):
            response = _request(session, url, params=params)
            if response is None:
                continue

            content_type = (
                response.headers.get("content-type") or ""
            ).lower()

            body = response.text
            print(
                f"SABINA_DIAG: JSON_SEARCH_{index} "
                f"status={response.status_code} "
                f"type={content_type!r} bytes={len(response.content)}"
            )

            if response.status_code == 200:
                try:
                    data = response.json()
                    products = data.get("products") if isinstance(data, dict) else None
                    print(
                        f"SABINA_DIAG: JSON_SEARCH_{index}_PRODUCTS="
                        f"{len(products) if isinstance(products, list) else 0}"
                    )

                    if isinstance(products, list):
                        for product in products:
                            if not isinstance(product, dict):
                                continue

                            title = clean(product.get("title"))
                            vendor = clean(product.get("vendor"))
                            raw_url = clean(product.get("url"))

                            if raw_url:
                                product_abs = urljoin(BASE, raw_url)
                            else:
                                product_abs = ""

                            if product_abs and product_match(product_abs) and (
                                matches(title + " " + vendor + " " + product_abs, query)
                            ):
                                search_candidate_pool.append({
                                    "url": product_abs.split("?")[0],
                                    "anchor_text": title,
                                    "slug": product_abs,
                                    "nearby_text": vendor,
                                    "score_anchor": len(tokens(query)),
                                    "score_slug": len(tokens(query)),
                                    "score_nearby": len(tokens(query)),
                                    "stage": f"JSON_SEARCH_{index}",
                                })
                except Exception as exc:
                    print(
                        f"SABINA_DIAG: JSON_SEARCH_{index}_NOT_JSON "
                        f"error={type(exc).__name__}: {exc}"
                    )

            response.close()

        # ------------------------------------------------------------
        # TEST C: sitemap path, modeled directly after ParfumZentrum.
        # ------------------------------------------------------------
        sitemap_candidates = _sitemap_diagnostics(session, query)

        # ------------------------------------------------------------
        # TEST D: verify every distinct candidate on the real product page.
        # This is the decisive step. It tells us:
        #   discovery failed
        #   discovery succeeded but URL verification failed
        #   title matching failed
        #   price extraction failed
        # ------------------------------------------------------------
        candidates = []

        seen = set()
        for item in search_candidate_pool:
            url = item["url"]
            if url not in seen:
                seen.add(url)
                candidates.append(item)

        for url in sitemap_candidates:
            if url not in seen:
                seen.add(url)
                candidates.append({
                    "url": url,
                    "anchor_text": "",
                    "slug": unquote(urlparse(url).path.rsplit("/", 1)[-1]),
                    "nearby_text": "",
                    "score_anchor": 0,
                    "score_slug": len(tokens(query)),
                    "score_nearby": 0,
                    "stage": "SITEMAP",
                })

        candidates = candidates[:30]

        print(
            f"SABINA_DIAG: TOTAL_UNIQUE_CANDIDATES={len(candidates)}"
        )

        for index, candidate in enumerate(candidates, 1):
            print(
                f"SABINA_DIAG: CANDIDATE_{index} "
                f"stage={candidate['stage']} "
                f"url={candidate['url']} "
                f"anchor_score={candidate['score_anchor']} "
                f"slug_score={candidate['score_slug']} "
                f"nearby_score={candidate['score_nearby']}"
            )

            verified = _product_page_diagnostics(
                session,
                candidate,
                query,
            )

            print(
                f"SABINA_DIAG: VERIFY_{index} "
                f"status={verified['status']} "
                f"title={verified['title']!r} "
                f"title_match={verified['matches_title']} "
                f"price={verified['price']!r}"
            )

            if (
                verified["status"] == 200
                and verified["matches_title"]
                and verified["price"] is not None
            ):
                results.append({
                    "store": STORE,
                    "name": verified["title"],
                    "price": format_price(verified["price"]),
                    "url": verified["url"],
                    "available": True,
                })

        # ------------------------------------------------------------
        # FINAL DIAGNOSIS.
        # ------------------------------------------------------------
        if results:
            diagnosis = "DISCOVERY_AND_VERIFICATION_OK"
        elif candidates:
            diagnosis = "DISCOVERY_FOUND_CANDIDATES_BUT_VERIFICATION_FAILED"
        else:
            diagnosis = "NO_PRODUCT_URL_DISCOVERED"

        print(f"SABINA_DIAG: DIAGNOSIS={diagnosis}")
        print(f"SABINA_DIAG: FINAL_RESULTS={len(results)}")

        return results

    finally:
        session.close()


# Compatible entry points. Main can run this diagnostic exactly like an adapter.
def scrape(query):
    return search(query)


def search_sabina(query):
    return search(query)


if __name__ == "__main__":
    import sys

    q = " ".join(sys.argv[1:]).strip() or "Dior"
    print(json.dumps(search(q), ensure_ascii=False, indent=2))
