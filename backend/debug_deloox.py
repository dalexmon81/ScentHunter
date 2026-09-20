"""ScentHunter — diagnostic Deloox for the 4 remaining Born in Roma variants.

IMPORTANT:
- Read-only diagnostic. It does NOT modify the production scraper.
- Target variants ONLY:
    1. Born in Roma Uomo The Gold
    2. Born in Roma Uomo Ivory
    3. Born in Roma Donna The Gold
    4. Born in Roma Donna Ivory

This file also exposes the diagnostic through:
    GET /diagnose-deloox-born4
"""

from __future__ import annotations

import io
import json
import re
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from fastapi import APIRouter

router = APIRouter()

BASE = "https://www.deloox.be"
TIMEOUT = (3.0, 8.0)

TARGETS = [
    {
        "canonical": "Born in Roma Uomo The Gold",
        "aliases": [
            "Born in Roma Uomo The Gold",
            "Born In Roma The Gold Uomo",
            "Valentino Born In Roma The Gold Uomo",
            "The Gold Uomo",
        ],
        "gender": "uomo",
        "known_category_urls": [
            f"{BASE}/categorie/1075744/eau-de-toilette-homme.html",
            f"{BASE}/categorie/1075744/eau-de-toilette-homme",
            f"{BASE}/categorie/1075744/eau-de-toilette-homme.html?page=2",
        ],
    },
    {
        "canonical": "Born in Roma Uomo Ivory",
        "aliases": [
            "Born in Roma Uomo Ivory",
            "Born In Roma Ivory Uomo",
            "Valentino Born In Roma Ivory Uomo",
            "Ivory Uomo",
        ],
        "gender": "uomo",
        "known_category_urls": [
            f"{BASE}/categorie/1075744/eau-de-toilette-homme.html",
            f"{BASE}/categorie/1075744/eau-de-toilette-homme",
            f"{BASE}/categorie/1075744/eau-de-toilette-homme.html?page=2",
        ],
    },
    {
        "canonical": "Born in Roma Donna The Gold",
        "aliases": [
            "Born in Roma Donna The Gold",
            "Born In Roma The Gold Donna",
            "Valentino Born In Roma The Gold Donna",
            "The Gold Donna",
        ],
        "gender": "donna",
        "known_category_urls": [
            f"{BASE}/categorie/1075743/eau-de-parfum-femme.html",
            f"{BASE}/categorie/1075743/eau-de-parfum-femme",
            f"{BASE}/categorie/1075742/eau-de-parfum-femme.html",
            f"{BASE}/categorie/1075742/eau-de-parfum-femme",
        ],
    },
    {
        "canonical": "Born in Roma Donna Ivory",
        "aliases": [
            "Born in Roma Donna Ivory",
            "Donna Born in Roma Ivory",
            "Born In Roma Ivory Donna",
            "Valentino Donna Born In Roma Ivory",
            "Ivory Donna",
        ],
        "gender": "donna",
        "known_category_urls": [
            f"{BASE}/categorie/1075743/eau-de-parfum-femme.html",
            f"{BASE}/categorie/1075743/eau-de-parfum-femme",
            f"{BASE}/categorie/1075742/eau-de-parfum-femme.html",
            f"{BASE}/categorie/1075742/eau-de-parfum-femme",
        ],
    },
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}

PRODUCT_RE = re.compile(
    r"(?:https?:\\?/\\?/[^\"'<>\\s]+)?/"
    r"(?:produit|product|producto|prodotto)/"
    r"\d+/[^\"'<>\\s?#]+",
    re.I,
)

NON_FRAGRANCE = (
    "body mist", "body spray", "body lotion", "body cream", "deodorant",
    "after shave", "aftershave", "shower gel", "hair mist",
    "hair body mist", "hair and body mist", "body hair mist",
)

NON_PRODUCT_PACKAGING = (
    "coffret", "cadeau", "gift set", "giftset", "set cadeau", "geschenkset",
)


