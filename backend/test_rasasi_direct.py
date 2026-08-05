import re
import requests
from bs4 import BeautifulSoup

BASE = "https://www.sabina.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.7",
}

def test_rasasi():
    url = BASE + "/it/631_rasasi"
    r = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)

    print("STATUS =", r.status_code)
    print("URL =", r.url)
    print("HTML =", len(r.text))

    soup = BeautifulSoup(r.text, "html.parser")
    found = []

    for a in soup.find_all("a", href=True):
        href = a["href"]
        full = href if href.startswith("http") else BASE + "/" + href.lstrip("/")
        text = (a.get_text(" ", strip=True) + " " + full).lower()

        if "hawas" not in text:
            continue
        if not re.search(r"\d+-[^/?#]+\.html", full, re.I):
            continue
        if full not in found:
            found.append(full)

    print("HAWAS LINKS =", len(found))
    for x in found:
        print(x)

test_rasasi()
