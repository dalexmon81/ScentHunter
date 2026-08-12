import re
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from urllib.parse import unquote

BASE_URL = "https://www.parfum-zentrum.de"
SITEMAP_URL = BASE_URL + "/sitemap.xml"

SESSION = requests.Session()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}

IGNORED_MATCH_WORDS = {
    "eau", "de", "parfum", "perfume", "edp", "edt",
    "spray", "ml", "pour", "for",
    "woman", "man", "men", "women",
}


# ------------------------------------------------------------
# Utility per matching nome → query
# ------------------------------------------------------------

def _tokens(text: str):
    return [
        x.lower()
        for x in re.findall(r"[A-Za-zÀ-ÿ0-9]+", unquote(text))
        if len(x) > 1
    ]


def _all_tokens_match(text: str, query: str) -> bool:
    text_tokens = set(_tokens(text))
    query_tokens = {
        token
        for token in _tokens(query)
        if token not in IGNORED_MATCH_WORDS
    }

    if not query_tokens:
        query_tokens = set(_tokens(query))

    if not query_tokens:
        return False

    return query_tokens.issubset(text_tokens)


# ------------------------------------------------------------
# Lettura sitemap → URL prodotti
# ------------------------------------------------------------

def _xml_urls(xml_text: str):
    root = ET.fromstring(xml_text)
    return [
        el.text.strip()
        for el in root.iter()
        if el.tag.endswith("loc") and el.text
    ]


def _get_sitemap_urls():
    r = SESSION.get(SITEMAP_URL, headers=HEADERS, timeout=5)

    if r.status_code in (403, 429):
        print(f"PARFUMZENTRUM BLOCKED: HTTP {r.status_code}")
        r.close()
        return []

    r.raise_for_status()
    xml_text = r.text
    r.close()
    urls = _xml_urls(xml_text)

    child_maps = [
        u for u in urls
        if "sitemap" in u.lower()
        and u.lower().endswith((".xml", ".xml.gz"))
    ]

    if not child_maps:
        return urls

    out = []

    for sm in child_maps:
        try:
            rr = SESSION.get(sm, headers=HEADERS, timeout=5)

            if rr.status_code in (403, 429):
                print(f"PARFUMZENTRUM SITEMAP BLOCKED: HTTP {rr.status_code}")
                rr.close()
                break

            if rr.status_code == 200:
                xml_text = rr.text
                rr.close()
                out.extend(_xml_urls(xml_text))
            else:
                rr.close()
        except Exception:
            pass

    return out


# ------------------------------------------------------------
# Utility prezzi/formati
# ------------------------------------------------------------

def _extract_number(text: str):
    """
    Restituisce '52,30' da '52,30 €'.
    """
    m = re.search(r"(\d{1,4}[.,]\d{2})\s*€", text)
    if not m:
        return None
    # Parfumzentrum usa sia . che ,: normalizziamo a virgola
    return m.group(1).replace(".", ",")


def _is_coupon_block(text: str) -> bool:
    """
    True se il blocco rappresenta un prezzo con codice/coupon.
    """
    t = text.lower()
    if "preis inkl. code" in t:
        return True
    if "rabattcode" in t:
        return True
    if "gutschein" in t:
        return True
    if "code:" in t or "code " in t:
        return True
    return False


def _is_unavailable(soup: BeautifulSoup) -> bool:
    unavailable_phrases = (
        "leider nicht lieferbar",
        "nicht lieferbar",
        "nicht vorrätig",
        "ausverkauft",
    )
    txt = soup.get_text(" ", strip=True).lower()
    return any(p in txt for p in unavailable_phrases)


# ------------------------------------------------------------
# Estrazione varianti da pagina prodotto
# ------------------------------------------------------------

