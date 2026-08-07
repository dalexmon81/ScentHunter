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
    text = _clean(text)

    if not text:
        return ""

    # 1. Notino: "Prix actuel 37,50 €"
    current = re.search(
        r"prix\\s+actuel\\s+(\\d{1,4}[.,]\\d{2})\\s*€",
        text,
        re.I,
    )
    if current:
        return current.group(1).replace(".", ",") + "€"

    # 2. Notino: "En stock | 37,50 € / 100 ml"
    stock = re.search(
        r"en\\s+stock.{0,80}?(\\d{1,4}[.,]\\d{2})\\s*€",
        text,
        re.I,
    )
    if stock:
        return stock.group(1).replace(".", ",") + "€"

    # 3. Evita che lo storico "Dernier prix le plus bas"
    # venga scelto come prezzo del prodotto.
    cleaned = re.sub(
        r"dernier\\s+prix\\s+le\\s+plus\\s+bas\\s+"
        r"\\d{1,4}[.,]\\d{2}\\s*€",
        "",
        text,
        flags=re.I,
    )

    matches = list(PRICE_RE.finditer(cleaned))

    if not matches:
        return ""

    # Manteniamo il comportamento dello scraper originale.
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
            response.raise_for_status()
        except requests.RequestException as error:
            print("NOTINO ERROR:", error)
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

        for link in soup.find_all("a", href=True):
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

            text = _clean(card.get_text(" ", strip=True))

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
                continue

            price = _price(text)

            if not price:
                continue

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

    return results


if __name__ == "__main__":
    print(search("Hawas Ice"))
