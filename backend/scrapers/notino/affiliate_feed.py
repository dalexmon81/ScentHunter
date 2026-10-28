"""Authenticated CJ/VIV XML feed integration for Notino.fr.

The feed's actual credential URL and access details are provided by the affiliate
network. This module accepts the documented Google Shopping XML export shape
without assuming a fixed namespace prefix or a specific feed URL.
"""
from __future__ import annotations

import gzip
import hashlib
import logging
import os
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable

import requests

LOGGER = logging.getLogger("scenthunter.notino_feed")
STORE_KEY = "notino"
STORE_LABEL = "Notino"
MARKET_HOST = "www.notino.fr"
TIMEOUT = (5.0, 30.0)
MAX_FEED_BYTES = 256 * 1024 * 1024
MAX_DECOMPRESSED_BYTES = 512 * 1024 * 1024
USER_AGENT = "ScentHunter/authorized-affiliate-feed (+price-comparison)"


class FeedImportError(RuntimeError):
    """A stable diagnostic with no secret-bearing URL or response body."""


@dataclass(frozen=True)
class NotinoOffer:
    external_id: str
    title: str
    brand: str
    gtin: str | None
    sku: str | None
    mpn: str | None
    size_ml: float
    price: float
    currency: str
    availability: str
    url: str
    image: str | None
    concentration: str | None


def _local(tag: str) -> str:
    return str(tag or "").rsplit("}", 1)[-1].lower()


def _values(node: ET.Element, names: Iterable[str]) -> list[str]:
    wanted = {name.lower() for name in names}
    found = []
    for child in list(node):
        if _local(child.tag) in wanted:
            text = (child.text or "").strip()
            if text:
                found.append(text)
            elif _local(child.tag) == "link":
                href = str(child.attrib.get("href") or "").strip()
                if href:
                    found.append(href)
    return found


def _first(node: ET.Element, *names: str) -> str:
    values = _values(node, names)
    return values[0] if values else ""


def _money(raw: str) -> tuple[Decimal | None, str]:
    text = str(raw or "").strip().replace("\u00a0", " ")
    match_currency = re.search(r"\b([A-Z]{3})\s*$", text, re.I)
    currency = match_currency.group(1).upper() if match_currency else ""
    if match_currency:
        text = text[:match_currency.start()].strip()
    text = re.sub(r"[^0-9,.-]", "", text)
    if not text:
        return None, currency
    if "," in text and "." in text:
        decimal = "," if text.rfind(",") > text.rfind(".") else "."
        thousands = "." if decimal == "," else ","
        text = text.replace(thousands, "").replace(decimal, ".")
    elif "," in text:
        tail = text.rsplit(",", 1)[1]
        text = text.replace(",", ".") if len(tail) in (1, 2) else text.replace(",", "")
    elif "." in text and len(text.rsplit(".", 1)[1]) not in (1, 2):
        text = text.replace(".", "")
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None, currency
    if not value.is_finite() or value <= 0:
        return None, currency
    return value.quantize(Decimal("0.01")), currency


def _size_ml(*values: str) -> float | None:
    text = " ".join(str(value or "") for value in values)
    matches = list(re.finditer(
        r"(?<![0-9])([0-9]+(?:[.,][0-9]+)?)\s*(ml|cl|l)\b",
        text,
        re.I,
    ))
    if not matches:
        return None
    # Prefer an explicit size field. If it contains several sizes, use the
    # first unit-bearing measurement in that field; title is only fallback.
    for source in values:
        matches = list(re.finditer(
            r"(?<![0-9])([0-9]+(?:[.,][0-9]+)?)\s*(ml|cl|l)\b",
            str(source or ""),
            re.I,
        ))
        if not matches:
            continue
        match = matches[0]
        try:
            value = float(match.group(1).replace(",", "."))
        except ValueError:
            continue
        value *= {"ml": 1.0, "cl": 10.0, "l": 1000.0}[match.group(2).lower()]
        return value if 1 <= value <= 10000 else None
    return None