def clean(v) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def norm(v) -> str:
    return re.sub(r"[^a-z0-9]+", " ", clean(v).lower()).strip()


def compact(v) -> str:
    return norm(v).replace(" ", "")


def tokens(v):
    return {x for x in norm(v).split() if len(x) > 1}


def get(session, url):
    try:
        r = session.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        if r.status_code == 200 and r.text:
            return r
        return None
    except requests.RequestException:
        return None


def is_product_url(url):
    try:
        p = urlparse(url)
    except Exception:
        return False

    host = p.netloc.lower().split(":", 1)[0]
    if host not in {"deloox.be", "www.deloox.be"}:
        return False

    return bool(re.search(
        r"/(?:product|produit|producto|prodotto)/\d+/",
        p.path,
        re.I,
    ))


def product_url(raw):
    raw = clean(raw).replace("\\/", "/")
    if not raw:
        return ""

    if raw.startswith("//"):
        raw = "https:" + raw
    elif raw.startswith("/"):
        raw = urljoin(BASE + "/", raw)

    raw = raw.split("#", 1)[0].split("?", 1)[0]
    return raw if is_product_url(raw) else ""


def slug(url):
    try:
        return clean(urlparse(url).path.rsplit("/", 1)[-1])
    except Exception:
        return ""


def excluded(url):
    s = norm(slug(url))
    return (
        any(norm(x) in s for x in NON_FRAGRANCE)
        or any(norm(x) in s for x in NON_PRODUCT_PACKAGING)
    )


def target_score(text, target):
    hay = norm(text)
    best = 0
    best_alias = ""

    for alias in target["aliases"]:
        at = tokens(alias)
        if not at:
            continue

        hits = sum(t in hay for t in at)
        score = hits / len(at)

        if {"born", "roma"} <= at and {"born", "roma"} <= tokens(text):
            score += 0.15

        if score > best:
            best = score
            best_alias = alias

    return min(best, 1.0), best_alias


def extract_urls(html):
    found = set()
    soup = BeautifulSoup(html, "html.parser")

    for a in soup.find_all("a", href=True):
        u = product_url(a.get("href"))
        if u and not excluded(u):
            found.add(u)

    for raw in PRODUCT_RE.findall(html or ""):
        u = product_url(raw)
        if u and not excluded(u):
            found.add(u)

    return sorted(found)


def url_text(url):
    s = slug(url)
    s = re.sub(r"[-_]+", " ", s)
    return clean(s)


def extract_context_for_url(html, url):
    soup = BeautifulSoup(html, "html.parser")

    for a in soup.find_all("a", href=True):
        u = product_url(a.get("href"))
        if u != url:
            continue

        node = a
        best = clean(a.get_text(" ", strip=True))

        for _ in range(8):
            node = node.parent
            if not node:
                break

            text = clean(node.get_text(" ", strip=True))
            if 3 <= len(text) <= 3000 and len(text) > len(best):
                best = text

            if re.search(r"€|prix|price|prijs|livraison|delivery", text, re.I):
                break

        return best

    marker = url.split("/produit/", 1)[-1]
    pos = html.lower().find(marker.lower())
    if pos >= 0:
        frag = html[max(0, pos - 5000):pos + 10000]
        return clean(BeautifulSoup(frag, "html.parser").get_text(" ", strip=True))

    return ""


def discover_search_surface(session, query):
    encoded = quote_plus(query)
    urls = set()
    pages = []

    for page in range(1, 11):
        endpoint = (
            f"{BASE}/chercher.html?q={encoded}"
            if page == 1
            else f"{BASE}/chercher.html?q={encoded}&page={page}"
        )

        r = get(session, endpoint)
        if not r:
            break

        pages.append({
            "page": page,
            "requested_url": endpoint,
            "final_url": r.url,
            "status": r.status_code,
            "bytes": len(r.text or ""),
        })

        page_urls = extract_urls(r.text)
        born_urls = [
            u for u in page_urls
            if "born" in norm(slug(u))
            and "roma" in norm(slug(u))
        ]

        urls.update(born_urls)

        if not page_urls and page > 1:
            break

    return sorted(urls), pages


