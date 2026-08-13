import json
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

COUPON_WORDS = (
    "preis inkl. code",
    "rabattcode",
    "gutschein",
    "coupon",
    "promo",
    "aktion",
    "code",
)

OLD_PRICE_CLASS_WORDS = (
    "old", "was", "strike", "compare", "cross",
    "previous", "original",
)


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
                continue

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
    m = re.search(r"(\d{1,4}[.,]\d{2})\s*€", text)
    if not m:
        return None
    return m.group(1).replace(".", ",")


def _is_coupon_text(text: str) -> bool:
    t = (text or "").lower()
    return any(word in t for word in COUPON_WORDS)


def _has_old_price_marker(tag) -> bool:
    if tag is None:
        return False

    if getattr(tag, "name", None) in ("del", "s", "strike"):
        return True

    classes = " ".join(tag.get("class") or []).lower()
    if any(word in classes for word in OLD_PRICE_CLASS_WORDS):
        return True

    style = (tag.get("style") or "").replace(" ", "").lower()
    return "line-through" in style or "text-decoration:line-through" in style


def _node_is_coupon_or_old(tag) -> bool:
    if tag is None:
        return False

    node = tag

    # Controlliamo i marker di prezzo barrato lungo il contesto DOM,
    # ma il testo coupon solo sul nodo stesso. Il testo del parent può
    # contenere un coupon fratello e un prezzo valido insieme.
    for _ in range(4):
        if node is None:
            break

        if _has_old_price_marker(node):
            return True

        if node is tag and _is_coupon_text(node.get_text(" ", strip=True)):
            return True

        node = getattr(node, "parent", None)

    return False


def _extract_current_price(container):
    """
    Estrae SOLO un prezzo corrente dal contenitore della singola variante.

    Priorità:
      1. prezzo in un elemento dedicato, non barrato/non coupon
      2. testo diretto non barrato/non coupon

    Non usa mai il primo numero trovato in un blocco generico.
    """
    candidates = []

    for tag in container.find_all(True):
        if _node_is_coupon_or_old(tag):
            continue

        candidate = (
            tag.get("content")
            or tag.get("data-price")
            or tag.get("data-product-price")
            or tag.get("data-final-price")
            or tag.get_text(" ", strip=True)
        )

        if not candidate or "€" not in candidate:
            continue

        classes = " ".join(tag.get("class") or []).lower()
        score = 0

        if tag.get("itemprop") == "price":
            score += 100
        if any(x in classes for x in ("price", "product-price", "current", "final")):
            score += 50
        if tag.name in ("span", "strong", "b"):
            score += 10

        value = _extract_number(candidate)
        if value:
            candidates.append((score, len(candidate), value))

    if candidates:
        candidates.sort(key=lambda x: (-x[0], x[1]))
        return candidates[0][2]

    pieces = []
    for string in container.stripped_strings:
        parent = getattr(string, "parent", None)
        if _node_is_coupon_or_old(parent):
            continue
        text = str(string)
        if "€" in text:
            value = _extract_number(text)
            if value:
                pieces.append(value)

    return pieces[0] if pieces else None


def _size_tokens(text: str):
    return [
        int(m.group(1))
        for m in re.finditer(r"\b(\d{1,4})\s*ml\b", text or "", re.I)
    ]


def _extract_variants(soup: BeautifulSoup):
    """
    Associa formato -> prezzo cercando il più piccolo contenitore DOM che:
      - contiene esattamente un formato (es. 50 ml)
      - contiene un prezzo
      - non confonde il prezzo barrato con quello corrente.

    Un coupon fratello non invalida la variante: viene ignorato a livello
    del singolo nodo prezzo.
    """
    by_size = {}
    candidates = []

    for tag in soup.find_all(True):
        text = tag.get_text(" ", strip=True)

        if "ml" not in text or "€" not in text:
            continue

        sizes = sorted(set(_size_tokens(text)))
        if len(sizes) != 1:
            continue

        if len(text) > 1200:
            continue

        size = sizes[0]
        price = _extract_current_price(tag)
        if not price:
            continue

        candidates.append((size, len(text), tag, price))

    candidates.sort(key=lambda row: row[1])

    for size, _, _, price in candidates:
        if size not in by_size:
            by_size[size] = {
                "size_ml": str(size),
                "price": price + "€",
            }

    return [
        by_size[size]
        for size in sorted(by_size)
    ]


