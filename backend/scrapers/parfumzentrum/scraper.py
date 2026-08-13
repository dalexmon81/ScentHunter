import re
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from urllib.parse import unquote

BASE_URL = "https://www.parfum-zentrum.de"
SITEMAP_URL = BASE_URL + "/sitemap.xml"

SESSION = requests.Session()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}

IGNORED_MATCH_WORDS = {
    "eau", "de",
    "spray", "ml", "pour", "for",
}

def _concentration(text):
    """Return the concentration explicitly requested/present in text."""
    value = unquote(str(text or ""))
    if re.search(r"\beau\s+de\s+toilette\b|\bedt\b", value, re.I):
        return "edt"
    if re.search(r"\beau\s+de\s+parfum\b|\bedp\b", value, re.I):
        return "edp"
    if re.search(r"\bextrait(?:\s+de\s+parfum)?\b", value, re.I):
        return "extrait"
    return ""

def _tokens(text):
    return [
        x.lower()
        for x in re.findall(r"[A-Za-zÀ-ÿ0-9]+", unquote(text))
        if len(x) > 1
    ]

def _all_tokens_match(text, query):
    text_tokens = set(_tokens(text))
    query_tokens = {
        token
        for token in _tokens(query)
        if token not in IGNORED_MATCH_WORDS
    }

    if not query_tokens:
        return False

    if not query_tokens.issubset(text_tokens):
        return False

    # Generic searches must allow both EDT and EDP.
    # If the user explicitly requests a concentration, enforce it.
    wanted_concentration = _concentration(query)
    if wanted_concentration:
        return _concentration(text) == wanted_concentration

    return True

def _xml_urls(xml_text):
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

def _format_price(value):
    """
    Normalizza un prezzo in euro.
    Gestisce valori come:
    69.95 / 69,95 / 69.95 € / 1.149,80
    """
    raw = str(value or "").strip()
    if not raw:
        return ""

    raw = raw.replace("\xa0", " ").strip()
    m = re.search(r"\d[\d.,]*", raw)
    if not m:
        return ""

    number = m.group(0)

    # Formato europeo: 1.149,80
    if "," in number:
        if "." in number:
            number = number.replace(".", "").replace(",", ".")
        else:
            number = number.replace(",", ".")
    # Formato decimale semplice: 69.95
    elif number.count(".") == 1:
        left, right = number.split(".")
        if len(right) != 2:
            number = number.replace(".", "")
    # Separatore migliaia senza decimali: 1.149
    elif number.count(".") > 1:
        number = number.replace(".", "")

    try:
        value_float = float(number)
    except ValueError:
        return ""

    if value_float <= 0:
        return ""

    return f"{value_float:.2f}".replace(".", ",") + "€"


def _extract_price_from_html(html):
    """
    Estrae il prezzo di vendita reale.
    Ordine:
      1) JSON-LD Product/Offer
      2) meta price
      3) prezzo visibile vicino al prodotto
    Non usa il Grundpreis €/l come prezzo del prodotto.
    """
    soup = BeautifulSoup(html or "", "html.parser")

    # 1) JSON-LD: è la fonte più affidabile.
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        if not raw:
            continue

        try:
            data = __import__("json").loads(raw)
        except Exception:
            continue

        stack = data if isinstance(data, list) else [data]

        while stack:
            item = stack.pop(0)

            if isinstance(item, list):
                stack.extend(item)
                continue

            if not isinstance(item, dict):
                continue

            item_type = str(item.get("@type", "")).lower()

            if item_type == "product" or "offers" in item:
                offers = item.get("offers")
                offer_list = offers if isinstance(offers, list) else [offers]

                for offer in offer_list:
                    if not isinstance(offer, dict):
                        continue

                    for key in ("price", "lowPrice"):
                        price = _format_price(offer.get(key))
                        if price:
                            return price

            for key in ("mainEntity", "item", "@graph"):
                child = item.get(key)
                if child:
                    if isinstance(child, list):
                        stack.extend(child)
                    else:
                        stack.append(child)

    # 2) Meta prezzo strutturato.
    for attrs in (
        {"property": "product:price:amount"},
        {"property": "og:price:amount"},
        {"itemprop": "price"},
    ):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            price = _format_price(tag["content"])
            if price:
                return price

    # 3) Prezzo visibile.
    # Prima cerchiamo contenitori che abbiano il simbolo € ma NON
    # la dicitura Grundpreis (prezzo per litro).
    for node in soup.find_all(["div", "span", "p", "strong", "b"]):
        txt = node.get_text(" ", strip=True)
        if not txt or "€" not in txt:
            continue

        low = txt.lower()
        if "grundpreis" in low or "€/l" in low or "pro liter" in low:
            continue

        # Prezzo con esattamente due decimali.
        m = re.search(r"(?<![\d.,])(\d{1,4}(?:[.,]\d{2}))(?:\s*€)", txt)
        if m:
            price = _format_price(m.group(1))
            if price:
                return price

    # 4) Ultimo fallback sul testo della pagina.
    text_content = soup.get_text(" ", strip=True)
    patterns = [
        r"(\d{1,4}[.,]\d{2})\s*€\s*inkl\.",
        r"(\d{1,4}[.,]\d{2})\s*€",
    ]

    for pattern in patterns:
        for m in re.finditer(pattern, text_content, re.I):
            # Ignora prezzi per litro.
            left = text_content[max(0, m.start() - 100):m.start()].lower()
            if "grundpreis" in left or "pro liter" in left:
                continue

            price = _format_price(m.group(1))
            if price:
                return price

    return ""