def _extract_variants(soup: BeautifulSoup, product_name: str, url: str):
    """
    Estrae tutte le varianti di formato per il prodotto:

    Ritorna una lista di dict:
      {
          "store": "ParfumZentrum",
          "name": product_name,
          "size_ml": "100",
          "price": "52,30€",
          "url": url,
      }
    """

    variants = []

    # Heuristica: i box dei formati includono 'ml' e uno o più prezzi "€".
    # Scandiamo il DOM e identifichiamo i container che contengono 'ml' + '€'.
    candidate_boxes = []

    for tag in soup.find_all(True):
        txt = tag.get_text(" ", strip=True)
        if "ml" in txt and "€" in txt:
            candidate_boxes.append(tag)

    processed_ids = set()

    for box in candidate_boxes:
        if id(box) in processed_ids:
            continue
        processed_ids.add(id(box))

        full_text = box.get_text(" ", strip=True)

        # Salta box coupon (es. "51,22 € Preis inkl. Code SALE5DE")
        if _is_coupon_block(full_text):
            continue

        # Trova dimensione formato
        size_match = re.search(r"(\d{1,4})\s*ml\b", full_text, re.I)
        if not size_match:
            continue
        size_ml = size_match.group(1)

        # Cerca il prezzo corrente: prende il primo prezzo non barrato.
        current_price = None

        # 1) cerca elementi che contengono '€' ma il parent NON è barrato.
        for el in box.find_all(string=re.compile(r"€")):
            parent = el.parent

            # prezzo barrato in <s>/<del> → scarta
            if parent.name in ("s", "del"):
                continue

            style = (parent.get("style", "") or "").lower()
            if "line-through" in style.replace(" ", ""):
                continue

            # testo completo del nodo
            price_text = parent.get_text(" ", strip=True)
            num = _extract_number(price_text)
            if not num:
                continue

            current_price = num
            break

        # 2) se non siamo riusciti a trovare via DOM, fallback: primo numero nel testo intero
        if not current_price:
            nums = re.findall(r"(\d{1,4}[.,]\d{2})\s*€", full_text)
            if nums:
                current_price = nums[0].replace(".", ",")

        if not current_price:
            continue

        variants.append(
            {
                "store": "ParfumZentrum",
                "name": product_name,
                "size_ml": size_ml,
                "price": current_price + "€",
                "url": url,
            }
        )

    return variants


# ------------------------------------------------------------
# Estrazione prodotto singolo (pagina)
# ------------------------------------------------------------

def _extract_product(url: str, query: str):
    r = SESSION.get(url, headers=HEADERS, timeout=5)

    if r.status_code in (403, 429):
        print(f"PARFUMZENTRUM PRODUCT BLOCKED: HTTP {r.status_code}")
        r.close()
        return []
    if r.status_code != 200:
        r.close()
        return []

    html = r.text
    r.close()

    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    if not h1:
        return []

    name = " ".join(h1.stripped_strings)
    if not _all_tokens_match(name, query):
        return []

    if _is_unavailable(soup):
        return []

    variants = _extract_variants(soup, name, url)
    return variants


# ------------------------------------------------------------
# Entry point pubblico
# ------------------------------------------------------------

def search(query: str):
    """
    Ritorna una lista di offerte Parfumzentrum per quel prodotto,
    una per formato:

    [
      {
        "store": "ParfumZentrum",
        "name": "...",
        "size_ml": "50",
        "price": "36,75€",
        "url": "https://...",
      },
      {
        "store": "ParfumZentrum",
        "name": "...",
        "size_ml": "100",
        "price": "52,30€",
        "url": "https://...",
      },
      ...
    ]
    """
    try:
        urls = _get_sitemap_urls()
    except Exception as e:
        print("ERRORE SITEMAP:", e)
        return []

    candidates = []

    for url in urls:
        # Pagina prodotto tipo ..._z696243/
        if re.search(r"_z\d+/?$", url) and _all_tokens_match(url, query):
            candidates.append(url)

    results = []
    seen = set()

    try:
        for url in candidates[:6]:
            try:
                variants = _extract_product(url, query)
            except Exception:
                variants = []

            for v in variants:
                key = (v["name"].lower(), v["size_ml"], v["url"])
                if key in seen:
                    continue
                seen.add(key)
                results.append(v)
    finally:
        SESSION.close()

    return results


# ------------------------------------------------------------
# Test manuale
# ------------------------------------------------------------

if __name__ == "__main__":
    q = "Versace Eros pour Femme Eau de Toilette"
    res = search(q)
    print("RISULTATI:", len(res))
    for item in res:
        print(item)
