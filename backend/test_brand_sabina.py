import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.sabina.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "it-IT,it;q=0.9",
}
TIMEOUT = 8
BRAND_RE = re.compile(r"/it/\d+_[^/?#]+/?$", re.I)


def norm(s):
    return re.sub(r"\s+", " ", str(s or "").lower()).strip()


def find_brand(brand):
    brand = norm(brand)
    pages = [
        BASE_URL + "/it/",
        BASE_URL + "/it/marche",
        BASE_URL + "/it/brands",
        BASE_URL + "/it/manufacturer",
    ]

    session = requests.Session()

    for page in pages:
        try:
            r = session.get(page, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
            if r.status_code != 200:
                continue
        except requests.RequestException:
            continue

        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = urljoin(BASE_URL, a["href"]).split("?")[0].split("#")[0]
            hay = norm(
                a.get_text(" ", strip=True)
                + " "
                + a.get("title", "")
                + " "
                + href.replace("_", " ").replace("-", " ")
            )
            if BRAND_RE.search(href) and brand in hay:
                return href

    return None


if __name__ == "__main__":
    print("RASASI =", find_brand("Rasasi"))
