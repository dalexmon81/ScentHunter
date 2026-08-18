import json
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

STORE = "Sabina"
BASE = "https://www.sabina.com"

# Diagnostic deliberately uses a short per-request timeout and NEVER hides
# which request failed. The production scraper is not modified by this file.
TIMEOUT = 10

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/18.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,it-IT,it;q=0.8,en;q=0.7",
    "Connection": "keep-alive",
}

STOPWORDS = {
    "eau", "de", "du", "des", "the", "for", "and", "with",
    "spray", "ml", "man", "men", "woman", "women",
    "homme", "femme", "herren", "damen", "parfum",
}

PRODUCT_RE = re.compile(
    r"^https?://(?:www\.)?sabina\.com/(?:[a-z]{2}/)?[^?#]*/\d+-[^?#]+\.html$",
    re.I,
)


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
    # Handles both 29,99 and 29.99 without trying to interpret arbitrary
    # numbers elsewhere in the page.
    m = re.search(r"(?<!\d)(\d+(?:[.,]\d{1,2})?)\s*(?:€|EUR)", text, re.I)
    if not m:
        m = re.search(r"(?<!\d)(\d+[.,]\d{2})(?!\d)", text)
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


def _request(session, label, url, **kwargs):
    """
    Diagnostic request wrapper.

    IMPORTANT:
    Every request prints START before network I/O and END/ERROR after it.
    This prevents the previous failure mode where the log stopped at
    SABINA_DIAG: TOKENS and gave us no idea which request was hanging.
    """
    started = time.monotonic()
    print(f"SABINA_DIAG: HTTP_START label={label} url={url}", flush=True)

    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
            **kwargs,
        )
        elapsed = round(time.monotonic() - started, 3)
        content_type = response.headers.get("content-type", "")
        print(
            f"SABINA_DIAG: HTTP_END label={label} "
            f"status={response.status_code} "
            f"elapsed={elapsed}s "
            f"final={response.url} "
            f"bytes={len(response.content)} "
            f"type={content_type!r} "
            f"server={response.headers.get('server')!r} "
            f"cf_ray={response.headers.get('cf-ray')!r}",
            flush=True,
        )
        return response

    except requests.RequestException as exc:
        elapsed = round(time.monotonic() - started, 3)
        print(
            f"SABINA_DIAG: HTTP_ERROR label={label} "
            f"elapsed={elapsed}s "
            f"error={type(exc).__name__}: {exc}",
            flush=True,
        )
        return None
    except Exception as exc:
        elapsed = round(time.monotonic() - started, 3)
        print(
            f"SABINA_DIAG: HTTP_EXCEPTION label={label} "
            f"elapsed={elapsed}s "
            f"error={type(exc).__name__}: {exc}",
            flush=True,
        )
        return None


def _challenge_words(html):
    low = (html or "").lower()
    words = (
        "captcha",
        "cloudflare",
        "attention required",
        "verify you are human",
        "cf-chl",
        "challenge-platform",
        "access denied",
        "forbidden",
    )
    return [x for x in words if x in low]


def _discover_from_html(html, base_url, query, stage):
    soup = BeautifulSoup(html, "html.parser")
    found = []
    seen = set()
    wanted = tokens(query)

    for anchor in soup.find_all("a", href=True):
        url = urljoin(base_url, anchor.get("href") or "").split("#")[0]
        if not product_url(url) or url in seen:
            continue

        anchor_text = clean(
            anchor.get("title")
            or anchor.get("aria-label")
            or anchor.get_text(" ", strip=True)
        )

        slug = unquote(urlparse(url).path.rsplit("/", 1)[-1])

        nearby = anchor
        nearby_text = ""
        for _ in range(5):
            nearby = getattr(nearby, "parent", None)
            if nearby is None:
                break
            candidate = clean(nearby.get_text(" ", strip=True))
            if len(candidate) <= 1500:
                nearby_text = candidate
                break

        score_anchor = sum(t in norm(anchor_text) for t in wanted)
        score_slug = sum(t in norm(slug) for t in wanted)
        score_nearby = sum(t in norm(nearby_text) for t in wanted)

        # Diagnostic records product URLs even when the query terms are not
        # in the anchor. This is important: Sabina may render product cards
        # whose visible text is generated elsewhere in the card.
        if score_anchor == 0 and score_slug == 0 and score_nearby == 0:
            continue

        seen.add(url)
        found.append({
            "url": url,
            "anchor_text": anchor_text,
            "slug": slug,
            "nearby_text": nearby_text[:500],
            "score_anchor": score_anchor,
            "score_slug": score_slug,
            "score_nearby": score_nearby,
            "stage": stage,
        })

    return found


