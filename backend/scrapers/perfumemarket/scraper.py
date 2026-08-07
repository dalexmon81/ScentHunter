import re import requests from bs4 import BeautifulSoup from
urllib.parse import quote, urljoin

BASE_URL = “https://www.perfumemarket.nl” PRICE_RE =
re.compile(r”€([.,])|([.,])€“, re.I)

Parole che indicano prodotti diversi dal profumo vero e proprio.

EXCLUDED_WORDS = { “body”, “shower”, “gel”, “soap”, “wash”, “hand”,
“cream”, “creme”, “moisturizer”, “deodorant”, “spray deodorant”,
“lotion”, “after shave”, “aftershave”, “hair”, “candle”, “diffuser”,
“set”, “gift set” }

def _norm(text): text = str(text or ““).lower() text =
re.sub(r”[^a-z0-9]+“,” “, text) return re.sub(r”+“,” “, text).strip()

def _extract_price(text): match = PRICE_RE.search(text or ““) if not
match: return None

    value = match.group(1) or match.group(2)
    return value.replace(".", ",") + " €"

def _extract_ml(text): m = re.search(r”)ml, text or ““, re.I) return
int(m.group(1)) if m else None

def _is_excluded(name): n = _norm(name) return any(re.search(r” +
re.escape(word) + r”, n) for word in EXCLUDED_WORDS)

def _query_tokens(query): # Il formato non deve impedire di trovare le
altre varianti. # Es.: “Tom Ford Neroli Portofino 30 ml” deve poter
trovare anche 50/100 ml. q = re.sub(r”ml, ” “, str(query or”“),
flags=re.I) return [t for t in _norm(q).split() if t]

def _product_name_from_card(card, fallback): # Cerca prima un
titolo/link prodotto leggibile nella stessa card. candidates = []

    for selector in ("h1", "h2", "h3", "h4", ".product-title", ".card__heading", ".product-item__title"):
        for node in card.select(selector):
            txt = node.get_text(" ", strip=True)
            if txt:
                candidates.append(txt)

    for a in card.find_all("a", href=True):
        txt = a.get_text(" ", strip=True)
        if txt:
            candidates.append(txt)

    if fallback:
        candidates.append(fallback)

    # Preferisce nomi con formato ml, perché distinguono correttamente le varianti.
    candidates = list(dict.fromkeys(candidates))
    candidates.sort(key=lambda x: (0 if _extract_ml(x) else 1, len(x)))

    return candidates[0] if candidates else fallback

def search(query): query = str(query or ““).strip() if not query: return
[]

    url = BASE_URL + "/search?q=" + quote(query)
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                      "AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1",
        "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
    except requests.RequestException as error:
        print(f"PERFUMEMARKET ERROR: {error}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    results = []
    seen = set()

    tokens = _query_tokens(query)

    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        link_name = link.get_text(" ", strip=True)

        if not href:
            continue

        # Risale la card senza inglobare mezza pagina.
        node = link
        card = link
        for _ in range(6):
            parent = getattr(node, "parent", None)
            if parent is None:
                break

            text = parent.get_text(" ", strip=True)
            if len(text) > 2500:
                break

            card = parent

            # Una card utile contiene prezzo e link.
            if PRICE_RE.search(text):
                break

            node = parent

        card_text = card.get_text(" ", strip=True)
        name = _product_name_from_card(card, link_name)

        # Il match viene fatto sul contenuto della card, non soltanto sul primo <a>.
        haystack = _norm(name + " " + card_text)
        if not tokens or not all(token in haystack for token in tokens):
            continue

        if _is_excluded(name):
            continue

        price = _extract_price(card_text)
        if not price:
            continue

        product_url = urljoin(BASE_URL, href).split("#")[0]

        # Evita URL generici della ricerca/home.
        if "/search" in product_url.lower():
            continue

        ml = _extract_ml(name) or _extract_ml(card_text)

        # Chiave con URL + formato: non elimina accidentalmente 30/50/100 ml.
        key = (product_url.split("?")[0], ml)
        if key in seen:
            continue
        seen.add(key)

        clean_name = name.strip()
        if ml and not re.search(r"\b\d{1,4}\s*ml\b", clean_name, re.I):
            clean_name = f"{clean_name} {ml} ml"

        results.append({
            "store": "PerfumeMarket",
            "name": clean_name,
            "price": price,
            "url": product_url,
        })

    # Prima i profumi con formato riconosciuto, poi ordine crescente di ml.
    results.sort(key=lambda x: (
        _extract_ml(x["name"]) is None,
        _extract_ml(x["name"]) or 9999,
        _norm(x["name"])
    ))

    return results

if name == “main”: for q in ( “Tom Ford Neroli Portofino”, “Hawas Ice”,
“Riiffs Freeze”, ): print(“” + “=” * 60) print(“QUERY:”, q) items =
search(q) print(“RISULTATI:”, len(items)) for product in items:
print(product)
