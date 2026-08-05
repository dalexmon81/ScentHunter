import json
import re
import html as html_lib
import importlib
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://www.sabina.com"
QUERY = "Miu Miu"
TIMEOUT = 30

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

def clean(v):
    return re.sub(r"\s+", " ", html_lib.unescape(str(v or ""))).strip()

def norm(v):
    s = clean(v).lower().replace("’", "'").replace("`", "'")
    return s

def main():
    lines = []
    url = BASE + "/it/ricerca?search_query=" + quote_plus(QUERY)
    s = requests.Session()
    r = s.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
    html = r.text
    soup = BeautifulSoup(html, "html.parser")

    lines += [
        "=== SCENTHUNTER / SABINA PARSER DIAGNOSTIC ===",
        f"REQUEST: {url}",
        f"FINAL URL: {r.url}",
        f"STATUS: {r.status_code}",
        f"HTML LEN: {len(html)}",
        f"CONTENT-TYPE: {r.headers.get('content-type')}",
        "",
        "=== RAW MIU-MIU PRODUCT-LIKE LINKS ===",
    ]

    raw = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(BASE, a.get("href", ""))
        text = clean(" ".join([
            a.get("title") or "",
            a.get("aria-label") or "",
            a.get_text(" ", strip=True) or "",
        ]))
        parent_text = ""
        node = a
        for _ in range(5):
            node = getattr(node, "parent", None)
            if node is None:
                break
            t = clean(node.get_text(" ", strip=True))
            if "€" in t:
                parent_text = t[:700]
                break
        hay = norm(text + " " + parent_text + " " + href)
        if ("miu" in hay or "miutine" in hay) and href not in seen:
            seen.add(href)
            raw.append((text, href, parent_text))

    lines.append(f"RAW CANDIDATES: {len(raw)}")
    for i, (text, href, parent_text) in enumerate(raw, 1):
        lines.append(f"[{i}] TEXT: {text}")
        lines.append(f"    URL: {href}")
        if parent_text:
            lines.append(f"    BLOCK: {parent_text[:350]}")
    lines.append("")

    lines.append("=== CURRENT SCRAPER _parse_html() ===")
    try:
        try:
            mod = importlib.import_module("backend.scrapers.sabina.scraper")
        except ModuleNotFoundError:
            mod = importlib.import_module("scrapers.sabina.scraper")

        parsed = mod._parse_html(html, QUERY)
        lines.append(f"_parse_html COUNT: {len(parsed)}")
        for i, p in enumerate(parsed, 1):
            lines.append(
                f"[{i}] {p.get('name')} | {p.get('price')} | {p.get('url')}"
            )
    except Exception as e:
        lines.append(f"_parse_html ERROR: {type(e).__name__}: {e}")

    lines.append("")
    lines.append("=== CURRENT SCRAPER search() ===")
    try:
        final = mod.search(QUERY)
        lines.append(f"search COUNT: {len(final)}")
        for i, p in enumerate(final, 1):
            lines.append(
                f"[{i}] {p.get('name')} | {p.get('price')} | {p.get('url')}"
            )
    except Exception as e:
        lines.append(f"search ERROR: {type(e).__name__}: {e}")

    lines.append("")
    lines.append("=== STRING PRESENCE CHECK ===")
    checks = [
        "miutine",
        "l'eau de muguet",
        "l'eau bleue",
        "l'eau rosee",
        "l'eau rosée",
        "fleur de lait",
        "miumiu fleur de lait",
    ]
    low = norm(html)
    for x in checks:
        lines.append(f"{x} => {norm(x) in low}")

    report = "\n".join(lines)
    print(report)

    out = Path(__file__).resolve().parent / "sabina_parser_report.txt"
    out.write_text(report, encoding="utf-8")
    print(f"\nREPORT SAVED: {out}")

if __name__ == "__main__":
    main()
