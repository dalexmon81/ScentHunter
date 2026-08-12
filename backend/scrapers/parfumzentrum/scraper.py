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


def _xml_urls(xml_text: str):
    root = ET.fromstring(xml_text)
    return [
        el.text.strip()
        for el in root.iter()
        if el.tag.endswith("loc") and el.text
    ]


def _get_sitemap_urls():
    r = SESSION.get(SITEMAP_URL, headers=HEADERS, timeout=4)

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
            rr = SESSION.get(sm, headers=HEADERS, timeout=4)

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


def _extract_number(text: str):
    """
    Restituisce '52,30' da '52,30 €', ecc.
    """
    m = re.search(r"(\d{1,4}[.,]\d{2})\s*€", text)
    if not m:
        return None
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
    # se vogliamo essere super sicuri sui codici tipo SALE5DE:
    if re.search(r"[a-z]{4,}\d{0,2}", t) and "code" in t:
        return True
    return False


def _extract_variants(soup: BeautifulSoup):
    """
    Estrarre lista di {size_ml, price} per i vari formati (30/50/100 ml, etc).
    Regole:
    - prezzo corrente visibile → usare
    - prezzo barrato (strike/del/s) → NON usare
    - blocchi 'Preis inkl. Code' / 'Rabattcode' → NON usare
    """
    variants = []

    # Heuristica: i box dei formati sono tipicamente blocchi con il testo 'ml'
    # e contengono prezzi. Cerchiamo elementi che nel testo contengono 'ml' e '€'.
    candidate_boxes = []

    for tag in soup.find_all(True):
        txt = tag.get_text(" ", strip=True)
        if "ml" in txt and "€" in txt:
            candidate_boxes.append(tag)

    seen_boxes = set()

    for box in candidate_boxes:
        # Evita di processare lo stesso box più volte
        box_id = id(box)
        if box_id in seen_boxes:
            continue
        seen_boxes.add(box_id)

        full_text = box.get_text(" ", strip=True)
        if _is_coupon_block(full_text):
            # è il blocco tipo "51,22 € Preis inkl. Code"
            continue

        # Trova la dimensione (es. '50 ml', '100 ml')
        size_match = re.search(r"(\d{1,4})\s*ml\b", full_text, re.I)
        if not size_match:
            continue

        size_ml = size_match.group(1)

        # Cerchiamo prezzi nei figli del box, ignorando quelli barrati
        current_price = None

        # 1) cerca elementi che NON siano <s>/<del> e NON abbiano stile line-through
        for el in box.find_all(string=re.compile(r"€")):
            parent = el.parent

            # se il parent è s/del → barrato
            if parent.name in ("s", "del"):
                continue

            style = parent.get("style", "") or ""
            if "line-through" in style.replace(" ", "").lower():
                # testo barrato via CSS
                continue

            price_text = parent.get_text(" ", strip=True)
            num = _extract_number(price_text)
            if not num:
                continue

            # prima occorrenza "sana" → la prendiamo come prezzo corrente
            current_price = num
            break

        # 2) se non abbiamo trovato nulla, fallback: primo numero non barrato nel testo
        if not current_price:
            numbers = []
            # prende tutte le occorrenze, ma poi filtriamo a livello di testo
            for m in re.finditer(r"(\d{1,4}[.,]\d{2})\s*€", full_text):
                numbers.append(m.group(1))

            if numbers:
                current_price = numbers[0].replace(".", ",")

        if not current_price:
            continue

        variants.append(
            {
                "size_ml": size_ml,
                "price": current_price + "€",
            }
        )

    return variants


def _extract_product(url: str, query: str):
    r = SESSION.get(url, headers=HEADERS, timeout=4)

    if r.status_code in (403, 429):
        print(f"PARFUMZENTRUM PRODUCT BLOCKED: HTTP {r.status_code}")
        r.close()
        return None

    if r.status_code != 200:
        r.close()
        return None

    html = r.text
    r.close()

    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")

    if not h1:
        return None

    name = " ".join(h1.stripped_strings)

    if not _all_tokens_match(name, query):
        return None

    # verifica disponibilità
    unavailable_phrases = (
        "leider nicht lieferbar",
        "nicht lieferbar",
        "nicht vorrätig",
        "ausverkauft",
    )

    # testo vicino all'H1 per capire se è esaurito
    chunks = []
    node = h1

    for _ in range(8):
        if not node:
            break
        txt = node.get_text(" ", strip=True)
        if txt:
            chunks.append(txt)
        node = node.parent

    page_near_h1 = " ".join(chunks[:5]).lower()
    if any(x in page_near_h1 for x in unavailable_phrases):
        return None

    # --- NUOVA LOGICA: estrazione varianti ---
    variants = _extract_variants(soup)

    if not variants:
        # fallback: logica vecchia, ma solo per non perdere il prodotto
        product_text = min(
            (x for x in chunks if len(x) >= len(name) and "€" in x),
            key=len,
            default="",
        )
        price = ""
        patterns = [
            r"(\d{1,4}[.,]\d{2})\s*€\s*inkl\.",
            r"Versandbereit\s*(\d{1,4}[.,]\d{2})\s*€",
            r"(\d{1,4}[.,]\d{2})\s*€",
        ]
        for pattern in patterns:
            m = re.search(pattern, product_text, re.I)
            if m:
                price = m.group(1).replace(".", ",") + "€"
                break

        if not price:
            return None

        # variante fittizia "std"
        variants = [{"size_ml": None, "price": price}]

    # ritorno compatibile con il resto di ScentHunter:
    # per ora prendo la variante con prezzo minimo come "entry" principale.
    main_variant = min(variants, key=lambda v: float(v["price"].split("€")[0].replace(",", ".")))

    return {
        "store": "ParfumZentrum",
        "name": name,
        "price": main_variant["price"],
        "url": url,
        "variants": variants,  # formato → prezzo (30/50/100 ml)
    }


def search(query: str):
    try:
        urls = _get_sitemap_urls()
    except Exception as e:
        print("ERRORE SITEMAP:", e)
        return []

    candidates = []

    for url in urls:
        if re.search(r"_z\d+/?$", url) and _all_tokens_match(url, query):
            candidates.append(url)

    results = []
    seen = set()

    try:
        for url in candidates[:6]:
            try:
                item = _extract_product(url, query)
            except Exception:
                item = None

            if item:
                key = (item["name"].lower(), item["url"])
                if key not in seen:
                    seen.add(key)
                    results.append(item)
    finally:
        SESSION.close()

    return results


if __name__ == "__main__":
    results = search("Versace Eros pour Femme Eau de Toilette")
    print("RISULTATI:", len(results))
    for item in results[:10]:
        print(item)
