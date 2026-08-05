from pathlib import Path
import html as html_lib
import importlib
import re
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://www.sabina.com"
QUERY = "Miu Miu"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Referer": BASE + "/it/",
}

def clean(value):
    return re.sub(r"\\s+", " ", html_lib.unescape(str(value or ""))).strip()

def main():
    report_lines = []
    url = BASE + "/it/ricerca?search_query=" + quote_plus(QUERY)

    session = requests.Session()
    response = session.get(
        url,
        headers=HEADERS,
        timeout=30,
        allow_redirects=True,
    )
    response.raise_for_status()

    html = response.text
    soup = BeautifulSoup(html, "html.parser")

    report_lines.extend([
        "=== SABINA / SCENTHUNTER DIAGNOSTIC V3 ===",
        f"STATUS: {response.status_code}",
        f"FINAL URL: {response.url}",
        f"HTML LEN: {len(html)}",
        "",
        "=== RAW MIU PRODUCT LINKS ===",
    ])

    raw = []
    seen_urls = set()

    for anchor in soup.find_all("a", href=True):
        product_url = urljoin(BASE, anchor["href"])
        anchor_text = clean(" ".join(filter(None, [
            anchor.get("title"),
            anchor.get("aria-label"),
            anchor.get_text(" ", strip=True),
        ])))

        nearby_text = ""
        node = anchor
        for _ in range(6):
            node = getattr(node, "parent", None)
            if node is None:
                break
            candidate = clean(node.get_text(" ", strip=True))
            if "€" in candidate:
                nearby_text = candidate[:600]
                break

        haystack = (anchor_text + " " + nearby_text + " " + product_url).lower()

        if ("miu" in haystack or "miutine" in haystack) and product_url not in seen_urls:
            seen_urls.add(product_url)
            raw.append((anchor_text, product_url, nearby_text))

    report_lines.append(f"RAW COUNT: {len(raw)}")

    for index, (text, product_url, nearby) in enumerate(raw, 1):
        report_lines.append(f"[{index}] TEXT: {text}")
        report_lines.append(f"    URL: {product_url}")
        if nearby:
            report_lines.append(f"    BLOCK: {nearby[:300]}")

    report_lines.extend(["", "=== CURRENT SCRAPER _parse_html ==="])

    scraper_module = None
    try:
        try:
            scraper_module = importlib.import_module("backend.scrapers.sabina.scraper")
        except ModuleNotFoundError:
            scraper_module = importlib.import_module("scrapers.sabina.scraper")

        parsed = scraper_module._parse_html(html, QUERY)
        report_lines.append(f"PARSED COUNT: {len(parsed)}")

        for index, product in enumerate(parsed, 1):
            report_lines.append(
                f"[{index}] {product.get('name')} | {product.get('price')} | {product.get('url')}"
            )
    except Exception as exc:
        report_lines.append(f"PARSE ERROR: {type(exc).__name__}: {exc}")

    report_lines.extend(["", "=== CURRENT SCRAPER search() ==="])

    try:
        if scraper_module is None:
            raise RuntimeError("Modulo scraper Sabina non caricato")

        final_results = scraper_module.search(QUERY)
        report_lines.append(f"SEARCH COUNT: {len(final_results)}")

        for index, product in enumerate(final_results, 1):
            report_lines.append(
                f"[{index}] {product.get('name')} | {product.get('price')} | {product.get('url')}"
            )
    except Exception as exc:
        report_lines.append(f"SEARCH ERROR: {type(exc).__name__}: {exc}")

    report_lines.extend(["", "=== PRODUCT STRING CHECKS ==="])

    normalized_html = html.lower().replace("’", "'").replace("`", "'")

    checks = [
        "miutine",
        "l'eau de muguet",
        "l'eau bleue",
        "l'eau rosee",
        "l'eau rosée",
        "fleur de lait",
        "miumiu fleur de lait",
    ]

    for check in checks:
        report_lines.append(f"{check} => {check in normalized_html}")

    report = "\\n".join(report_lines)

    output_path = Path(__file__).resolve().parent / "sabina_parser_report_v3.txt"
    output_path.write_text(report, encoding="utf-8")

    print(report)
    print()
    print("REPORT SAVED:", output_path)

if __name__ == "__main__":
    main()
