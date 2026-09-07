import re
import json
import html as html_lib
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

STORE = "Sabina"
BASE = "https://www.sabina.com"
TIMEOUT = 3

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
        "Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Referer": BASE + "/it/",
}

PRICE_RE = re.compile(r"(?<!\d)(\d{1,4}(?:[.,]\d{2}))\s*€")
PRODUCT_URL_RE = re.compile(
    r"^https?://(?:www\.)?sabina\.com/it/(?!"
    r"(?:content|ricerca|ricerca_old|marchi|negozi|contatto|faq|"
    r"carrello|ordine|stato-ordine|il-mio-conto|module)/)"
)


def _clean(value):
    return re.sub(r"\s+", " ", html_lib.unescape(value or "")).strip()


def _price(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return f"{float(value):.2f}".replace(".", ",") + " €"
    text = _clean(str(value))
    m = PRICE_RE.search(text)
    if not m:
        # JSON/API spesso restituisce il numero senza simbolo €
        m = re.search(r"(?<!\d)(\d{1,4}(?:[.,]\d{2}))(?!\d)", text)
    if not m:
        return None
    return m.group(1).replace(".", ",") + " €"


def _looks_like_product_url(url):
    return bool(url and PRODUCT_URL_RE.match(url))


def _extract_variants_from_html(text):
    """Estrae SOLO varianti realmente legate alla scheda prodotto.

    La versione precedente scandiva indiscriminatamente tutti i div/span/li
    della pagina. Sabina inserisce nelle stesse pagine prodotti consigliati,
    filtri e blocchi di navigazione: quel metodo poteva quindi associare, per
    esempio, 90/100/150/200 ml allo stesso prodotto usando prezzi di altri
    prodotti.

    Regola nuova:
      1. prima leggiamo il blocco "Dimensione/Taille/Size" della scheda;
      2. poi leggiamo JSON strutturato SOLO quando misura e prezzo sono nello
         stesso oggetto;
      3. non facciamo più un fallback globale sul testo della pagina.
    """
    if not text:
        return []

    soup = BeautifulSoup(text, "html.parser")
    variants = []
    seen = set()

    def add_variant(size, price):
        if size is None or price is None:
            return
        raw_size = str(size).strip()
        m = re.search(r"(?<!\d)(\d{2,4})\s*ml\b", raw_size, re.I)
        if m:
            size = m.group(1)
        elif re.fullmatch(r"\d{2,4}", raw_size):
            size = raw_size
        else:
            return
        price_text = _price(price)
        if not price_text:
            return
        key = (size, price_text)
        if key not in seen:
            seen.add(key)
            variants.append({"size_ml": size, "price": price_text})

    def walk_strict(obj):
        if isinstance(obj, dict):
            low = {str(k).lower(): v for k, v in obj.items()}
            size = None
            for key in (
                "size", "volume", "netcontent", "capacity", "contentvolume",
                "description",
            ):
                if key in low:
                    m = re.search(r"(?<!\d)(\d{2,4})\s*ml\b", str(low[key]), re.I)
                    if m:
                        size = m.group(1)
                        break

            price = None
            for key in (
                "price", "final_price", "finalprice", "sale_price",
                "saleprice", "price_amount", "priceamount",
            ):
                if key in low:
                    price = low[key]
                    break

            # IMPORTANT: misura e prezzo devono appartenere allo stesso
            # oggetto JSON. Non propaghiamo più valori tra oggetti fratelli.
            if size and price:
                add_variant(size, price)

            for value in obj.values():
                walk_strict(value)

        elif isinstance(obj, list):
            for value in obj:
                walk_strict(value)

    # 1) Il blocco visibile della scheda prodotto. Nella pagina reale Sabina
    # mostra, ad esempio: "Dimensione: 100ML" e subito sotto il prezzo.
    visible = _clean(soup.get_text(" ", strip=True))
    size_labels = r"(?:dimensione|taille|size|tamaño|tamanho)"
    size_match = re.search(
        rf"{size_labels}\s*:\s*(\d{{2,4}})\s*ml\b",
        visible,
        re.I,
    )
    if size_match:
        size = size_match.group(1)
        # Limitiamo la ricerca del prezzo al blocco immediatamente successivo
        # alla misura, evitando prezzi di raccomandazioni/reviews lontane.
        window = visible[size_match.start():size_match.end() + 260]
        price_match = re.search(
            r"(?:prix|price|precio|preço|prezzo)?\s*(?:normal[^€$£]{0,40})?"
            r"(\d{1,4}(?:[.,]\d{2}))\s*[€$£]",
            window,
            re.I,
        )
        if price_match:
            add_variant(size, price_match.group(1) + " €")

    # 2) Se la pagina usa un input/option per la misura, leggiamo solo il
    # controllo e il suo contenitore immediato. Mai l'intero parent tree.
    for node in soup.select("option, input, label"):
        raw = " ".join(
            str(node.get(attr, ""))
            for attr in ("value", "aria-label", "data-value", "data-size", "title")
        )
        raw = _clean(raw + " " + node.get_text(" ", strip=True))
        sm = re.search(r"(?<!\d)(\d{2,4})\s*ml\b", raw, re.I)
        if not sm:
            continue

        # Per option/label il prezzo deve essere nello stesso elemento o nel
        # suo parent diretto. Non saliamo ulteriormente nella pagina.
        local_blocks = [raw]
        parent = node.parent
        if parent:
            local_blocks.append(_clean(parent.get_text(" ", strip=True)))
        for block in local_blocks:
            pm = re.search(
                r"(?<!\d)(\d{1,4}(?:[.,]\d{2}))\s*[€$£]",
                block,
            )
            if pm:
                add_variant(sm.group(1), pm.group(1) + " €")
                break

    # 3) JSON-LD: misura + prezzo solo se sono realmente nello stesso objeto.
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.get_text(strip=True))
            walk_strict(data)
        except Exception:
            continue

    return variants