def discover_category_surface(session, urls):
    all_urls = set()
    page_reports = []

    for url in dict.fromkeys(urls):
        r = get(session, url)

        report = {
            "requested_url": url,
            "final_url": r.url if r else None,
            "status": r.status_code if r else None,
            "bytes": len(r.text or "") if r else 0,
            "reachable": bool(r),
            "born_urls": [],
        }

        if r:
            candidates = extract_urls(r.text)
            born = [
                u for u in candidates
                if "born" in norm(slug(u))
                and "roma" in norm(slug(u))
            ]
            report["born_urls"] = sorted(born)
            all_urls.update(born)

        page_reports.append(report)

    return sorted(all_urls), page_reports


def parse_jsonld_products(html):
    out = []
    soup = BeautifulSoup(html, "html.parser")

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.get_text())
        except Exception:
            continue

        queue = list(data) if isinstance(data, list) else [data]

        while queue:
            item = queue.pop(0)

            if isinstance(item, list):
                queue.extend(item)
                continue

            if not isinstance(item, dict):
                continue

            typ = item.get("@type")
            if typ == "Product" or (
                isinstance(typ, list) and "Product" in typ
            ):
                out.append(item)

            graph = item.get("@graph")
            if isinstance(graph, list):
                queue.extend(graph)

    return out


def parse_direct_product(session, url, target):
    r = get(session, url)
    result = {
        "url": url,
        "reachable": bool(r),
        "status": r.status_code if r else None,
        "bytes": len(r.text or "") if r else 0,
        "http_ok": bool(r and r.status_code == 200),
        "jsonld_products": 0,
        "jsonld_names": [],
        "target_name_match": False,
        "target_name_match_alias": "",
        "offers": 0,
        "offer_details": [],
    }

    if not r:
        return result

    products = parse_jsonld_products(r.text)
    result["jsonld_products"] = len(products)

    for p in products:
        name = clean(p.get("name"))
        if name:
            result["jsonld_names"].append(name)

        score, alias = target_score(name, target)
        if score >= 0.60:
            result["target_name_match"] = True
            result["target_name_match_alias"] = alias

        offers = p.get("offers")
        if isinstance(offers, dict):
            offers = [offers]
        elif not isinstance(offers, list):
            offers = []

        for offer in offers:
            if not isinstance(offer, dict):
                continue

            result["offers"] += 1
            result["offer_details"].append({
                "price": offer.get("price"),
                "availability": offer.get("availability"),
                "currency": offer.get("priceCurrency"),
            })

    return result


def find_target_urls(all_urls, target):
    matches = []

    for url in all_urls:
        text = url_text(url)
        score, alias = target_score(text, target)
        t = tokens(text)
        distinctive = {"gold", "ivory"} & t
        gender = {"uomo", "donna"} & t

        if (
            score >= 0.60
            or ({"born", "roma"} <= t and distinctive and gender)
        ):
            matches.append({
                "url": url,
                "url_text": text,
                "score": round(score, 3),
                "matched_alias": alias,
            })

    matches.sort(key=lambda x: (-x["score"], x["url"]))
    return matches


def try_web_search_surface(session, target):
    results = []

    for alias in target["aliases"]:
        endpoint = f"{BASE}/chercher.html?q={quote_plus(alias)}"
        r = get(session, endpoint)

        item = {
            "query": alias,
            "requested_url": endpoint,
            "final_url": r.url if r else None,
            "status": r.status_code if r else None,
            "bytes": len(r.text or "") if r else 0,
            "urls": [],
        }

        if r:
            candidates = extract_urls(r.text)
            scored = []

            for u in candidates:
                score, matched = target_score(url_text(u), target)
                if score >= 0.45:
                    scored.append({
                        "url": u,
                        "score": round(score, 3),
                        "matched_alias": matched,
                    })

            scored.sort(key=lambda x: (-x["score"], x["url"]))
            item["urls"] = scored

        results.append(item)

    return results


