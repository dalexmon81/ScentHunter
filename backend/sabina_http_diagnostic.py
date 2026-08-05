import requests
from urllib.parse import quote_plus

BASE = "https://www.sabina.com"
QUERY = "Miu Miu"

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

url = BASE + "/it/ricerca?search_query=" + quote_plus(QUERY)
s = requests.Session()
r = s.get(url, headers=HEADERS, timeout=30, allow_redirects=True)

html = r.text
html_low = html.lower().replace("’", "'")

checks = [
    "miutine",
    "l'eau de muguet",
    "l'eau bleue",
    "l'eau rosee",
    "fleur de lait",
    "miumiu fleur de lait",
]

lines = [
    "=== SCENTHUNTER / SABINA HTTP DIAGNOSTIC ===",
    f"REQUEST URL: {url}",
    f"FINAL URL: {r.url}",
    f"STATUS: {r.status_code}",
    f"CONTENT-TYPE: {r.headers.get('content-type')}",
    f"SERVER: {r.headers.get('server')}",
    f"CF-RAY: {r.headers.get('cf-ray')}",
    f"HTML LEN: {len(html)}",
    f"COOKIES: {s.cookies.get_dict()}",
    "CHALLENGE WORDS: " + str(any(x in html_low for x in [
        "captcha", "cloudflare", "attention required",
        "verify you are human", "cf-chl", "challenge-platform"
    ])),
    "",
    "=== PRODUCT STRING CHECKS ===",
]
for c in checks:
    lines.append(f"{c} => {c in html_low}")

report = "\n".join(lines)
print(report)

Path("sabina_http_diagnostic.txt").write_text(report, encoding="utf-8")
Path("sabina_raw_response.html").write_text(html, encoding="utf-8")