def _extract_size_from_html(text, preferred_size=""):
    """Compatibilità: restituisce una misura dalla pagina prodotto."""
    variants = _extract_variants_from_html(text)

    preferred = re.search(
        r"(?<!\d)(\d{2,4})\s*ml\b",
        str(preferred_size or ""),
        re.I,
    )
    if preferred:
        wanted = preferred.group(1)
        for variant in variants:
            if variant["size_ml"] == wanted:
                return wanted

    return variants[0]["size_ml"] if variants else ""


MAX_SIZE_ENRICH_REQUESTS = 3


def _enrich_product_sizes(session, rows, query=""):
    """Aggiunge formato/prezzo reali delle varianti dalla pagina prodotto.

    Se la query contiene un formato (es. 125 ml), la relativa variante viene
    selezionata dalla scheda prodotto. Questo evita di restituire il prezzo
    della variante predefinita (spesso 75 ml) quando l'utente ha chiesto 125 ml.
    """
    enriched = []
    cache = {}
    enrichment_requests = 0

    requested_size = ""
    m = re.search(r"(?<!\d)(\d{2,4})\s*ml\b", _clean(query), re.I)
    if m:
        requested_size = m.group(1)

    for row in rows:
        item = dict(row)
        name = _clean(item.get("name"))
        existing = re.search(r"\b(\d{1,4})\s*ml\b", name, re.I)

        url = str(item.get("url") or "").split("#")[0]
        if not url:
            if existing:
                item["size_ml"] = existing.group(1)
            enriched.append(item)
            continue

        if existing and not requested_size:
            item["size_ml"] = existing.group(1)
            enriched.append(item)
            continue

        if url in cache:
            variants = cache[url]
        elif enrichment_requests >= MAX_SIZE_ENRICH_REQUESTS:
            variants = []
        else:
            variants = []
            enrichment_requests += 1
            try:
                r = _get(session, url)
                if r is not None:
                    page = r.text
                    r.close()
                    variants = _extract_variants_from_html(page)
            except Exception:
                variants = []
            cache[url] = variants

        if requested_size:
            selected = next(
                (v for v in variants if v["size_ml"] == requested_size),
                None,
            )
            if selected:
                item["size_ml"] = selected["size_ml"]
                item["price"] = selected["price"]
            else:
                # Non fingiamo che una variante diversa sia quella richiesta.
                continue
        elif variants:
            item["size_ml"] = variants[0]["size_ml"]
            item["price"] = variants[0]["price"]

        enriched.append(item)

    return enriched


