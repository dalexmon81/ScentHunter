from __future__ import annotations

import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus


BASE_URL = "https://www.easycosmetic.de"
SEARCH_URL = BASE_URL + "/suche?searchfor={}"


def search(query: str):
    url = SEARCH_URL.format(quote_plus(query))

    response = requests.get(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        },
        timeout=15,
    )

    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    results = []

    for link in soup.find_all("a", href=True):
        href = link["href"]

        if ".aspx" not in href:
            continue

        if href.startswith("/"):
            href = BASE_URL + href

        if not href.startswith(BASE_URL):
            continue

        if href not in results:
            results.append(href)

    return results


if __name__ == "__main__":
    products = search("Liquid Brun")

    print("RISULTATI:", len(products))

    for product in products[:10]:
        print(product)
