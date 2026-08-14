import requests
import re
import json
import time
import hashlib
from pathlib import Path
from urllib.parse import quote_plus

BASE = "https://www.sabina.com"
QUERY = "Jean Paul Gaultier Le Beau"
RUNS = 5

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

OUT = Path("sabina_raw_diagnostic")
OUT.mkdir(exist_ok=True)


def product_strings(html):
    """Look only at Sabina's raw response. No ScentHunter matching."""
    text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    low = text.lower()

    needles = [
        "le beau",
        "narcisse",
        "flower",
        "paradise garden",
        "le parfum",
        "jean paul gaultier",
    ]

    return [needle for needle in needles if needle in low]


summary = []

for run in range(1, RUNS + 1):
    session = requests.Session()
    url = BASE + "/it/ricerca?search_query=" + quote_plus(QUERY)
    started = time.time()

    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=30,
            allow_redirects=True,
        )

        elapsed = round(time.time() - started, 3)
        html = response.text
        html_low = html.lower().replace("’", "'")

        challenge_words = [
            "captcha",
            "cloudflare",
            "attention required",
            "verify you are human",
            "cf-chl",
            "challenge-platform",
        ]

        meta = {
            "run": run,
            "request_url": url,
            "final_url": response.url,
            "status": response.status_code,
            "content_type": response.headers.get("content-type"),
            "server": response.headers.get("server"),
            "cf_ray": response.headers.get("cf-ray"),
            "elapsed_seconds": elapsed,
            "html_length": len(html),
            "cookies": session.cookies.get_dict(),
            "challenge_words": [
                word for word in challenge_words if word in html_low
            ],
            "product_strings_found": product_strings(html),
        }

        raw_path = OUT / f"run_{run}.html"
        json_path = OUT / f"run_{run}.json"

        raw_path.write_text(html, encoding="utf-8")

        meta["raw_sha256"] = hashlib.sha256(
            html.encode("utf-8", errors="replace")
        ).hexdigest()

        json_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        summary.append(meta)

    except Exception as exc:
        meta = {
            "run": run,
            "request_url": url,
            "error": repr(exc),
        }

        (OUT / f"run_{run}.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        summary.append(meta)

    if run < RUNS:
        time.sleep(1)

lines = [
    "=== SCENTHUNTER / SABINA RAW 5-RUN DIAGNOSTIC ===",
    f"QUERY: {QUERY}",
    f"RUNS: {RUNS}",
    "",
]

for item in summary:
    lines.append(f"--- RUN {item['run']} ---")

    if "error" in item:
        lines.append(f"ERROR: {item['error']}")
        lines.append("")
        continue

    lines.extend([
        f"STATUS: {item['status']}",
        f"FINAL URL: {item['final_url']}",
        f"CONTENT-TYPE: {item['content_type']}",
        f"HTML LEN: {item['html_length']}",
        f"ELAPSED: {item['elapsed_seconds']}s",
        f"COOKIES: {item['cookies']}",
        f"CHALLENGES: {item['challenge_words']}",
        f"PRODUCT STRINGS: {item['product_strings_found']}",
        f"RAW SHA256: {item['raw_sha256']}",
        "",
    ])

Path("sabina_http_diagnostic.txt").write_text(
    "\n".join(lines),
    encoding="utf-8",
)

(OUT / "summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

print("\n".join(lines))
print(f"Raw responses: {OUT.resolve()}")
print("Summary: sabina_http_diagnostic.txt")
