import json
import re
import time
from urllib.parse import urljoin, urlparse, quote

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

BASE_URL = "https://www.notino.fr"
SEARCH_URL = BASE_URL + "/search.asp"
TIMEOUT = 30000
SCRAPER_VERSION = "notino-DIAGNOSTIC-2026-08-18-v5"

P_ID_RE = re.compile(r"/p-(\d+)(?:/|$)", re.I)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def absolute_url(page_url, href):
    if not href:
        return ""
    return urljoin(page_url, href).split("#", 1)[0]


def inspect_search_page(page, query):
    html = page.content()
    soup = BeautifulSoup(html, "html.parser")

    title = clean(page.title())
    h1 = ""
    try:
        h1 = clean(page.locator("h1").first.inner_text(timeout=3000))
    except Exception:
        pass

    anchors = []
    seen = set()

    for a in soup.find_all("a", href=True):
        url = absolute_url(page.url, a.get("href"))
        if not url:
            continue

        host = urlparse(url).netloc.lower()
        if host != "notino.fr" and not host.endswith(".notino.fr"):
            continue

        key = url.lower()
        if key in seen:
            continue
        seen.add(key)

        text = clean(a.get_text(" ", strip=True))
        img = a.find("img")
        alt = clean(img.get("alt")) if img else ""
        aria = clean(a.get("aria-label"))
        title_attr = clean(a.get("title"))

        p = P_ID_RE.search(urlparse(url).path.rstrip("/") + "/")

        haystack = clean(
            " ".join([url, text, alt, aria, title_attr])
        ).lower()

        query_tokens = [
            x for x in re.sub(r"[^a-z0-9]+", " ", query.lower()).split()
            if len(x) > 1
        ]

        query_match = (
            bool(query_tokens)
            and all(token in haystack for token in query_tokens)
        )

        if p or query_match:
            anchors.append({
                "url": url,
                "p_id": p.group(1) if p else None,
                "query_match": query_match,
                "text": text[:300],
                "alt": alt[:300],
                "aria": aria[:200],
                "title": title_attr[:200],
            })

    jsonld = []
    for script in soup.find_all(
        "script",
        attrs={"type": re.compile(r"application/ld\+json", re.I)},
    ):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        values = data if isinstance(data, list) else [data]
        for item in values:
            if isinstance(item, dict):
                jsonld.append({
                    "type": item.get("@type"),
                    "name": clean(item.get("name")),
                    "url": clean(item.get("url")),
                })

    print(
        f"NOTINO_V5_SEARCH: status=200 url={page.url} "
        f"bytes={len(html.encode('utf-8'))} title={title!r} "
        f"h1={h1!r} interesting_links={len(anchors)} "
        f"jsonld={len(jsonld)}",
        flush=True,
    )

    for i, item in enumerate(anchors[:150], 1):
        print(
            f"NOTINO_V5_LINK[{i}]: "
            f"p_id={item['p_id']} "
            f"query_match={item['query_match']} "
            f"url={item['url']} "
            f"text={item['text']!r} "
            f"alt={item['alt']!r}",
            flush=True,
        )

    return {
        "status": 200,
        "url": page.url,
        "bytes": len(html.encode("utf-8")),
        "title": title,
        "h1": h1,
        "interesting_links": anchors[:150],
        "jsonld": jsonld[:50],
    }


def search(query):
    query = clean(query)
    print(f"NOTINO_V5_VERSION: {SCRAPER_VERSION}", flush=True)
    print(f"NOTINO_V5_START: query={query!r}", flush=True)

    if not query:
        return []

    url = SEARCH_URL + "?exps=" + quote(query)

    report = {
        "diagnostic": True,
        "version": SCRAPER_VERSION,
        "query": query,
        "direct_browser_search": None,
    }

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )

        try:
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="fr-FR",
                viewport={"width": 1365, "height": 900},
            )

            try:
                page = context.new_page()
                started = time.perf_counter()

                response = page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=TIMEOUT,
                )

                try:
                    page.wait_for_load_state(
                        "networkidle",
                        timeout=12000,
                    )
                except Exception:
                    pass

                page.wait_for_timeout(1000)

                elapsed = round(time.perf_counter() - started, 3)

                if response is None:
                    raise RuntimeError(
                        "Playwright returned no main response"
                    )

                print(
                    f"NOTINO_V5_HTTP: status={response.status} "
                    f"url={page.url} elapsed={elapsed}s",
                    flush=True,
                )

                report["direct_browser_search"] = inspect_search_page(
                    page,
                    query,
                )
                report["direct_browser_search"]["elapsed"] = elapsed

            finally:
                context.close()

        finally:
            browser.close()

    print(
        "NOTINO_V5_END: "
        f"links={len(report['direct_browser_search']['interesting_links'])}",
        flush=True,
    )

    return [report]


def scrape(query):
    return search(query)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    args = parser.parse_args()

    print(
        json.dumps(
            search(args.query),
            ensure_ascii=False,
            indent=2,
        )
    )
