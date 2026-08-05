import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

BASE = "https://www.sabina.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.7",
}
BRAND_RE = re.compile(r"/it/\d+_[^/?#]+/?$", re.I)

def find_brand(brand):
    brand = brand.lower().strip()
    r = requests.get(BASE + "/it/", headers=HEADERS, timeout=15)
    print("HOME STATUS =", r.status_code)
    soup = BeautifulSoup(r.text, "html.parser")
    matches = []

    for a in soup.find_all("a", href=True):
        href = urljoin(BASE, a["href"]).split("#")[0].split("?")[0]
        hay = " ".join([
            a.get_text(" ", strip=True),
            a.get("title", ""),
            a.get("aria-label", ""),
            href.replace("-", " ").replace("_", " "),
        ]).lower()
        if brand in hay and BRAND_RE.search(href):
            matches.append(href)

    pattern = re.compile(r"(?:https?://www\.sabina\.com)?(/it/\d+_[^\"'<>?\s]+)", re.I)
    for path in pattern.findall(r.text):
        full = urljoin(BASE, path)
        if brand in full.lower().replace("-", " ").replace("_", " "):
            matches.append(full)

    unique = list(dict.fromkeys(matches))
    print(brand.upper(), "CANDIDATES =", unique)
    return unique[0] if unique else None

for brand in ("rasasi", "dior", "versace", "azzaro"):
    print("\n", brand.upper(), "=", find_brand(brand))
