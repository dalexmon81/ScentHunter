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
    return bool(q) and q.issubset(set(tokens(text)))

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
    if not name or not matches(name, query):
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
        r = session.get(BASE_URL + "/search?q=" + quote_plus(query), headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        urls, seen = [], set()
        for a in soup.select('a[href*="/products/"]'):
            url = urljoin(BASE_URL, a.get("href") or "").split("?")[0]
            if url in seen:
                continue
            card = a
            for _ in range(7):
                if card is None:
                    break
                text = clean(card.get_text(" ", strip=True))
                if matches(text, query) and "€" in text:
                    break
                card = card.parent
            if card is None:
                continue
            if matches(clean(card.get_text(" ", strip=True)), query):
                seen.add(url)
                urls.append(url)
        results = []
        for url in urls[:15]:
            item = product_page(session, url, query)
            if item:
                results.append(item)
        return results
    except requests.RequestException:
        return []
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
