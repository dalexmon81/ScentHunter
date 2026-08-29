# backend/scrapers/deloox/scraper.py
"""
Deloox scraper - versione corretta con primary + fallback deterministico.
"""
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re
from typing import List, Dict, Optional

BASE_URL = "https://www.deloox.fr"
SEARCH_URL = "https://www.deloox.fr/chercher.html"

CONNECT_TIMEOUT = 4
READ_TIMEOUT = 8
MAX_PRODUCT_PAGES = 12

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

def is_blocked_or_invalid_response(response: Optional[requests.Response]) -> bool:
    if response is None:
        return True
    status = response.status_code
    if status in {403, 429, 500, 502, 503, 504}:
        return True
    text = response.text or ""
    if len(text) < 1000:
        return True
    lower = text.lower()
    markers = ["captcha", "cloudflare", "just a moment", "access denied",
               "verify you are human", "enable javascript", "challenge"]
    if any(m in lower for m in markers):
        return True
    return False

def extract_candidate_urls_from_search(html: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/parfum-" in href or "/produit-" in href or re.search(r'/p-\d+', href):
            urls.append(urljoin(BASE_URL, href))
    seen = set()
    deduped = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            deduped.append(u)
    return deduped

def parse_product_page(html: str, product_url: str) -> Optional[Dict]:
    soup = BeautifulSoup(html, "html.parser")
    name = None
    price = None
    name_el = soup.find("h1")
    if name_el:
        name = name_el.get_text(strip=True)
    price_el = soup.find("span", class_=re.compile(r"price|prix", re.I))
    if price_el:
        price_text = price_el.get_text(strip=True)
        m = re.search(r"[\d]+[,.]?\d*", price_text.replace(",", "."))
        if m:
            price = float(m.group())
    stock_text = soup.get_text().lower()
    in_stock = True if "disponible" in stock_text or "in stock" in stock_text else True
    if not name:
        return None
    return {"store": "deloox", "name": name, "price": price, "currency": "EUR", "in_stock": in_stock, "url": product_url}

def primary_search(query: str) -> List[Dict]:
    params = {"q": query}
    try:
        resp = requests.get(SEARCH_URL, params=params, headers=HEADERS, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
    except Exception:
        return []
    if is_blocked_or_invalid_response(resp):
        return []
    candidate_urls = extract_candidate_urls_from_search(resp.text)
    if not candidate_urls:
        return []
    results = []
    for url in candidate_urls[:MAX_PRODUCT_PAGES]:
        try:
            prod_resp = requests.get(url, headers=HEADERS, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
        except Exception:
            continue
        if is_blocked_or_invalid_response(prod_resp):
            continue
        parsed = parse_product_page(prod_resp.text, url)
        if parsed:
            results.append(parsed)
    return results

def fallback_search(query: str) -> List[Dict]:
    fallback_url = "https://www.deloox.fr/parfums.html"
    try:
        resp = requests.get(fallback_url, headers=HEADERS, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
    except Exception:
        return []
    if is_blocked_or_invalid_response(resp):
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    candidate_urls = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True).lower()
        if ("/parfum-" in href or "/produit-" in href) and query.lower() in text:
            candidate_urls.append(urljoin(BASE_URL, href))
    if not candidate_urls:
        return []
    results = []
    for url in candidate_urls[:MAX_PRODUCT_PAGES]:
        try:
            prod_resp = requests.get(url, headers=HEADERS, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
        except Exception:
            continue
        if is_blocked_or_invalid_response(prod_resp):
            continue
        parsed = parse_product_page(prod_resp.text, url)
        if parsed:
            results.append(parsed)
    return results

def deduplicate(results: List[Dict]) -> List[Dict]:
    seen = set()
    deduped = []
    for r in results:
        key = (r.get("name", "").lower(), r.get("price"), r.get("url", ""))
        if key not in seen:
            seen.add(key)
            deduped.append(r)
    return deduped

def run_store(query: str) -> List[Dict]:
    results = primary_search(query)
    if results:
        return deduplicate(results)
    fallback_results = fallback_search(query)
    return deduplicate(fallback_results)

def search(query: str) -> List[Dict]:
    return run_store(query)
