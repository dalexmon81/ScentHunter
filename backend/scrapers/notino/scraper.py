import json
import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


STORE = "Notino"
BASE_URL = "https://www.notino.fr"
SEARCH_URL = BASE_URL + "/search.asp"
TIMEOUT = 25

SCRAPER_VERSION = "notino-DIAGNOSTIC-2026-08-18-v2"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
}

P_ID_RE = re.compile(r"/p-(\d+)/?(?:$|[?#])", re.I)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value):
    return re.sub(
        r"\s+",
        " ",
        re.sub(r"[^a-z0-9]+", " ",
                clean(value).lower())
    ).strip()


def same_host(url):
    try:
        host = urlparse(url).netloc.lower()
        return host == "notino.fr" or host.endswith(".notino.fr")
    except Exception:
        return False


def tokens(query):
    ignored = {
        "eau", "de", "parfum", "perfume", "edp", "edt",
        "extrait", "spray", "pour", "homme", "femme",
        "mixte", "men", "women", "for", "by",
    }
    return [
        x for x in norm(query).split()
        if len(x) > 1 and x not in ignored
    ]


def url_has_query_tokens(url, query):
    value = norm(urlparse(url).path.replace("/", " "))
    wanted = tokens(query)
    return bool(wanted) and all(x in value for x in wanted)


def href_record(anchor, page_url):
    href = clean(anchor.get("href"))
    if not href:
        return None

    absolute = urljoin(page_url, href)
    if not same_host(absolute):
        return None

    text = clean(anchor.get_text(" ", strip=True))
    aria = clean(anchor.get("aria-label"))
    title = clean(anchor.get("title"))

    img = anchor.find("img")
    alt = clean(img.get("alt")) if img else ""

    path = urlparse(absolute).path.rstrip("/") or "/"
    p_match = P_ID_RE.search(path + "/")

    return {
        "url": absolute.split("#", 1)[0],
        "path": path,
        "text": text[:300],
        "aria": aria[:200],
        "title": title[:200],
        "img_alt": alt[:200],
        "has_p_id": bool(p_match),
        "product_id": p_match.group(1) if p_match else None,
        "url_matches_query": url_has_query_tokens(absolute, CURRENT_QUERY),
    }


def jsonld_summary(soup):
    result = []

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
            if not isinstance(item, dict):
                continue

            result.append({
                "type": item.get("@type"),
                "name": clean(item.get("name"))[:200],
                "url": clean(item.get("url")),
                "sku": clean(item.get("sku")),
                "brand": (
                    clean(item.get("brand", {}).get("name"))
                    if isinstance(item.get("brand"), dict)
                    else clean(item.get("brand"))
                ),
            })

    return result


def page_snapshot(response, query):
    soup = BeautifulSoup(response.text, "html.parser")

    h1 = clean(
        soup.select_one("h1").get_text(" ", strip=True)
        if soup.select_one("h1")
        else ""
    )

    title = clean(soup.title.get_text(" ", strip=True)) if soup.title else ""

    anchors = []
    seen = set()

    for anchor in soup.find_all("a", href=True):
        record = href_record(anchor, response.url)
        if not record:
            continue

        key = record["url"].lower()

        if key in seen:
            continue

        seen.add(key)
        anchors.append(record)

    p_links = [
        x for x in anchors
        if x["has_p_id"]
    ]

    query_url_links = [
        x for x in anchors
        if x["url_matches_query"]
    ]

    relevant = []
    wanted = tokens(query)

    for item in anchors:
        haystack = norm(
            " ".join([
                item["url"],
                item["text"],
                item["aria"],
                item["title"],
                item["img_alt"],
            ])
        )

        if wanted and all(token in haystack for token in wanted):
            relevant.append(item)

    types = []
    for item in jsonld_summary(soup):
        if item["type"] not in types:
            types.append(item["type"])

    return {
        "status": response.status_code,
        "final_url": response.url,
        "bytes": len(response.content),
        "title": title,
        "h1": h1,
        "anchors_total": len(anchors),
        "p_id_links": len(p_links),
        "query_url_links": len(query_url_links),
        "relevant_links": len(relevant),
        "jsonld_types": types,
        "jsonld": jsonld_summary(soup)[:20],
        "p_id_links_detail": p_links[:100],
        "query_url_links_detail": query_url_links[:100],
        "relevant_links_detail": relevant[:100],
    }