def _concentration(*values: str) -> str | None:
    text = " ".join(str(value or "") for value in values).lower()
    for pattern, label in (
        (r"\beau de toilette\b|\bedt\b", "Eau de Toilette"),
        (r"\beau de parfum\b|\bedp\b", "Eau de Parfum"),
        (r"\beau de cologne\b|\bedc\b", "Eau de Cologne"),
        (r"\bextrait(?: de parfum)?\b", "Extrait de Parfum"),
        (r"\bparfum\b", "Parfum"),
    ):
        if re.search(pattern, text):
            return label
    return None


def _product_url(raw: str) -> str | None:
    parsed = urllib.parse.urlparse(str(raw or "").strip())
    host = (parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme != "https"
        or host not in {"notino.fr", "www.notino.fr"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
    ):
        return None
    path = re.sub(r"/{2,}", "/", parsed.path or "")
    if not path or path == "/" or path.lower().startswith((
        "/search", "/parfums", "/marques", "/login", "/account", "/cart",
        "/checkout", "/customer-service", "/wishlist",
    )):
        return None
    # Canonical product links remain on the French host. Feed redirects and
    # tracking query parameters do not become duplicate source offers.
    return urllib.parse.urlunparse(("https", MARKET_HOST, path, "", "", ""))


def _image_url(raw: str) -> str | None:
    parsed = urllib.parse.urlparse(str(raw or "").strip())
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return str(raw).strip()


def _parse_item(item: ET.Element) -> NotinoOffer | None:
    title = _first(item, "title", "name", "productname")
    brand = _first(item, "brand", "manufacturer", "vendor")
    external_id = _first(item, "id", "offerid", "productid")
    sku = _first(item, "sku", "g:id")
    gtin = _first(item, "gtin", "gtin13", "gtin12", "gtin14", "ean", "barcode")
    mpn = _first(item, "mpn", "manufacturer_part_number")
    raw_price = _first(item, "price", "saleprice", "currentprice")
    price, currency = _money(raw_price)
    currency = currency or _first(item, "currency", "pricecurrency").upper()
    raw_availability = _first(item, "availability", "stock", "availabilitystatus").lower().strip()
    if raw_availability in {"in stock", "instock", "in_stock", "available", "limited availability", "limitedavailability"}:
        availability = "in_stock"
    elif raw_availability in {"out of stock", "outofstock", "out_of_stock", "sold out", "unavailable"}:
        availability = "out_of_stock"
    elif raw_availability in {"preorder", "pre-order"}:
        availability = "preorder"
    else:
        availability = "unknown"

    raw_link = _first(item, "link", "url", "producturl")
    if not raw_link:
        # Atom <link href="..."/> contains its destination as an attribute.
        for child in list(item):
            if _local(child.tag) == "link" and child.attrib.get("href"):
                raw_link = str(child.attrib["href"]).strip()
                break

    raw_size = _first(item, "size", "volume", "capacity", "product_size", "g:size")
    size_ml = _size_ml(raw_size, title)  # explicit field is preferred
    image = _first(item, "image_link", "image", "imageurl", "g:image_link")
    if not image:
        for child in list(item):
            if _local(child.tag) == "image_link" and child.text:
                image = child.text.strip()
                break

    link = _product_url(raw_link)
    if not title or not brand or price is None or currency != "EUR" or not link or size_ml is None:
        return None
    if not external_id:
        external_id = gtin or sku or hashlib.sha256(
            f"{link}|{size_ml:g}|{title}".encode("utf-8")
        ).hexdigest()[:24]
    return NotinoOffer(
        external_id=external_id.strip(),
        title=re.sub(r"\s+", " ", title).strip(),
        brand=re.sub(r"\s+", " ", brand).strip(),
        gtin=gtin.strip() or None,
        sku=sku.strip() or None,
        mpn=mpn.strip() or None,
        size_ml=size_ml,
        price=float(price),
        currency=currency,
        availability=availability,
        url=link,
        image=_image_url(image),
        concentration=_concentration(title, raw_size),
    )


def parse_feed(data: bytes) -> list[NotinoOffer]:
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise FeedImportError("notino_feed_empty")
    raw = bytes(data)
    if len(raw) > MAX_FEED_BYTES:
        raise FeedImportError("notino_feed_too_large")
    if raw[:2] == b"\x1f\x8b":
        try:
            decompressor = gzip.GzipFile(fileobj=__import__("io").BytesIO(raw))
            raw = decompressor.read(MAX_DECOMPRESSED_BYTES + 1)
            decompressor.close()
        except (OSError, EOFError):
            raise FeedImportError("notino_feed_invalid_gzip") from None
        if len(raw) > MAX_DECOMPRESSED_BYTES:
            raise FeedImportError("notino_feed_decompressed_too_large")
    if not raw.strip():
        raise FeedImportError("notino_feed_empty")
    if re.search(br"<!DOCTYPE|<!ENTITY", raw, re.I):
        raise FeedImportError("notino_feed_unsafe_xml_declaration")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        raise FeedImportError("notino_feed_invalid_xml") from None
    root_name = _local(root.tag)
    if root_name not in {"rss", "feed", "channel", "catalog", "products", "productfeed"}:
        raise FeedImportError("notino_feed_unrecognized_root")
    candidates = [node for node in root.iter() if _local(node.tag) in {"item", "entry", "product"}]
    if not candidates and root_name in {"catalog", "products", "productfeed"}:
        candidates = [node for node in list(root) if len(list(node))]
    if not candidates:
        raise FeedImportError("notino_feed_no_product_entries")
    parsed = []
    for node in candidates:
        offer = _parse_item(node)
        if offer is not None:
            parsed.append(offer)
    if not parsed:
        raise FeedImportError("notino_feed_no_valid_priced_fr_offers")
    # Identical feed duplicates are discarded; real size variants stay distinct.
    unique = {}
    for offer in parsed:
        key = (
            offer.external_id,
            offer.url,
            offer.size_ml,
            offer.gtin or "",
            offer.sku or "",
        )
        unique[key] = offer
    return list(unique.values())


def _fetch_feed() -> bytes:
    feed_url = os.environ.get("NOTINO_CJ_FEED_URL", "").strip()
    username = os.environ.get("NOTINO_CJ_FEED_USERNAME", "").strip()
    password = os.environ.get("NOTINO_CJ_FEED_PASSWORD", "")
    if not feed_url or not username or not password:
        raise FeedImportError("notino_feed_credentials_missing")
    parsed = urllib.parse.urlparse(feed_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise FeedImportError("notino_feed_url_must_be_https_without_embedded_credentials")

    response = None
    try:
        response = requests.get(
            feed_url,
            auth=(username, password),
            headers={
                "Accept": "application/xml,text/xml,application/rss+xml,application/atom+xml,*/*",
                "Accept-Encoding": "gzip",
                "User-Agent": USER_AGENT,
            },
            timeout=TIMEOUT,
            stream=True,
            allow_redirects=False,
        )
        if response.status_code in (301, 302, 303, 307, 308):
            raise FeedImportError("notino_feed_redirect_refused")
        if response.status_code in (401, 403):
            raise FeedImportError("notino_feed_auth_denied")
        if response.status_code >= 400:
            raise FeedImportError(f"notino_feed_http_{response.status_code}")
        content_type = str(response.headers.get("Content-Type", "")).lower()
        if "html" in content_type:
            raise FeedImportError("notino_feed_returned_html_not_xml")
        chunks = []
        size = 0
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            size += len(chunk)
            if size > MAX_FEED_BYTES:
                raise FeedImportError("notino_feed_too_large")
            chunks.append(chunk)
        payload = b"".join(chunks)
        if not payload:
            raise FeedImportError("notino_feed_empty")
        return payload
    except FeedImportError:
        raise
    except requests.Timeout:
        raise FeedImportError("notino_feed_timeout") from None
    except requests.RequestException:
        raise FeedImportError("notino_feed_network_error") from None
    finally:
        if response is not None:
            response.close()


def _stable_variant_key(offer: NotinoOffer) -> str:
    identity = offer.gtin or offer.sku or offer.external_id
    identity = re.sub(r"[^A-Za-z0-9._:-]+", "_", identity)[:100]
    return f"{offer.size_ml:g}ml:{identity}"


def _slug(url: str) -> str:
    path = urllib.parse.unquote(urllib.parse.urlparse(url).path)
    return re.sub(r"[-_/]+", " ", path).strip().lower()


def _persist_offers(offers: list[NotinoOffer]) -> int:
    from catalog_engine import db

    conn = db()
    now = time.time()
    grouped: dict[str, list[NotinoOffer]] = {}
    for offer in offers:
        grouped.setdefault(offer.url, []).append(offer)
    try:
        with conn:
            for url, variants in grouped.items():
                # The parent record exists only to make the product URL searchable.
                # Do not expose a parent-level price or parent-level size: every
                # commercial size/edition price is stored separately below.
                titles = list(dict.fromkeys(item.title for item in variants))
                brands = list(dict.fromkeys(item.brand for item in variants))
                representative = variants[0]
                searchable_name = " | ".join(titles)[:1500]
                searchable_brand = " | ".join(brands)[:500]
                conn.execute(
                    """INSERT INTO store_urls(store,url,slug,lastmod,discovered_at,active)
                       VALUES(?,?,?,?,?,1)
                       ON CONFLICT(store,url) DO UPDATE SET
                         slug=excluded.slug,discovered_at=excluded.discovered_at,active=1""",
                    (STORE_KEY, url, _slug(url), None, now),
                )
                conn.execute(
                    """INSERT INTO store_products(
                           store,url,name,brand,image,sku,gtin,mpn,size_ml,concentration,
                           gender,price,currency,availability,fetched_at,fetch_status)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'OK')
                       ON CONFLICT(store,url) DO UPDATE SET
                         name=excluded.name,brand=excluded.brand,image=excluded.image,
                         sku=NULL,gtin=NULL,mpn=NULL,size_ml=NULL,concentration=NULL,gender=NULL,
                         price=NULL,currency=excluded.currency,availability='variant_catalog',
                         fetched_at=excluded.fetched_at,fetch_status='OK'""",
                    (
                        STORE_KEY, url, searchable_name, searchable_brand,
                        representative.image, None, None, None, None, None,
                        None, None, representative.currency, 'variant_catalog', now,
                    ),
                )
                for offer in variants:
                    conn.execute(
                        """INSERT INTO store_product_variants(
                               store,url,variant_key,name,brand,image,sku,gtin,mpn,size_ml,
                               concentration,gender,price,currency,availability,fetched_at,variant_url)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                           ON CONFLICT(store,url,variant_key) DO UPDATE SET
                             name=excluded.name,brand=excluded.brand,image=excluded.image,
                             sku=excluded.sku,gtin=excluded.gtin,mpn=excluded.mpn,
                             size_ml=excluded.size_ml,concentration=excluded.concentration,
                             price=CASE WHEN excluded.availability='out_of_stock' THEN NULL ELSE excluded.price END,
                             currency=excluded.currency,availability=excluded.availability,
                             fetched_at=excluded.fetched_at,variant_url=excluded.variant_url""",
                        (
                            STORE_KEY, url, _stable_variant_key(offer), offer.title,
                            offer.brand, offer.image, offer.sku, offer.gtin, offer.mpn,
                            offer.size_ml, offer.concentration, None,
                            offer.price, offer.currency, offer.availability, now, url,
                        ),
                    )
                conn.execute(
                    """INSERT INTO hydration_queue(
                           store,url,state,priority,attempts,available_at,first_seen_at)
                       VALUES(?,?,'DONE',0,0,?,?)
                       ON CONFLICT(store,url) DO UPDATE SET
                         state='DONE',priority=0,attempts=0,available_at=excluded.available_at,
                         leased_until=NULL,lease_token=NULL,last_error=NULL""",
                    (STORE_KEY, url, now, now),
                )
    finally:
        conn.close()
    return len(offers)


def import_feed_bytes(data: bytes) -> dict:
    """Parse completely before opening the DB so malformed feeds cannot affect offers."""
    offers = parse_feed(data)
    count = _persist_offers(offers)
    LOGGER.info("Notino authorized feed import completed: offers=%d", count)
    return {
        "ok": True,
        "store": STORE_KEY,
        "imported_offers": count,
        "feed_source": "cj_viv_authorized_xml",
    }


def import_configured_feed() -> dict:
    """Fetch/import from env config. Diagnostics deliberately omit URL and credentials."""
    payload = _fetch_feed()
    return import_feed_bytes(payload)


def search_feed(query: str, max_age_seconds: int = 48 * 60 * 60) -> dict:
    """Read fresh feed-backed Notino variants for normal search without site scraping."""
    query = re.sub(r"\s+", " ", str(query or "")).strip()
    if not query:
        return {"status": "success", "verified": True, "results": [], "error": None,
                "details": {"source": "cj_viv_authorized_xml", "empty_query": True}}
    try:
        from catalog_engine import db
        conn = db()
        try:
            cutoff = time.time() - max_age_seconds
            rows = conn.execute(
                """SELECT v.*, u.active
                     FROM store_product_variants v
                     JOIN store_urls u ON u.store=v.store AND u.url=v.url
                    WHERE v.store=? AND u.active=1
                      AND v.fetched_at>=? AND v.price>0
                      AND upper(COALESCE(v.currency,''))='EUR'
                    ORDER BY v.fetched_at DESC""",
                (STORE_KEY, cutoff),
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        return {"status": "unavailable", "verified": False, "results": [],
                "error": "notino_feed_catalog_read_error",
                "details": {"source": "cj_viv_authorized_xml"}}

    import unicodedata

    def norm(text):
        plain = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii")
        return re.sub(r"[^a-z0-9]+", " ", plain.lower()).strip()

    wanted = [token for token in norm(query).split() if len(token) > 1]
    requested_size = _size_ml(query)
    results = []
    seen = set()
    for row in rows:
        name = str(row["name"] or "").strip()
        brand = str(row["brand"] or "").strip()
        size = row["size_ml"]
        haystack = set(norm(f"{brand} {name} {size} ml").split())
        if not wanted or not all(token in haystack for token in wanted):
            continue
        if requested_size is not None and size is not None and abs(float(size) - requested_size) > 0.01:
            continue
        if str(row["availability"] or "").lower() not in {"in_stock", "preorder"}:
            continue
        key = (row["url"], float(size or 0), float(row["price"]))
        if key in seen:
            continue
        seen.add(key)
        price = float(row["price"])
        results.append({
            "shop": STORE_LABEL,
            "store": STORE_KEY,
            "brand": brand,
            "name": name,
            "price": f"{price:.2f} €",
            "price_num": price,
            "currency": "EUR",
            "available": True,
            "availability": row["availability"],
            "image": row["image"],
            "size_ml": size,
            "concentration": row["concentration"],
            "url": row["variant_url"] or row["url"],
            "gtin": row["gtin"],
            "sku": row["sku"],
            "fetched_at": row["fetched_at"],
        })
    results.sort(key=lambda item: (item["price_num"], item["size_ml"] or 0, item["url"]))
    return {
        "status": "success",
        "verified": True,
        "results": results,
        "error": None,
        "details": {
            "source": "cj_viv_authorized_xml",
            "freshness_seconds": max_age_seconds,
            "catalog_candidates": len(rows),
            "matched_offers": len(results),
        },
    }
