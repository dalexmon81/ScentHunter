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


# ScentHunter routing rule:
# These three stores are Arabic-fragrance specialists. They should NOT be
# queried for clearly identified designer / niche brands. Unknown brands are
# intentionally NOT blocked, so a new Arabic brand is never lost.
NON_ARABIC_BRANDS = {
    "acqua di parma", "aerin", "amouage", "armani", "azzaro", "bdk",
    "bdk parfums", "bentley", "biotherm", "boucheron", "burberry",
    "bvlgari", "bulgari", "byredo", "calvin klein", "carolina herrera",
    "cartier", "chanel", "chloe", "chloé", "clinique", "coach",
    "comptoir sud pacifique", "creed", "david beckham", "dior",
    "diptyque", "dolce & gabbana", "dolce gabbana", "dunhill",
    "elizabeth arden", "elie saab", "emilio pucci", "estee lauder",
    "estée lauder", "etat libre d'orange", "fragrance du bois",
    "frederic malle", "frederic malle", "givenchy", "guerlain",
    "gucci", "hugo boss", "issey miyake", "jaguar", "jean paul gaultier",
    "jil sander", "jimmy choo", "jo malone", "jovan", "juliette has a gun",
    "kenzo", "kilian", "la mer", "lalique", "lancome", "lancôme",
    "lanvin", "le labo", "loewe", "lorenzo villoresi", "maison crivelli",
    "maison francis kurkdjian", "maison margiela", "marc jacobs",
    "mancera", "mariah carey", "memo paris", "michael kors", "miller harris",
    "montblanc", "moschino", "mugler", "narciso rodriguez", "nars",
    "nautica", "nishane", "paco rabanne", "parfums de marly", "philosophy",
    "prada", "ralph lauren", "revlon", "roberto cavalli", "roger & gallet",
    "salvatore ferragamo", "serge lutens", "shiseido", "sisley",
    "snif", "tom ford", "tommy hilfiger", "trussardi", "valentino",
    "van cleef & arpels", "versace", "viktor & rolf", "vilhelm parfumerie",
    "yves saint laurent", "ysl", "zadig & voltaire", "zara",
    "xerjoff", "ex nihilo", "initio", "ormonde jayne", "penhaligon's",
    "penhaligons", "roja", "roja parfums", "the merchant of venice",
    "tiziana terenzi", "nasomatto", "ortho parisi", "parle moi de parfum",
    "atelier des ors", "bdk parfums", "bois 1920", "carner barcelona",
    "essential parfums", "histoires de parfums", "laboratorio olfattivo",
    "liquides imaginaires", "mancera", "montale", "parle moi de parfum",
    "profumum roma", "room 1015", "state of mind", "une nuit nomade",
}

def _is_non_arabic_brand_query(query):
    """Return True only for a clearly recognized designer/niche brand.

    We deliberately do not guess from unknown names. The three Arabic-only
    stores are skipped only when the query contains a known non-Arabic brand.
    """
    text = norm(query) if "norm" in globals() else clean(query).lower()
    text = re.sub(r"\s+", " ", text).strip()
    return any(
        re.search(r"(?<![a-z0-9])" + re.escape(norm(brand)) + r"(?![a-z0-9])", text)
        for brand in NON_ARABIC_BRANDS
    )


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

    if _is_non_arabic_brand_query(query):
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

def scrape(query):
    return search(query)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generic ParfumCity store adapter")
    parser.add_argument("query")
    args = parser.parse_args()
    print(json.dumps(search(args.query), ensure_ascii=False, indent=2))