def get(session, url, params=None):
    print(
        f"NOTINO_DIAG_HTTP: GET {url}"
        f"{'?' + '&'.join(f'{k}={v}' for k,v in params.items()) if params else ''}",
        flush=True,
    )

    try:
        response = session.get(
            url,
            params=params,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
    except Exception as exc:
        print(
            f"NOTINO_DIAG_HTTP_ERROR: {type(exc).__name__}: {exc}",
            flush=True,
        )
        return None

    print(
        f"NOTINO_DIAG_HTTP: status={response.status_code} "
        f"url={response.url} bytes={len(response.content)}",
        flush=True,
    )

    return response


def search(query):
    global CURRENT_QUERY
    CURRENT_QUERY = clean(query)

    print(
        f"NOTINO_DIAG_VERSION: {SCRAPER_VERSION}",
        flush=True,
    )
    print(
        f"NOTINO_DIAG_START: query={CURRENT_QUERY!r}",
        flush=True,
    )

    if not CURRENT_QUERY:
        return []

    session = requests.Session()

    try:
        # STEP 1: exact endpoint requested by the user.
        search_response = get(
            session,
            SEARCH_URL,
            {"exps": CURRENT_QUERY},
        )

        if search_response is None:
            return [{
                "diagnostic": True,
                "stage": "search_request",
                "error": "request_failed",
            }]

        search_data = page_snapshot(
            search_response,
            CURRENT_QUERY,
        )

        print(
            "NOTINO_DIAG_SEARCH: "
            f"title={search_data['title']!r} "
            f"h1={search_data['h1']!r} "
            f"anchors={search_data['anchors_total']} "
            f"p_id={search_data['p_id_links']} "
            f"query_url={search_data['query_url_links']} "
            f"relevant={search_data['relevant_links']}",
            flush=True,
        )

        # STEP 2: DO NOT decide which URL is a product.
        # First print every structurally interesting URL from the search page.
        interesting = []
        seen = set()

        for group in (
            search_data["query_url_links_detail"],
            search_data["p_id_links_detail"],
            search_data["relevant_links_detail"],
        ):
            for item in group:
                key = item["url"].lower()
                if key in seen:
                    continue
                seen.add(key)
                interesting.append(item)

        print(
            f"NOTINO_DIAG_INTERESTING_COUNT: {len(interesting)}",
            flush=True,
        )

        for i, item in enumerate(interesting[:150], 1):
            print(
                f"NOTINO_DIAG_SEARCH_LINK[{i}]: "
                f"p_id={item['product_id']} "
                f"query_url={item['url_matches_query']} "
                f"url={item['url']} "
                f"text={item['text']!r} "
                f"alt={item['img_alt']!r}",
                flush=True,
            )

        # STEP 3: Open every query-relevant URL, regardless of whether it
        # contains /p-ID/. This is the critical diagnostic step.
        to_open = []
        seen_open = set()

        for item in interesting:
            if not (
                item["url_matches_query"]
                or item["has_p_id"]
            ):
                continue

            url = item["url"]

            if url.lower() == search_response.url.lower():
                continue

            if url.lower() in seen_open:
                continue

            seen_open.add(url.lower())
            to_open.append(url)

        print(
            f"NOTINO_DIAG_OPEN_COUNT: {len(to_open)}",
            flush=True,
        )

        opened = []

        for i, url in enumerate(to_open[:50], 1):
            response = get(session, url)

            if response is None:
                print(
                    f"NOTINO_DIAG_OPEN[{i}]: FAILED url={url}",
                    flush=True,
                )
                continue

            snapshot = page_snapshot(
                response,
                CURRENT_QUERY,
            )

            print(
                f"NOTINO_DIAG_OPEN[{i}]: "
                f"url={response.url} "
                f"title={snapshot['title']!r} "
                f"h1={snapshot['h1']!r} "
                f"anchors={snapshot['anchors_total']} "
                f"p_id={snapshot['p_id_links']} "
                f"query_url={snapshot['query_url_links']} "
                f"jsonld={snapshot['jsonld_types']}",
                flush=True,
            )

            for j, item in enumerate(
                snapshot["p_id_links_detail"][:50],
                1,
            ):
                print(
                    f"NOTINO_DIAG_NESTED[{i}.{j}]: "
                    f"p_id={item['product_id']} "
                    f"url={item['url']} "
                    f"text={item['text']!r} "
                    f"alt={item['img_alt']!r}",
                    flush=True,
                )

            opened.append({
                "url": response.url,
                "snapshot": snapshot,
            })

        print(
            "NOTINO_DIAG_END: "
            f"search_p_id={search_data['p_id_links']} "
            f"search_relevant={search_data['relevant_links']} "
            f"opened={len(opened)}",
            flush=True,
        )

        # /test-store expects a list. Return one diagnostic object rather
        # than pretending these observations are real products.
        return [{
            "diagnostic": True,
            "scraper_version": SCRAPER_VERSION,
            "query": CURRENT_QUERY,
            "search": search_data,
            "opened_pages": opened,
        }]

    finally:
        session.close()


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
