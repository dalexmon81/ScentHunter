import re import requests from bs4 import BeautifulSoup, Tag from
urllib.parse import quote_plus, urljoin

STORE = “Bplatz” BASE = “https://en.bplatz.de” TIMEOUT = 6

HEADERS = { “User-Agent”: ( “Mozilla/5.0 (Windows NT 10.0; Win64; x64)”
“AppleWebKit/537.36 (KHTML, like Gecko)” “Chrome/131.0 Safari/537.36” ),
“Accept-Language”: “en-US,en;q=0.9”, }

def _norm(v): v = str(v or ““).lower() v =
re.sub(r”(?<=(?=[a-z])|(?<=[a-z])(?=“,” “, v) v = re.sub(r”[^a-z0-9]+“,”
“, v) return re.sub(r”+“,” “, v).strip()

def _match(text, query): words = _norm(query).split() hay = _norm(text)
return bool(words) and all(w in hay for w in words)

def _price(text): if not text: return None

    patterns = [
        r"retail\s+price\s*€\s*(\d{1,4}(?:[.,]\d{2})?)",
        r"sale\s+price\s*€\s*(\d{1,4}(?:[.,]\d{2})?)",
        r"€\s*(\d{1,4}(?:[.,]\d{2})?)",
        r"(\d{1,4}(?:[.,]\d{2})?)\s*€",
    ]

    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if not m:
            continue

        value = m.group(1).replace(".", ",")

        try:
            if float(value.replace(",", ".")) <= 0:
                continue
        except ValueError:
            continue

        if "," not in value:
            value += ",00"

        return value + " €"

    return None

def _product_card(a): node = a best = a

    for _ in range(8):
        parent = node.parent

        if not isinstance(parent, Tag):
            break

        text = " ".join(parent.stripped_strings)

        if len(text) > 1800:
            break

        best = parent

        if "€" in text and (
            "add to" in text.lower()
            or "wishlist" in text.lower()
            or "retail price" in text.lower()
            or "show product" in text.lower()
        ):
            return parent

        node = parent

    return best

def _extract_page(html, query): soup = BeautifulSoup(html,
“html.parser”) out = [] seen = set()

    for a in soup.find_all("a", href=True):
        href = urljoin(BASE, a.get("href", "")).split("#")[0].split("?")[0]

        if "/products/" not in href.lower():
            continue

        card = _product_card(a)
        card_text = " ".join(card.stripped_strings).strip()

        if not _match(card_text, query):
            continue

        candidates = [
            " ".join(a.stripped_strings).strip(),
            (a.get("title") or "").strip(),
            (a.get("aria-label") or "").strip(),
        ]

        img = card.find("img")
        if img:
            candidates.append((img.get("alt") or "").strip())

        product_name = next(
            (x for x in candidates if x and _match(x, query)),
            None
        )

        if not product_name:
            for pa in card.find_all("a", href=True):
                txt = " ".join(pa.stripped_strings).strip()
                phref = urljoin(BASE, pa.get("href", ""))

                if (
                    "/products/" in phref.lower()
                    and txt
                    and _match(txt, query)
                ):
                    product_name = txt
                    href = phref.split("#")[0].split("?")[0]
                    break

        if not product_name:
            continue

        price = _price(card_text)

        if not price:
            continue

        key = (href.lower(), _norm(product_name))

        if key in seen:
            continue

        seen.add(key)

        out.append({
            "store": STORE,
            "name": product_name,
            "price": price,
            "url": href,
        })

    return out

def _search_urls(query): q = quote_plus(query)

    # Shopify storefront search. These are direct search requests,
    # not a 30-page catalogue crawl.
    return [
        f"{BASE}/search?q={q}&type=product",
        f"{BASE}/search?q={q}",
    ]

def search(query): query = str(query or ““).strip()

    if not query:
        return []

    session = requests.Session()
    session.headers.update(HEADERS)

    results = []
    seen_urls = set()

    for url in _search_urls(query):
        try:
            r = session.get(
                url,
                timeout=TIMEOUT,
                allow_redirects=True,
            )
        except requests.RequestException:
            continue

        if r.status_code != 200 or not r.text:
            continue

        page_results = _extract_page(r.text, query)

        for item in page_results:
            key = item["url"].lower()

            if key in seen_urls:
                continue

            seen_urls.add(key)
            results.append(item)

        if results:
            break

    results.sort(
        key=lambda x: (
            len(_norm(x["name"])),
            x["name"].lower(),
        )
    )

    return results[:20]

if name == “main”: for q in ( “Rasasi Hawas”, “Armaf Club de Nuit”,
“Afnan 9 PM Night Out”, “French Avenue”, ): print(“” + “=” * 60)
print(“QUERY:”, q) items = search(q) print(“RISULTATI:”, len(items)) for
item in items: print(item)