def _extract_all_product_urls(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    urls = []
    seen = set()

    for anchor in soup.find_all("a", href=True):
        url = urljoin(base_url, anchor.get("href") or "").split("#")[0]
        if product_url(url) and url not in seen:
            seen.add(url)
            urls.append(url)

    return urls


def _product_page_diagnostics(session, candidate, query, index):
    url = candidate["url"]
    response = _request(session, f"VERIFY_{index}", url)

    if response is None:
        return {
            "url": url,
            "status": "request_error",
            "title": "",
            "matches_title": False,
            "price": None,
            "challenge": [],
        }

    final_url = response.url
    status = response.status_code
    html = response.text
    challenge = _challenge_words(html)

    if status != 200:
        response.close()
        return {
            "url": final_url,
            "status": status,
            "title": "",
            "matches_title": False,
            "price": None,
            "challenge": challenge,
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

    # JSON-LD first.
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
            is_product = typ == "Product" or (
                isinstance(typ, list) and "Product" in typ
            )

            if is_product:
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

            if price is not None:
                break

            for value in item.values():
                if isinstance(value, (dict, list)):
                    stack.append(value)

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

    response.close()

    return {
        "url": final_url,
        "status": status,
        "title": title,
        "matches_title": matches(title, query),
        "price": price,
        "challenge": challenge,
    }


def _sitemap_diagnostics(session, query):
    """
    Diagnostic-only sitemap probe.

    It does NOT crawl the whole site. It only determines whether Sabina
    exposes product URLs through a sitemap and whether the query can reach
    one of them.
    """
    sources = [
        BASE + "/sitemap.xml",
        BASE + "/sitemap_index_shop_1.xml",
        BASE + "/fr/sitemap.xml",
    ]

    matching = []

    for idx, url in enumerate(sources, 1):
        response = _request(session, f"SITEMAP_{idx}", url)

        if response is None:
            continue

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
            locs = re.findall(
                r"<loc>\s*(.*?)\s*</loc>",
                text,
                flags=re.I | re.S,
            )

        print(
            f"SABINA_DIAG: SITEMAP_{idx}_LOCS={len(locs)}",
            flush=True,
        )

        direct_products = [u for u in locs if product_url(u)]

        if direct_products:
            hits = [
                u for u in direct_products
                if matches(unquote(u), query)
            ]
            print(
                f"SABINA_DIAG: SITEMAP_{idx}_DIRECT_PRODUCTS="
                f"{len(direct_products)} "
                f"MATCHES={len(hits)}",
                flush=True,
            )
            matching.extend(hits[:10])
            continue

        children = [
            u for u in locs
            if u.lower().split("?", 1)[0].endswith(".xml")
        ]

        for child_index, child_url in enumerate(children[:20], 1):
            response = _request(
                session,
                f"SITEMAP_{idx}_CHILD_{child_index}",
                child_url,
            )
            if response is None:
                continue

            if response.status_code != 200:
                response.close()
                continue

            child_text = response.text
            response.close()

            child_locs = re.findall(
                r"<loc>\s*(.*?)\s*</loc>",
                child_text,
                flags=re.I | re.S,
            )

            hits = [
                u for u in child_locs
                if product_url(u) and matches(unquote(u), query)
            ]

            print(
                f"SABINA_DIAG: SITEMAP_CHILD_RESULT "
                f"url={child_url} "
                f"locs={len(child_locs)} "
                f"matches={len(hits)}",
                flush=True,
            )

            if hits:
                matching.extend(hits[:10])
                break

    deduped = []
    seen = set()

    for url in matching:
        if url not in seen:
            seen.add(url)
            deduped.append(url)

    print(
        f"SABINA_DIAG: SITEMAP_MATCHING_PRODUCTS={len(deduped)}",
        flush=True,
    )
    return deduped[:20]


def _native_search_diagnostics(session, query):
    """
    Test the native search routes one by one.

    The important difference from the previous diagnostic is that every
    request is observable. We also count ALL product URLs on a successful
    search page before applying query matching.
    """
    encoded = quote_plus(query)

    urls = [
        ("SEARCH_FR_1", BASE + "/fr/recherche?search_query=" + encoded),
        ("SEARCH_FR_2", BASE + "/fr/recherche?s=" + encoded),
        ("SEARCH_FR_3", BASE + "/fr/search?s=" + encoded),
        ("SEARCH_FR_4", BASE + "/fr/search?q=" + encoded),
        ("SEARCH_IT_1", BASE + "/it/ricerca?search_query=" + encoded),
        ("SEARCH_IT_2", BASE + "/it/ricerca_old?s=" + encoded),
        ("SEARCH_IT_3", BASE + "/it/ricerca_old?search_query=" + encoded),
    ]

    candidates = []

    for label, url in urls:
        response = _request(session, label, url)

        if response is None:
            continue

        status = response.status_code
        final_url = response.url
        html = response.text if status == 200 else ""
        challenge = _challenge_words(html)

        if challenge:
            print(
                f"SABINA_DIAG: {label}_CHALLENGE={challenge}",
                flush=True,
            )

        if status == 200:
            all_product_urls = _extract_all_product_urls(
                html, final_url
            )
            print(
                f"SABINA_DIAG: {label}_ALL_PRODUCT_URLS="
                f"{len(all_product_urls)}",
                flush=True,
            )

            found = _discover_from_html(
                html, final_url, query, label
            )

            print(
                f"SABINA_DIAG: {label}_MATCHING_CANDIDATES="
                f"{len(found)}",
                flush=True,
            )

            candidates.extend(found)

        response.close()

    return candidates


def search(query):
    """
    DEFINITIVE SABINA DIAGNOSTIC.

    It is intentionally NOT a production scraper.
    It follows the working ScentHunter architecture:

        discovery -> candidate product URL -> real product page -> validation

    It also probes the sitemap path separately.

    The diagnostic ALWAYS exposes:
      1. which HTTP request is running;
      2. its status/final URL/size/content type;
      3. whether Sabina returned a challenge;
      4. how many product URLs existed on the page;
      5. how many matched the query;
      6. whether candidate product pages validate;
      7. the final reason for success/failure.

    No single perfume name is hard-coded.
    """
    query = clean(query)

    if not query:
        print("SABINA_DIAG: EMPTY_QUERY", flush=True)
        return []

    print("=" * 70, flush=True)
    print(f"SABINA_DIAG: START query={query!r}", flush=True)
    print(f"SABINA_DIAG: TOKENS={tokens(query)}", flush=True)
    print(f"SABINA_DIAG: TIMEOUT={TIMEOUT}s", flush=True)
    print("=" * 70, flush=True)

    session = requests.Session()
    session.headers.update(HEADERS)

    results = []
    native_candidates = []
    sitemap_candidates = []

    try:
        # ------------------------------------------------------------
        # STEP 0 — home page
        # ------------------------------------------------------------
        home = _request(session, "HOME_FR", BASE + "/fr/")

        if home is None:
            print("SABINA_DIAG: HOME_RESULT=REQUEST_ERROR", flush=True)
        else:
            html = home.text if home.status_code == 200 else ""
            print(
                f"SABINA_DIAG: HOME_RESULT status={home.status_code} "
                f"bytes={len(home.content)} "
                f"challenge={_challenge_words(html)}",
                flush=True,
            )

            if home.status_code == 200:
                soup = BeautifulSoup(html, "html.parser")
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
                        name.lower() in {
                            "s", "q", "search", "search_query"
                        }
                        or str(kind).lower() == "search"
                        for name, kind, _ in fields
                    ):
                        forms.append({
                            "action": urljoin(
                                home.url,
                                form.get("action") or "/fr/",
                            ),
                            "method": (
                                form.get("method") or "get"
                            ).lower(),
                            "fields": fields,
                        })

                print(
                    f"SABINA_DIAG: SEARCH_FORMS={len(forms)}",
                    flush=True,
                )
                for form in forms[:10]:
                    print(
                        f"SABINA_DIAG: FORM={form}",
                        flush=True,
                    )

            home.close()

        # ------------------------------------------------------------
        # STEP A — native search discovery
        # ------------------------------------------------------------
        native_candidates = _native_search_diagnostics(
            session, query
        )

        # ------------------------------------------------------------
        # STEP B — sitemap discovery
        # ------------------------------------------------------------
        sitemap_candidates = _sitemap_diagnostics(
            session, query
        )

        # ------------------------------------------------------------
        # STEP C — merge candidates
        # ------------------------------------------------------------
        candidates = []
        seen = set()

        for item in native_candidates:
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
                    "slug": unquote(
                        urlparse(url).path.rsplit("/", 1)[-1]
                    ),
                    "nearby_text": "",
                    "score_anchor": 0,
                    "score_slug": len(tokens(query)),
                    "score_nearby": 0,
                    "stage": "SITEMAP",
                })

        print(
            f"SABINA_DIAG: NATIVE_CANDIDATES={len(native_candidates)}",
            flush=True,
        )
        print(
            f"SABINA_DIAG: SITEMAP_CANDIDATES={len(sitemap_candidates)}",
            flush=True,
        )
        print(
            f"SABINA_DIAG: TOTAL_UNIQUE_CANDIDATES={len(candidates)}",
            flush=True,
        )

        # Keep diagnostic bounded.
        candidates = candidates[:20]

        # ------------------------------------------------------------
        # STEP D — real product page verification
        # ------------------------------------------------------------
        for index, candidate in enumerate(candidates, 1):
            print(
                f"SABINA_DIAG: CANDIDATE_{index} "
                f"stage={candidate['stage']} "
                f"url={candidate['url']} "
                f"anchor_score={candidate['score_anchor']} "
                f"slug_score={candidate['score_slug']} "
                f"nearby_score={candidate['score_nearby']}",
                flush=True,
            )

            verified = _product_page_diagnostics(
                session,
                candidate,
                query,
                index,
            )

            print(
                f"SABINA_DIAG: VERIFY_{index} "
                f"status={verified['status']} "
                f"title={verified['title']!r} "
                f"title_match={verified['matches_title']} "
                f"price={verified['price']!r} "
                f"challenge={verified['challenge']}",
                flush=True,
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
        # FINAL DIAGNOSIS
        # ------------------------------------------------------------
        if results:
            diagnosis = "DISCOVERY_AND_VERIFICATION_OK"
        elif candidates:
            diagnosis = (
                "DISCOVERY_FOUND_CANDIDATES_BUT_VERIFICATION_FAILED"
            )
        elif native_candidates:
            diagnosis = "NATIVE_DISCOVERY_FOUND_BUT_NO_UNIQUE_CANDIDATE"
        elif sitemap_candidates:
            diagnosis = "SITEMAP_DISCOVERY_FOUND_BUT_NO_UNIQUE_CANDIDATE"
        else:
            diagnosis = "NO_PRODUCT_URL_DISCOVERED"

        print("=" * 70, flush=True)
        print(f"SABINA_DIAG: DIAGNOSIS={diagnosis}", flush=True)
        print(
            f"SABINA_DIAG: FINAL_RESULTS={len(results)}",
            flush=True,
        )

        if diagnosis == "NO_PRODUCT_URL_DISCOVERED":
            print(
                "SABINA_DIAG: CONCLUSION=Sabina did not expose a usable "
                "product URL through the tested discovery paths.",
                flush=True,
            )
        elif diagnosis == (
            "DISCOVERY_FOUND_CANDIDATES_BUT_VERIFICATION_FAILED"
        ):
            print(
                "SABINA_DIAG: CONCLUSION=Discovery works; the failure "
                "is in real product-page verification.",
                flush=True,
            )
        else:
            print(
                "SABINA_DIAG: CONCLUSION=At least one discovery/verification "
                "path works.",
                flush=True,
            )

        print("=" * 70, flush=True)

        return results

    except Exception as exc:
        # The diagnostic itself must NEVER bring down ScentHunter's entire
        # concurrent search because of an internal diagnostic exception.
        print(
            f"SABINA_DIAG: INTERNAL_EXCEPTION "
            f"type={type(exc).__name__}: {exc}",
            flush=True,
        )
        return []

    finally:
        session.close()


# Main.py compatibility.
def scrape(query):
    return search(query)


def search_sabina(query):
    return search(query)


if __name__ == "__main__":
    import sys

    query = " ".join(sys.argv[1:]).strip() or "Liquid brun"
    output = search(query)
    print(json.dumps(output, ensure_ascii=False, indent=2))