def _canonical_name(name: str) -> str:
    name = re.sub(r"\s+\d{1,4}\s*ml\b", "", name, flags=re.I)
    name = re.sub(r"\s+\(\s*woman\s*\)", "", name, flags=re.I)
    name = re.sub(r"\s+\(\s*man\s*\)", "", name, flags=re.I)
    name = re.sub(r"\s+", " ", name).strip()
    return name


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

    raw_name = " ".join(h1.stripped_strings)

    if not _all_tokens_match(raw_name, query):
        return None

    unavailable_phrases = (
        "leider nicht lieferbar",
        "nicht lieferbar",
        "nicht vorrätig",
        "ausverkauft",
    )

    chunks = []
    node = h1

    for _ in range(5):
        if not node:
            break
        txt = node.get_text(" ", strip=True)
        if txt:
            chunks.append(txt)
        node = node.parent

    page_near_h1 = " ".join(chunks).lower()

    if any(x in page_near_h1 for x in unavailable_phrases):
        return None

    name = _canonical_name(raw_name)

    variants = _extract_variants(soup)

    if not variants:
        target_size = re.search(r"\b(\d{1,4})\s*ml\b", raw_name, re.I)
        target_size = target_size.group(1) if target_size else None

        price = None

        if target_size:
            for tag in soup.find_all(True):
                text = tag.get_text(" ", strip=True)
                if (
                    f"{target_size} ml".lower() in text.lower()
                    and "€" in text
                    and len(text) <= 500
                    and len(set(_size_tokens(text))) == 1
                ):
                    price = _extract_current_price(tag)
                    if price:
                        break

        if not price:
            return None

        variants = [{
            "size_ml": target_size,
            "price": price + "€",
        }]

    def numeric(v):
        return float(v["price"].replace("€", "").replace(",", "."))

    main_variant = min(variants, key=numeric)

    return {
        "store": "ParfumZentrum",
        "name": name,
        "price": main_variant["price"],
        "url": url,
        "variants": variants,
    }


def _merge_product(existing, new):
    variants = list(existing.get("variants") or [])

    for variant in new.get("variants") or []:
        key = str(variant.get("size_ml") or "")
        old = next(
            (v for v in variants if str(v.get("size_ml") or "") == key),
            None,
        )

        if old is None:
            variants.append(dict(variant))
        else:
            old_price = _extract_number(old.get("price", ""))
            new_price = _extract_number(variant.get("price", ""))
            if old_price is None or (
                new_price is not None and new_price < old_price
            ):
                old["price"] = variant["price"]

    variants.sort(
        key=lambda v: int(re.sub(r"\D", "", str(v.get("size_ml") or "0")) or 0)
    )

    existing["variants"] = variants

    if variants:
        main = min(
            variants,
            key=lambda v: float(
                v["price"].replace("€", "").replace(",", ".")
            ),
        )
        existing["price"] = main["price"]

    return existing


def _candidate_score(url, query):
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

    if q:
        joined = " ".join(u)
        if all(token in joined for token in q):
            score += len(q)

    return score


def search(query: str):
    query = (query or "").strip()

    if not query:
        return []

    try:
        urls = _get_sitemap_urls()
    except Exception as e:
        print("ERRORE SITEMAP:", e)
        return []

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

    candidates = candidates[:24]

    results_by_name = {}

    try:
        for url in candidates:
            try:
                item = _extract_product(url, query)
            except Exception as exc:
                print(f"PARFUMZENTRUM PRODUCT ERROR url={url} err={exc}")
                item = None

            if not item:
                continue

            key = re.sub(r"\s+", " ", item["name"].lower()).strip()

            if key in results_by_name:
                _merge_product(results_by_name[key], item)
            else:
                results_by_name[key] = item

    finally:
        SESSION.close()

    return list(results_by_name.values())


if __name__ == "__main__":
    results = search("Versace Eros pour Femme Eau de Toilette")
    print("RISULTATI:", len(results))
    for item in results[:10]:
        print(item)
