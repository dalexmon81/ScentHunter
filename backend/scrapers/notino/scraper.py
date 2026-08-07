import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urljoin

STORE = "Notino"
BASE_URL = "https://www.notino.fr"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

PRICE_RE = re.compile(
    r"€\s*(\d{1,4}[.,]\d{2})|(\d{1,4}[.,]\d{2})\s*€",
    re.I,
)


def _clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _words(s):
    return [
        x for x in re.findall(r"[a-z0-9]+", _clean(s).lower())
        if len(x) > 1
    ]


def _matches(text, query):
    text = _clean(text).lower()
    return all(word in text for word in _words(query))


def _price(text):
    matches = list(PRICE_RE.finditer(text or ""))

    if not matches:
        return ""

    match = matches[-1]
    value = match.group(1) or match.group(2)

    return value.replace(".", ",") + "€"


def _search_page(query):
    urls = [
        BASE_URL + "/search.asp?exps=" + quote_plus(query),
        BASE_URL + "/search?query=" + quote_plus(query),
    ]

    session = requests.Session()
    session.headers.update(HEADERS)

    for url in urls:
        try:
            response = session.get(
                url,
                timeout=15,
                allow_redirects=True,
            )
            print("NOTINO DEBUG REQUEST URL:", url, flush=True)
            print("NOTINO DEBUG STATUS:", response.status_code, flush=True)
            print("NOTINO DEBUG FINAL URL:", response.url, flush=True)
            print("NOTINO DEBUG HTML LENGTH:", len(response.text or ""), flush=True)

            body_preview = _clean(
                BeautifulSoup(response.text or "", "html.parser").get_text(" ", strip=True)
            )
            print("NOTINO DEBUG BODY:", body_preview[:1200], flush=True)

            response.raise_for_status()
        except requests.RequestException as error:
            print("NOTINO ERROR:", error, flush=True)
            continue

        if response.text:
            yield response.text


def search(query):
    query = _clean(query)

    if not query:
        return []

    results = []
    seen = set()

    for html in _search_page(query):
        soup = BeautifulSoup(html, "html.parser")
        all_links = soup.find_all("a", href=True)
        print("NOTINO DEBUG LINKS TOTAL:", len(all_links), flush=True)

        candidate_count = 0
        query_card_count = 0

        for link in all_links:
            href = _clean(link.get("href", ""))

            if not href:
                continue

            product_url = urljoin(BASE_URL, href).split("?")[0]

            if "notino.fr" not in product_url.lower():
                continue

            path = product_url.replace(BASE_URL, "").strip("/").lower()

            if not path:
                continue

            if any(
                bad in path
                for bad in (
                    "search.asp",
                    "search/",
                    "panier",
                    "cart",
                    "login",
                    "account",
                    "contact",
                    "livraison",
                    "conditions",
                    "magazine",
                )
            ):
                continue

            if product_url in seen:
                continue

            candidate_count += 1
            if candidate_count <= 30:
                print(
                    "NOTINO DEBUG CANDIDATE:",
                    product_url,
                    "| LINK TEXT:",
                    _clean(link.get_text(" ", strip=True))[:180],
                    flush=True,
                )

            node = link
            card = None

            # Stessa logica di ParfumCity/PerfumeMarket:
            # risale dalla voce prodotto fino alla card che contiene
            # query + prezzo.
            for _ in range(8):
                if node is None:
                    break

                text = _clean(node.get_text(" ", strip=True))

                if _matches(text, query) and _price(text):
                    card = node
                    break

                node = node.parent

            if card is None:
                continue

            query_card_count += 1
            text = _clean(card.get_text(" ", strip=True))
            print(
                "NOTINO DEBUG MATCHED CARD:",
                product_url,
                "| TEXT:",
                text[:600],
                "| PRICE:",
                _price(text),
                flush=True,
            )

            name = ""

            for tag in card.find_all(["h1", "h2", "h3", "h4"]):
                candidate = _clean(tag.get_text(" ", strip=True))

                if candidate and _matches(candidate, query):
                    name = candidate
                    break

            if not name:
                candidate = _clean(
                    link.get("title")
                    or link.get("aria-label")
                    or link.get_text(" ", strip=True)
                )

                if candidate and _matches(candidate, query):
                    name = candidate

            if not name:
                # Alcune card Notino hanno il nome separato dal link:
                # usiamo il testo della card soltanto se contiene la query.
                for element in card.find_all(["span", "div", "p"]):
                    candidate = _clean(
                        element.get_text(" ", strip=True)
                    )

                    if (
                        candidate
                        and len(candidate) <= 250
                        and _matches(candidate, query)
                    ):
                        name = candidate
                        break

            if not name:
                print(
                    "NOTINO DEBUG REJECT NAME:",
                    product_url,
                    "| CARD:",
                    text[:500],
                    flush=True,
                )
                continue

            price = _price(text)

            if not price:
                print(
                    "NOTINO DEBUG REJECT PRICE:",
                    product_url,
                    "| NAME:",
                    name,
                    "| CARD:",
                    text[:500],
                    flush=True,
                )
                continue

            print(
                "NOTINO DEBUG ACCEPT:",
                name,
                "| PRICE:",
                price,
                "| URL:",
                product_url,
                flush=True,
            )

            seen.add(product_url)

            results.append({
                "store": STORE,
                "name": name,
                "price": price,
                "url": product_url,
            })

            if len(results) >= 10:
                return results

        if results:
            return results

    print(
        "NOTINO DEBUG FINAL RESULTS:",
        len(results),
        results,
        flush=True,
    )
    return results


if __name__ == "__main__":
    print(search("Hawas Ice"))
