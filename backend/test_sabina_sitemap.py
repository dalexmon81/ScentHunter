import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

BASE = "https://www.sabina.com"
URLS = [
    BASE + "/it/sitemap",
    BASE + "/en/sitemap",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.7",
}

BRANDS = ("rasasi", "dior", "versace", "azzaro")

for page in URLS:
    print("\nSITEMAP:", page)
    try:
        r = requests.get(page, headers=HEADERS, timeout=15, allow_redirects=True)
        print("STATUS =", r.status_code, "FINAL =", r.url)
        soup = BeautifulSoup(r.text, "html.parser")

        for brand in BRANDS:
            found = []
            for a in soup.find_all("a", href=True):
                href = urljoin(BASE, a["href"])
                text = (a.get_text(" ", strip=True) + " " + href).lower()
                if brand in text:
                    found.append(href)

            found = list(dict.fromkeys(found))
            print(brand.upper(), "=", found[:10] if found else None)

    except requests.RequestException as e:
        print("ERRORE =", e)