def try_import_production_scraper():
    roots = [
        Path.cwd(),
        Path(__file__).resolve().parent,
        Path(__file__).resolve().parent.parent,
    ]

    for root in roots:
        if (root / "scrapers" / "deloox" / "scraper.py").exists():
            if str(root) not in sys.path:
                sys.path.insert(0, str(root))
            try:
                from scrapers.deloox import scraper as deloox
                return deloox
            except Exception:
                pass

        if (root / "backend" / "scrapers" / "deloox" / "scraper.py").exists():
            if str(root) not in sys.path:
                sys.path.insert(0, str(root))
            try:
                from backend.scrapers.deloox import scraper as deloox
                return deloox
            except Exception:
                pass

    return None


def run_production_scraper_test(target, production_module):
    if production_module is None:
        return {
            "available": False,
            "reason": "Could not import production Deloox scraper",
        }

    try:
        rows = production_module.search("Born in Roma")
    except Exception as exc:
        return {
            "available": True,
            "error": f"{type(exc).__name__}: {exc}",
        }

    matches = []

    for row in rows or []:
        text = " ".join(
            str(row.get(k, ""))
            for k in ("brand", "name", "url")
        )
        score, alias = target_score(text, target)

        if score >= 0.60:
            matches.append({
                "name": row.get("name"),
                "brand": row.get("brand"),
                "url": row.get("url"),
                "price": row.get("price"),
                "price_num": row.get("price_num"),
                "size_ml": row.get("size_ml"),
                "score": round(score, 3),
                "matched_alias": alias,
            })

    return {
        "available": True,
        "production_total_rows": len(rows or []),
        "target_rows": matches,
    }


def main():
    started = time.time()
    session = requests.Session()

    output = {
        "diagnostic": "deloox-born-in-roma-4-targets-v1",
        "read_only": True,
        "targets": [x["canonical"] for x in TARGETS],
        "base": BASE,
        "search_surface": {},
        "category_surface": {},
        "target_results": {},
        "production_scraper": {},
        "timing_seconds": None,
    }

    born_urls, search_pages = discover_search_surface(session, "Born in Roma")
    output["search_surface"] = {
        "query": "Born in Roma",
        "pages": search_pages,
        "born_product_url_count": len(born_urls),
        "born_product_urls": born_urls,
    }

    category_urls = []
    for target in TARGETS:
        category_urls.extend(target["known_category_urls"])

    category_urls_found, category_reports = discover_category_surface(
        session,
        category_urls,
    )

    output["category_surface"] = {
        "requested_page_count": len(category_reports),
        "pages": category_reports,
        "born_product_url_count": len(category_urls_found),
        "born_product_urls": category_urls_found,
    }

    union_urls = sorted(set(born_urls) | set(category_urls_found))

    for target in TARGETS:
        exact_search = try_web_search_surface(session, target)
        exact_urls = set()

        for item in exact_search:
            for candidate in item.get("urls", []):
                exact_urls.add(candidate["url"])

        target_union = sorted(set(union_urls) | exact_urls)
        url_matches = find_target_urls(target_union, target)

        parsed = []
        for item in url_matches[:20]:
            parsed.append(parse_direct_product(session, item["url"], target))

        production_module = try_import_production_scraper()
        production = run_production_scraper_test(
            target,
            production_module,
        )

        output["target_results"][target["canonical"]] = {
            "exact_alias_search": exact_search,
            "candidate_url_matches": url_matches,
            "direct_product_parse": parsed,
            "production_scraper": production,
        }

    output["production_scraper"]["module_imported"] = (
        try_import_production_scraper() is not None
    )

    output["timing_seconds"] = round(time.time() - started, 2)

    print(json.dumps(output, ensure_ascii=False, indent=2))


@router.get("/diagnose-deloox-born4")
def diagnose_deloox_born4():
    """HTTP endpoint for the existing read-only Born4 diagnostic."""
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        main()
    return json.loads(buffer.getvalue().strip())


if __name__ == "__main__":
    main()