def _dedupe(rows, query):
    q = _clean(query).lower()

    # Il formato è un filtro sulla variante, non una parola che deve essere
    # necessariamente presente nel nome della card di ricerca.
    words = [
        w for w in re.findall(r"[a-z0-9À-ÿ]+", q)
        if len(w) > 1 and w != "ml" and not w.isdigit()
    ]

    out, seen = [], set()

    for row in rows:
        name = _clean(row.get("name"))
        url = row.get("url")
        price = _price(row.get("price"))

        if not name or not url or not price:
            continue

        hay = name.lower()
        if words and not all(w in hay for w in words):
            continue

        size = str(row.get("size_ml") or "").strip()
        key = (name.lower(), url.split("?")[0], size)
        if key in seen:
            continue
        seen.add(key)

        item = {
            "store": STORE,
            "name": name,
            "price": price,
            "url": url.split("#")[0],
        }
        if size:
            item["size_ml"] = size
        out.append(item)

    return out


def _walk_json(obj, query):
    """Estrae prodotti da JSON anche se SellBoost cambia leggermente i nomi dei campi."""
    rows = []

    def walk(x):
        if isinstance(x, dict):
            low = {str(k).lower(): v for k, v in x.items()}

            name = next(
                (low[k] for k in (
                    "name", "product_name", "productname", "title", "label"
                ) if k in low and isinstance(low[k], (str, int, float))),
                None,
            )
            url = next(
                (low[k] for k in (
                    "url", "link", "product_url", "producturl", "href"
                ) if k in low and isinstance(low[k], str)),
                None,
            )
            price = next(
                (low[k] for k in (
                    "price", "final_price", "finalprice", "sale_price",
                    "saleprice", "price_amount", "priceamount"
                ) if k in low),
                None,
            )

            if url:
                url = urljoin(BASE, url)
            if name and url and _looks_like_product_url(url) and _price(price):
                rows.append({
                    "store": STORE,
                    "name": str(name),
                    "price": price,
                    "url": url,
                })

            for v in x.values():
                walk(v)

        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(obj)
    return _dedupe(rows, query)


def _parse_html(text, query):
    soup = BeautifulSoup(text, "html.parser")
    rows = []

    # 1) JSON-LD: è il dato più pulito quando presente.
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.get_text(strip=True))
            rows.extend(_walk_json(data, query))
        except Exception:
            pass

    # 2) Card / link prodotto. Non dipende da UNA singola classe CSS.
    for a in soup.find_all("a", href=True):
        url = urljoin(BASE, a["href"])
        if not _looks_like_product_url(url):
            continue

        container = a
        for _ in range(7):
            parent = getattr(container, "parent", None)
            if not parent:
                break
            container = parent
            txt = _clean(container.get_text(" ", strip=True))
            if "€" in txt and len(txt) < 1800:
                break

        text_block = _clean(container.get_text(" ", strip=True))
        pm = PRICE_RE.search(text_block)
        if not pm:
            continue

        # Preferenza: titolo strutturato della card; poi title/aria-label;
        # solo alla fine il testo grezzo del link. In questo modo non
        # incorporiamo prezzo, sconto o altre informazioni nel nome prodotto.
        candidates = []

        for sel in ("h1", "h2", "h3", "h4", ".name", ".product-name", ".product-title"):
            el = container.select_one(sel)
            if el:
                candidates.append(el.get_text(" ", strip=True))

        candidates.extend([
            a.get("title"),
            a.get("aria-label"),
            a.get_text(" ", strip=True),
        ])

        name = next(
            (
                _clean(x)
                for x in candidates
                if _clean(x)
                and _clean(x).lower() not in {"vedi", "vedi tutto", "acquista", "immagine"}
            ),
            "",
        )
        if not name or name.lower() in {"vedi", "vedi tutto", "acquista", "immagine"}:
            continue

        rows.append({
            "store": STORE,
            "name": name,
            "price": pm.group(1) + " €",
            "url": url,
        })

    return _dedupe(rows, query)


