import json
import re
from urllib.parse import quote_plus, urljoin
import requests
from bs4 import BeautifulSoup

STORE = "ParfumCity"
BASE_URL = "https://www.parfumcity.nl"
TIMEOUT = 10
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
}

def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()

def norm(value):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", clean(value).lower())).strip()

def tokens(value):
    return [x for x in norm(value).split() if len(x) > 1]

def matches(text, query):
    q = set(tokens(query))
    if not q:
        return False

    text_tokens = set(tokens(text))
    if q.issubset(text_tokens):
        return True

    normalized_text = norm(text).replace(" ", "")
    return all(
        token in text_tokens or token in normalized_text
        for token in q
    )

def price(value):
    match = re.search(r"(?<![\d.,])(\d{1,4}(?:[.,]\d{2}))\s*€|€\s*(\d{1,4}(?:[.,]\d{2}))", clean(value))
    if not match:
        return None
    raw = next(x for x in match.groups() if x)
    return float(raw.replace(".", "").replace(",", ".")) if "," in raw and "." in raw else float(raw.replace(",", "."))

def size_ml(*values):
    match = re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b", " ".join(clean(x) for x in values), re.I)
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    if match.group(2).lower() == "cl":
        value *= 10
    return int(value) if value.is_integer() else value

def concentration(*values):
    text = norm(" ".join(clean(x) for x in values))
    if re.search(r"\beau de toilette\b|\bedt\b", text): return "Eau de Toilette"
    if re.search(r"\beau de parfum\b|\bedp\b", text): return "Eau de Parfum"
    if re.search(r"\bextrait(?: de parfum)?\b", text): return "Extrait de Parfum"
    return None

NON_PRODUCT_TERMS = {
    "sample", "samples", "tester", "testers", "gift set", "coffret",
    "set regalo", "discovery set", "bundle", "kit", "travel set",
    "deodorant", "deo spray", "shower gel", "body lotion",
    "body mist", "after shave", "aftershave",
}

def is_non_product(text):
    value = norm(text)
    return any(
        term in value
        for term in NON_PRODUCT_TERMS
    )

def product_name_from_url(url):
    try:
        path = url.split("?", 1)[0].rstrip("/")
        slug = path.rsplit("/", 1)[-1]
    except Exception:
        return ""
    return clean(re.sub(r"[-_]+", " ", slug))

def product_urls_from_search_json(data):
    urls = []
    seen = set()

    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"url", "handle"} and isinstance(item, str):
                    candidate = item
                    if candidate.startswith("/"):
                        candidate = urljoin(BASE_URL, candidate)
                    if "/products/" in candidate:
                        candidate = candidate.split("?", 1)[0]
                        if candidate not in seen:
                            seen.add(candidate)
                            urls.append(candidate)
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(data)
    return urls

def shopify_suggest(session, query):
    urls = []
    seen = set()

    endpoints = [
        BASE_URL + "/search/suggest.json?q=" + quote_plus(query)
        + "&resources[type]=product&resources[limit]=20",
        BASE_URL + "/search.json?q=" + quote_plus(query),
    ]

    for endpoint in endpoints:
        try:
            response = session.get(
                endpoint,
                headers=HEADERS,
                timeout=TIMEOUT,
            )
            if response.status_code != 200:
                continue
            data = response.json()
        except (requests.RequestException, ValueError):
            continue

        for url in product_urls_from_search_json(data):
            if url not in seen:
                seen.add(url)
                urls.append(url)

    return urls

def product_page(session, url, query):
    try:
        r = session.get(url, headers=HEADERS, timeout=TIMEOUT)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    soup = BeautifulSoup(r.text, "html.parser")
    h1 = soup.find("h1")
    name = clean(h1.get_text(" ", strip=True)) if h1 else ""
    if not name:
        return None

    page_identity = f"{name} {product_name_from_url(url)}"

    if is_non_product(page_identity):
        return None

    if not matches(page_identity, query):
        return None

    amount = None
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.get_text(strip=True))
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop(0)
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                offers = item.get("offers")
                offers = offers if isinstance(offers, list) else [offers]
                for offer in offers:
                    if isinstance(offer, dict):
                        try:
                            amount = float(str(offer.get("price")).replace(",", "."))
                        except (TypeError, ValueError):
                            pass
                        if amount:
                            break
                if amount:
                    break

    if amount is None:
        text = soup.get_text(" ", strip=True)
        amount = price(text)

    if amount is None:
        return None

    image = None
    meta = soup.select_one('meta[property="og:image"]')
    if meta and meta.get("content"):
        image = urljoin(url, meta["content"])

    return {
        "store": STORE,
        "source": {
            "source_name": name,
            "source_brand": None,
            "url": url,
            "image": image,
        },
        "identity": {
            "gtin": None,
            "mpn": None,
            "sku": None,
            "store_product_id": None,
            "store_variant_id": None,
        },
        "attributes": {
            "size_ml": {"value": size_ml(name), "source": "product_title"} if size_ml(name) else None,
            "concentration": {"value": concentration(name), "source": "product_title"} if concentration(name) else None,
            "gender": {"value": "unknown", "source": "not_explicit"},
            "packaging_type": {"value": "product", "source": "default"},
        },
        "offer": {
            "price": round(amount, 2),
            "currency": "EUR",
            "availability": "unknown",
        },
        "provenance": {"source_page": url, "name_source": "h1", "price_source": "jsonld_or_page"},
        "raw_data": {},
        "name": name,
        "price": f"{amount:.2f}".replace(".", ",") + "€",
        "url": url,
        "available": True,
    }