def _extract_product(url, query):
    try:
        r = SESSION.get(url, headers=HEADERS, timeout=6)
    except Exception:
        return None

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

    # Il formato e la concentrazione devono viaggiare con l'offerta.
    # Parfum-Zentrum espone entrambe le informazioni nel titolo H1, per esempio:
    # "Eros pour Femme Eau De Toilette 100 ml (woman)".
    size_match = re.search(r"(?<!\\d)(\\d{1,4})\\s*ml\\b", name, re.I)
    size_ml = int(size_match.group(1)) if size_match else None

    concentration = ""
    if re.search(r"\\beau\\s+de\\s+toilette\\b|\\bedt\\b", name, re.I):
        concentration = "Eau de Toilette"
    elif re.search(r"\\beau\\s+de\\s+parfum\\b|\\bedp\\b", name, re.I):
        concentration = "Eau de Parfum"
    elif re.search(r"\\bextrait(?:\\s+de\\s+parfum)?\\b", name, re.I):
        concentration = "Extrait de Parfum"

    # Il controllo definitivo resta sul nome reale del prodotto.
    if not _all_tokens_match(name, query):
        return None

    unavailable_phrases = (
        "leider nicht lieferbar",
        "nicht lieferbar",
        "nicht vorrätig",
        "ausverkauft",
    )

    page_near_h1 = soup.get_text(" ", strip=True).lower()

    if any(x in page_near_h1 for x in unavailable_phrases):
        return None

    price = _extract_price_from_html(html)

    if not price:
        return None

    return {
        "store": "ParfumZentrum",
        "name": name,
        "price": price,
        "url": url,
        "size_ml": size_ml,
        "concentration": concentration,
    }


def _candidate_score(url, query):
    """
    Ordina i candidati sitemap mettendo davanti quelli più vicini
    alla query. Non basta più prendere i primi URL della sitemap.
    """
    q = [
        t for t in _tokens(query)
        if t not in IGNORED_MATCH_WORDS
    ]
    u = _tokens(url)

    score = sum(10 for token in q if token in u)

    normalized_query = " ".join(q)
    normalized_url = " ".join(u)

    if normalized_query and normalized_query in normalized_url:
        score += 40

    # Bonus per sequenza dei token.
    if q:
        joined = " ".join(u)
        if all(token in joined for token in q):
            score += len(q)

    wanted_concentration = _concentration(query)
    if wanted_concentration == "edt":
        if "toilette" in u or "edt" in u:
            score += 60
    elif wanted_concentration == "edp":
        if "parfum" in u or "edp" in u:
            score += 60
    elif wanted_concentration == "extrait":
        if "extrait" in u:
            score += 60

    return score


def search(query):
    query = (query or "").strip()

    if not query:
        return []

    try:
        urls = _get_sitemap_urls()
    except Exception as e:
        print("ERRORE SITEMAP:", e)
        return []

    # Discovery generica:
    # non limitiamo più la verifica ai primi 6 URL della sitemap.
    # Prima raccogliamo TUTTI i candidati che contengono i token
    # significativi della query, poi li ordiniamo per pertinenza.
    candidates = []

    for url in urls:
        if not re.search(r"_z\d+/?$", url):
            continue

        if _all_tokens_match(url, query):
            candidates.append(url)

    candidates.sort(
        key=lambda u: _candidate_score(u, query),
        reverse=True,
    )

    # Limite alto ma controllato: evita una scansione enorme senza
    # perdere prodotti validi che nella sitemap non sono nei primi 6.
    candidates = candidates[:24]

    results = []
    seen = set()

    try:
        for url in candidates:
            try:
                item = _extract_product(url, query)
            except Exception as e:
                print("ERRORE PRODOTTO PARFUMZENTRUM:", repr(e))
                item = None

            if item:
                key = (
                    item["name"].lower(),
                    item["price"],
                )

                if key not in seen:
                    seen.add(key)
                    results.append(item)
    finally:
        SESSION.close()

    return results

if __name__ == "__main__":
    results = search("Khadlaj Onyx Gold")
    print("RISULTATI:", len(results))

    for item in results[:10]:
        print(item)
