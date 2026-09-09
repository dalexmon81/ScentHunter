import re
import json
import time
import html as html_lib
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

STORE = "Sabina"
BASE = "https://www.sabina.com"
TIMEOUT = 1.5
SEARCH_DEADLINE = 5.5

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
    r"^https?://(?:www\.)?sabina\.com/(?:it|fr|en|es|pt|nl|de|pl|da|sv|tw)/(?!"
    r"(?:content|ricerca|ricerca_old|marchi|negozi|contatto|faq|"
    r"carrello|ordine|stato-ordine|il-mio-conto|module|s|s-)/)"
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
        # Sabina mostra normalmente due prezzi consecutivi:
        # "Prezzo normale: 62,95 €" e "Prezzo: 37,95 €".
        # Il primo è il listino, non il prezzo dell'offerta.
        current_price_match = re.search(
            r"(?:prix|price|precio|preço|prezzo)\s*:\s*"
            r"(\d{1,4}(?:[.,]\d{2}))\s*[€$£]",
            window,
            re.I,
        )
        if current_price_match:
            add_variant(size, current_price_match.group(1) + " €")
        else:
            # Fallback stretto: se la pagina usa solo un prezzo senza
            # etichetta, usa il primo prezzo disponibile dopo la misura.
            price_match = re.search(
                r"(\d{1,4}(?:[.,]\d{2}))\s*[€$£]",
                window,
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

        # Never associate the normal Liquid Brun card with the Limited
        # Edition URL (or vice versa). Sabina exposes both products in the
        # same French Avenue collection and the two links can sit adjacent.
        name_low = name.lower()
        url_low = str(url).lower()
        name_limited = "limited edition" in name_low
        url_limited = "limited-edition" in url_low or "limited_edition" in url_low
        if name_limited != url_limited:
            continue

        hay = name_low
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

        # Sabina product cards often contain BOTH the crossed/list price and
        # the current sale price, e.g. "Prezzo normale: 62,95 € Prezzo: 37,95 €".
        # PRICE_RE alone therefore picks the wrong number. Prefer an explicitly
        # labelled current price; if the card has only the two raw prices, use
        # the lower valid product price (never a unit price such as €/100ml).
        def _card_price(block):
            current = re.search(
                r"(?:prezzo|price|prix|precio|preço|preis)\s*:\s*"
                r"(\d{1,4}(?:[.,]\d{2}))\s*€",
                block,
                re.I,
            )
            if current:
                return current.group(1) + " €"

            values = []
            for m in PRICE_RE.finditer(block):
                suffix = block[m.end():m.end()+20].lower()
                prefix = block[max(0, m.start()-45):m.start()].lower()
                if re.match(r"\s*/\s*\d+\s*ml", suffix):
                    continue
                if re.search(r"(?:/\s*\d+\s*ml|per\s*\d+\s*ml|par\s*\d+\s*ml|pour\s*\d+\s*ml)\s*$", prefix):
                    continue
                try:
                    value = float(m.group(1).replace(",", "."))
                except ValueError:
                    continue
                values.append((value, m.group(1)))
            if not values:
                return None
            values.sort(key=lambda x: x[0])
            return values[0][1] + " €"

        card_price = _card_price(text_block)
        if not card_price:
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
            "price": card_price,
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


def _xml_locs(text):
    """Return sitemap <loc> values without depending on XML namespaces."""
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(text or "")
        out = []
        for el in root.iter():
            tag = str(el.tag).lower()
            if (tag == "loc" or tag.endswith("}loc")) and el.text:
                value = _clean(el.text)
                if value:
                    out.append(value)
        return out
    except Exception:
        return re.findall(r"<loc>\s*([^<]+?)\s*</loc>", text or "", re.I)



def _sitemap_product_candidates(session, query, deadline=None):
    """Bounded generic sitemap discovery.

    Independent sitemap probes run concurrently. The function never relies on
    a product/brand-specific sitemap URL and stops as soon as matching product
    URLs are found.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    qwords = [
        w for w in re.findall(r"[a-z0-9À-ÿ]+", _clean(query).lower())
        if len(w) > 1 and w != "ml" and not w.isdigit()
    ]
    if not qwords:
        return []

    candidates = []
    seen_products = set()

    def add_product(url):
        if not _looks_like_product_url(url):
            return
        clean_url = str(url).split("#")[0].split("?")[0]
        slug = clean_url.lower().rsplit("/", 1)[-1]
        if all(word in slug for word in qwords) and clean_url not in seen_products:
            seen_products.add(clean_url)
            candidates.append(clean_url)

    def fetch_locs(url, timeout=1.5):
        try:
            r = session.get(
                url,
                headers=HEADERS,
                timeout=timeout,
                allow_redirects=True,
            )
            status = r.status_code
            body = r.text if status == 200 else ""
            r.close()
            return status, _xml_locs(body)
        except Exception:
            return 0, []

    index_urls = [
        BASE + "/sitemap_index_shop_1.xml",
        BASE + "/1_index_sitemap.xml",
        BASE + "/sitemap.xml",
        BASE + "/sitemap_index.xml",
        BASE + "/sitemap-index.xml",
    ] + [
        BASE + f"/1_{lang}_0_sitemap.xml"
        for lang in ("it", "fr", "en", "es", "pt", "nl", "de", "pl", "da", "sv", "tw")
    ] + [
        BASE + "/as4_seositemap.xml",
        BASE + "/as4_seositemap-1.xml",
        BASE + "/as4_seositemap-2.xml",
    ]

    index_locs = []
    with ThreadPoolExecutor(max_workers=min(8, len(index_urls))) as ex:
        futures = [ex.submit(fetch_locs, url) for url in index_urls]
        for fut in as_completed(futures):
            try:
                status, locs = fut.result()
            except Exception:
                continue
            if status != 200:
                continue

            index_locs.append(locs)
            for loc in locs:
                add_product(loc)

    if candidates:
        return candidates[:8]

    child_urls = []
    seen_children = set()
    for locs in index_locs:
        for loc in locs:
            low = str(loc).lower()
            if not low.endswith(".xml"):
                continue
            if loc not in seen_children:
                seen_children.add(loc)
                child_urls.append(loc)

    # Keep the child wave deliberately small. If a store exposes a huge sitemap
    # tree, it must not become the latency bottleneck.
    child_urls = child_urls[:12]

    if child_urls:
        with ThreadPoolExecutor(max_workers=min(6, len(child_urls))) as ex:
            futures = [ex.submit(fetch_locs, url) for url in child_urls]
            for fut in as_completed(futures):
                try:
                    status, locs = fut.result()
                except Exception:
                    continue
                if status != 200:
                    continue
                for loc in locs:
                    add_product(loc)
                    if len(candidates) >= 8:
                        return candidates[:8]

    return candidates[:8]


def _brand_collection_fallback(session, query):
    """Fast generic fallback using Sabina's public collection surface.

    The previous implementation hard-coded the French Avenue collection.
    That is removed: a collection is used only when a generic collection URL
    can be discovered from the query's public search page.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    qwords = [w for w in re.findall(r"[a-z0-9À-ÿ]+", _clean(query).lower())
              if len(w) > 1 and w != "ml" and not w.isdigit()]
    if not qwords:
        return []

    search_urls = [
        BASE + "/it/ricerca?search_query=" + quote_plus(query),
        BASE + "/it/ricerca_old?s=" + quote_plus(query),
        BASE + "/it/ricerca_old?search_query=" + quote_plus(query),
    ]

    def parse_search(url):
        try:
            r = session.get(
                url,
                headers=HEADERS,
                timeout=TIMEOUT,
                allow_redirects=True,
            )
            if r.status_code != 200:
                r.close()
                return []
            soup = BeautifulSoup(r.text or "", "html.parser")
            out = []
            seen = set()
            for a in soup.find_all("a", href=True):
                href = urljoin(BASE, a.get("href", ""))
                if not href:
                    continue
                label = _clean(a.get_text(" ", strip=True))
                blob = (label + " " + href).lower()
                if _looks_like_product_url(href) and all(w in blob for w in qwords):
                    href = href.split("#")[0].split("?")[0]
                    if href not in seen:
                        seen.add(href)
                        out.append(href)
                # Discover a generic collection/category link only when the
                # page itself exposes the query's brand/category context.
                elif "/it/" in href and "sabina.com" in href and all(w in blob for w in qwords):
                    if href not in seen:
                        seen.add(href)
            return out[:8]
        except Exception:
            return []

    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = [ex.submit(parse_search, url) for url in search_urls]
        for fut in as_completed(futures):
            try:
                found = fut.result()
            except Exception:
                found = []
            if found:
                return found
    return []


