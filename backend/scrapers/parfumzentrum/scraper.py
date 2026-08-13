mport re
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
    "eau", "de", "parfum", "perfume", "edp", "edt",
    "spray", "ml", "pour", "for",
}

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
        query_tokens = set(_tokens(query))

    if not query_tokens:
        return False

    return query_tokens.issubset(text_tokens)

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


def _is_old_or_discount_node(tag):
    if tag is None:
        return False
    name = getattr(tag, "name", "") or ""
    if name in ("del", "s", "strike"):
        return True
    classes = " ".join(tag.get("class") or []).lower()
    if any(word in classes for word in (
        "old", "list-price", "listprice", "compare", "strike",
        "cross", "was", "uvp", "previous", "regular-price",
    )):
        return True
    style = (tag.get("style") or "").replace(" ", "").lower()
    return "line-through" in style or "text-decoration:line-through" in style


def _contains_old_or_discount_descendant(tag):
    if tag is None:
        return False
    for child in tag.find_all(True):
        if _is_old_or_discount_node(child):
            return True
    return False


def _price_candidate_score(tag, text):
    classes = " ".join(tag.get("class") or []).lower()
    score = 0
    if tag.get("itemprop") == "price":
        score += 120
    if tag.get("content"):
        score += 15
    for word, points in (
        ("product-detail-price", 100),
        ("product-price", 80),
        ("current-price", 80),
        ("final-price", 80),
        ("price", 30),
    ):
        if word in classes:
            score += points
    if tag.name in ("strong", "b"):
        score += 10
    low = text.lower()
    if any(x in low for x in ("inkl. code", "rabattcode", "gutschein", "coupon")):
        score -= 1000
    return score


def _extract_price_from_html(html):
    """
    Estrae il prezzo corrente della singola pagina prodotto.
    Scarta prezzi barrati/listino, coupon e prezzi per litro.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    h1 = soup.find("h1")
    containers = []
    if h1:
        node = h1
        for _ in range(6):
            if node is None:
                break
            text = node.get_text(" ", strip=True)
            if "€" in text:
                containers.append(node)
            node = getattr(node, "parent", None)
    if not containers:
        containers = [soup]

    candidates = []
    for container in containers:
        for tag in container.find_all(True):
            if _is_old_or_discount_node(tag):
                continue
            if _contains_old_or_discount_descendant(tag):
                continue
            text = tag.get_text(" ", strip=True)
            if not text or "€" not in text or len(text) > 900:
                continue
            low = text.lower()
            if any(x in low for x in (
                "grundpreis", "pro liter", "€/l", "/ l",
                "inkl. code", "rabattcode", "gutschein", "coupon",
            )):
                continue
            matches = re.findall(
                r"(?<![\d.,])(\d{1,4}(?:[.,]\d{2}))(?:\s*€)",
                text,
            )
            for raw_value in matches:
                price = _format_price(raw_value)
                if price:
                    score = _price_candidate_score(tag, text)
                    score -= min(len(text), 300) / 1000.0
                    candidates.append((score, len(text), price))
        if candidates:
            break

    if candidates:
        candidates.sort(key=lambda x: (-x[0], x[1]))
        return candidates[0][2]

    for tag in soup.find_all(["meta", "span", "div", "strong", "b"]):
        if _is_old_or_discount_node(tag):
            continue
        content = tag.get("content") or tag.get_text(" ", strip=True)
        if tag.get("itemprop") == "price" and content:
            price = _format_price(content)
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
    size_match = re.search(r"(?<!\d)(\d{1,4})\s*ml\b", name, re.I)
    size_ml = int(size_match.group(1)) if size_match else None

    concentration = ""
    if re.search(r"\beau\s+de\s+toilette\b|\bedt\b", name, re.I):
        concentration = "Eau de Toilette"
    elif re.search(r"\beau\s+de\s+parfum\b|\bedp\b", name, re.I):
        concentration = "Eau de Parfum"
    elif re.search(r"\bextrait(?:\s+de\s+parfum)?\b", name, re.I):
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