def search(query):
    query = clean(query)
    if not query:
        return []

    session = requests.Session()

    try:
        urls = []
        seen = set()

        query_variants = [query]
        query_tokens = tokens(query)

        if len(query_tokens) > 1:
            reversed_query = " ".join(reversed(query_tokens))
            if reversed_query not in query_variants:
                query_variants.append(reversed_query)

        for variant in query_variants:
            search_url = (
                BASE_URL
                + "/search?q="
                + quote_plus(variant)
            )

            try:
                r = session.get(
                    search_url,
                    headers=HEADERS,
                    timeout=TIMEOUT,
                )
                r.raise_for_status()
                soup = BeautifulSoup(r.text, "html.parser")
            except requests.RequestException:
                soup = None

            if soup is not None:
                for a in soup.select('a[href*="/products/"]'):
                    url = (
                        urljoin(
                            BASE_URL,
                            a.get("href") or "",
                        )
                        .split("?")[0]
                    )

                    if not url or url in seen:
                        continue

                    card = a
                    best_text = clean(
                        a.get_text(" ", strip=True)
                    )

                    for _ in range(7):
                        if card is None:
                            break

                        text = clean(
                            card.get_text(
                                " ",
                                strip=True,
                            )
                        )

                        if text:
                            best_text = text

                        identity = (
                            f"{text} "
                            f"{product_name_from_url(url)}"
                        )

                        if (
                            matches(identity, variant)
                            and "€" in text
                        ):
                            break

                        card = card.parent

                    identity = (
                        f"{best_text} "
                        f"{product_name_from_url(url)}"
                    )

                    if (
                        matches(identity, variant)
                        and not is_non_product(identity)
                    ):
                        seen.add(url)
                        urls.append(url)

            for url in shopify_suggest(
                session,
                variant,
            ):
                if url in seen:
                    continue

                identity = product_name_from_url(url)

                if (
                    matches(identity, variant)
                    and not is_non_product(identity)
                ):
                    seen.add(url)
                    urls.append(url)

        results = []

        for url in urls[:25]:
            item = product_page(
                session,
                url,
                query,
            )

            if item:
                results.append(item)

        return results

    finally:
        session.close()


def diagnose(query):
    query=clean(query)
    if not query:return {"diagnostic":True,"query":query,"error":"empty_query"}
    session=requests.Session()
    try:
        search_url=BASE_URL+"/search?q="+quote_plus(query)
        d={"diagnostic":True,"query":query,"search_url":search_url,"search":{},"candidate_count":0,"candidates":[],"product_pages":[]}
        try:
            r=session.get(search_url,headers=HEADERS,timeout=TIMEOUT)
            d["search"].update({"status":r.status_code,"final_url":r.url,"html_length":len(r.text or "")})
            soup=BeautifulSoup(r.text,"html.parser") if r.status_code==200 else BeautifulSoup("","html.parser")
            anchors=soup.find_all("a",href=True); links=[]; matching=[]; rejected=[]; seen=set()
            for a in soup.select('a[href*="/products/"]'):
                u=urljoin(BASE_URL,a.get("href") or "").split("?")[0]
                if u in seen:continue
                seen.add(u); label=clean(a.get_text(" ",strip=True)); card=a; matched=False; card_text=""
                for _ in range(7):
                    if card is None:break
                    card_text=clean(card.get_text(" ",strip=True))
                    if matches(card_text,query) and "€" in card_text:matched=True;break
                    card=card.parent
                links.append(u)
                (matching if matched else rejected).append({"url":u,"anchor_text":label,"card_text":card_text[:500]})
            d["search"].update({"anchor_count":len(anchors),"product_link_count":len(links),"matching_card_count":len(matching),"matching_cards":matching[:25],"rejected_product_links":rejected[:25]})
        except requests.RequestException as exc:d["search"]["error"]=f"{type(exc).__name__}: {exc}"
        urls=[]
        try:
            r=session.get(search_url,headers=HEADERS,timeout=TIMEOUT); r.raise_for_status(); soup=BeautifulSoup(r.text,"html.parser"); seen=set()
            for a in soup.select('a[href*="/products/"]'):
                url=urljoin(BASE_URL,a.get("href") or "").split("?")[0]
                if url in seen:continue
                card=a
                for _ in range(7):
                    if card is None:break
                    text=clean(card.get_text(" ",strip=True))
                    if matches(text,query) and "€" in text:break
                    card=card.parent
                if card is not None and matches(clean(card.get_text(" ",strip=True)),query):
                    seen.add(url);urls.append(url)
        except requests.RequestException as exc:d["discovery_error"]=f"{type(exc).__name__}: {exc}"
        d["candidate_count"]=len(urls); d["candidates"]=urls[:50]
        for u in urls[:15]:
            item={"url":u,"status":None,"final_url":None,"html_length":None,"product_name":None,"name_matches_query":False,"price_found":False,"accepted":False,"error":None}
            try:
                r=session.get(u,headers=HEADERS,timeout=TIMEOUT); item.update({"status":r.status_code,"final_url":r.url,"html_length":len(r.text or "")})
                if r.status_code==200:
                    soup=BeautifulSoup(r.text,"html.parser"); h=soup.find("h1"); name=clean(h.get_text(" ",strip=True)) if h else ""
                    item["product_name"]=name; item["name_matches_query"]=matches(name,query); item["price_found"]=price(soup.get_text(" ",strip=True)) is not None; item["accepted"]=bool(item["name_matches_query"] and item["price_found"])
            except requests.RequestException as exc:item["error"]=f"{type(exc).__name__}: {exc}"
            d["product_pages"].append(item)
        return d
    finally:session.close()

def scrape(query):
    return search(query)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generic ParfumCity store adapter")
    parser.add_argument("query")
    parser.add_argument("--diagnose", action="store_true")
    args = parser.parse_args()
    print(json.dumps(diagnose(args.query) if args.diagnose else search(args.query), ensure_ascii=False, indent=2))