def search(query):
    """Fast, bounded Sabina search."""
    query = _clean(query)
    if not query:
        return []

    started = time.monotonic()
    s = requests.Session()
    s.headers.update(HEADERS)

    try:
        # 1) Search pages in parallel. This is the fastest generic discovery
        # channel and replaces the previous hard-coded French Avenue collection.
        candidates = _brand_collection_fallback(s, query)

        # 2) Generic sitemap fallback, still bounded.
        if not candidates and (time.monotonic() - started) < SEARCH_DEADLINE:
            candidates = _sitemap_product_candidates(
                s,
                query,
                deadline=SEARCH_DEADLINE,
            )

        if not candidates:
            return []

        # 3) Product pages concurrently.
        rows = []
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def fetch_product(url):
            try:
                r = _get(s, url)
                if r is None:
                    return []
                html = r.text
                r.close()
                return _parse_html(html, query)
            except Exception:
                return []

        remaining = max(0.5, SEARCH_DEADLINE - (time.monotonic() - started))
        with ThreadPoolExecutor(max_workers=min(4, len(candidates))) as ex:
            futures = [ex.submit(fetch_product, u) for u in candidates]
            deadline_at = time.monotonic() + remaining
            for fut in as_completed(futures):
                if time.monotonic() >= deadline_at:
                    break
                try:
                    rows.extend(fut.result(timeout=max(0.05, deadline_at - time.monotonic())))
                except Exception:
                    pass

        rows = _dedupe(rows, query)
        if not rows:
            return []

        # Size enrichment is deliberately capped by the remaining budget.
        if time.monotonic() - started >= SEARCH_DEADLINE:
            return rows
        return _enrich_product_sizes(s, rows, query)
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