def _get(session, url, **kwargs):
    r = session.get(
        url,
        headers=HEADERS,
        timeout=TIMEOUT,
        allow_redirects=True,
        **kwargs,
    )

    if r.status_code in (403, 429):
        print(f"SABINA BLOCKED: HTTP {r.status_code}")
        r.close()
        return None

    r.raise_for_status()
    return r

def search(query):
    """
    Ricerca Sabina con cascata strettamente bounded.

    Regola: una ricerca deve tentare prima la ricerca attuale; solo se non
    produce candidati passa a UN fallback legacy e poi a UN solo endpoint AJAX.
    Evitiamo la vecchia cascata 6+ richieste seriali che poteva tenere aperto
    lo scraper per 10-20 secondi.
    """
    query = _clean(query)
    if not query:
        return []

    s = requests.Session()
    s.headers.update(HEADERS)

    try:
        query_without_size = _clean(
            re.sub(r"(?<!\d)\d{2,4}\s*ml\b", " ", query, flags=re.I)
        )

        # 1) Ricerca attuale: una sola richiesta.
        primary_urls = [
            # Current Sabina/PrestaShop search route. The previous bounded
            # version used only search_query=, which can return an empty shell.
            BASE + "/it/ricerca?controller=search&s=" + quote_plus(query),
        ]
        if query_without_size and query_without_size.casefold() != query.casefold():
            primary_urls.append(
                BASE + "/it/ricerca?search_query=" + quote_plus(query_without_size)
            )

        for url in primary_urls:
            try:
                r = _get(s, url)
                if r is None:
                    break
                html = r.text
                r.close()

                parsed = _parse_html(html, query)
                if parsed:
                    return _enrich_product_sizes(
                        s, _dedupe(parsed, query), query
                    )
            except Exception:
                continue

        # 2) Un solo fallback legacy.
        legacy_url = BASE + "/it/ricerca_old?s=" + quote_plus(query)
        try:
            r = _get(s, legacy_url)
            if r is not None:
                html = r.text
                r.close()
                parsed = _parse_html(html, query)
                if parsed:
                    return _enrich_product_sizes(
                        s, _dedupe(parsed, query), query
                    )
        except Exception:
            pass

        # 3) Un solo GET AJAX. Se Sabina risponde 403/429, ci fermiamo:
        # ulteriori tentativi equivalenti aggiungono solo latenza.
        ajax_url = BASE + "/modules/ecelastic/ajax.php"
        payload = {
            "q": query,
            "query": query,
            "search_query": query,
            "id_lang": 5,
            "id_country": 10,
            "id_currency": 1,
        }

        try:
            r = s.get(
                ajax_url,
                params=payload,
                headers=HEADERS,
                timeout=TIMEOUT,
            )
            if r.status_code in (403, 429):
                r.close()
                return []
            if r.ok and r.text.strip():
                response_text = r.text
                r.close()
                try:
                    data = json.loads(response_text)
                    rows = _walk_json(data, query)
                except Exception:
                    rows = _parse_html(response_text, query)
                if rows:
                    return _enrich_product_sizes(
                        s, _dedupe(rows, query), query
                    )
            else:
                r.close()
        except Exception:
            pass

        return []

    finally:
        s.close()


# Alias compatibili con gli altri scraper del progetto.
def scrape(query):
    return search(query)


def search_sabina(query):
    return search(query)


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]).strip() or "Dior"
    data = search(q)
    print(json.dumps(data, ensure_ascii=False, indent=2))
