import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

BASE = "https://www.sabina.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.7",
}

PAGES = [
    "/it/marche",
    "/it/marcas",
    "/it/brands",
    "/it/produttori",
    "/it/manufacturers",
]

BRANDS = ["rasasi", "dior", "versace", "azzaro"]

for page in PAGES:
    try:
        r = requests.get(
            BASE + page,
            headers=HEADERS,
            timeout=15,
            allow_redirects=True,
        )
        print("\nPAGE:", page)
        print("STATUS:", r.status_code)
        print("FINAL:", r.url)

        soup = BeautifulSoup(r.text, "html.parser")

        for brand in BRANDS:
            found = []
            for a in soup.find_all("a", href=True):
                href = urljoin(BASE, a["href"]).split("#")[0]
                text = (
                    a.get_text(" ", strip=True)
                    + " "
                    + a.get("title", "")
                    + " "
                    + href
                ).lower()

                if brand in text:
                    found.append(href)

            found = list(dict.fromkeys(found))
            print(brand.upper(), "=", found[:10] if found else None)

    except requests.RequestException as e:
        print("\nPAGE:", page)
        print("ERRORE:", e)
