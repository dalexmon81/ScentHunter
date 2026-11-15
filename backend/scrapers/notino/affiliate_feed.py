"""Authenticated CJ/VIV XML feed integration for Notino.fr.

The feed's actual credential URL and access details are provided by the affiliate
network. This module accepts the documented Google Shopping XML export shape
without assuming a fixed namespace prefix or a specific feed URL.
"""
from __future__ import annotations

import gzip
import io
import zipfile
import hashlib
import logging
import os
import re
import sqlite3
import tempfile
import time
import urllib.parse
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from itertools import groupby
from typing import Iterable

import requests

LOGGER = logging.getLogger("scenthunter.notino_feed")
STORE_KEY = "notino"
STORE_LABEL = "Notino"
MARKET_HOST = "www.notino.fr"
TIMEOUT = (5.0, 30.0)
MAX_FEED_BYTES = 256 * 1024 * 1024
MAX_DECOMPRESSED_BYTES = 512 * 1024 * 1024
MAX_IMPORT_SECONDS = 10 * 60
USER_AGENT = "ScentHunter/authorized-affiliate-feed (+price-comparison)"
# CJ HTTP/S subscription configured for the accepted NOTINO.fr product export.
DEFAULT_CJ_FEED_URL = (
    "https://datatransfer.cj.com/datatransfer/files/8115142/"
    "outgoing/productcatalog/324587/"
    "NOTINO_fr-NotinoFR_google_all-shopping.xml.zip"
)


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
    size_ml: float | None
    price: float
    currency: str
    availability: str
    url: str
    image: str | None
    concentration: str | None
    # Keep CJ attribution while catalog identity remains the canonical URL.
    affiliate_url: str | None = None


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
    value = value.quantize(Decimal("0.01"))
    return (value if value > 0 else None), currency


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


CJ_TRACKING_HOSTS = frozenset({
    "anrdoezrs.net", "www.anrdoezrs.net",
    "dpbolvw.net", "www.dpbolvw.net",
    "jdoqocy.com", "www.jdoqocy.com",
    "kqzyfj.com", "www.kqzyfj.com",
    "tkqlhce.com", "www.tkqlhce.com",
})
CJ_CLICK_PATH = re.compile(r"^/click-\d+-\d+/?$", re.I)


def _canonical_notino_product_url(raw: str) -> str | None:
    parsed = urllib.parse.urlparse(str(raw or "").strip())
    host = (parsed.hostname or "").lower().rstrip(".")
    try:
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or host not in {"notino.fr", "www.notino.fr"}
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
    ):
        return None
    path = re.sub(r"/{2,}", "/", parsed.path or "")
    if not path or path == "/" or path.lower().startswith((
        "/search", "/parfums", "/marques", "/login", "/account", "/cart",
        "/checkout", "/customer-service", "/wishlist",
    )):
        return None
    return urllib.parse.urlunparse(("https", MARKET_HOST, path, "", "", ""))


def _cj_affiliate_link(raw: str) -> tuple[str, str] | None:
    """Validate an allowlisted CJ click URL and return its Notino target."""
    click_url = str(raw or "").strip()
    parsed = urllib.parse.urlparse(click_url)
    host = (parsed.hostname or "").lower().rstrip(".")
    try:
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or host not in CJ_TRACKING_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or not CJ_CLICK_PATH.fullmatch(parsed.path or "")
    ):
        return None
    params = urllib.parse.parse_qs(parsed.query, keep_blank_values=False)
    destinations = [
        value
        for key, values in params.items()
        if key.lower() == "url"
        for value in values
    ]
    if len(destinations) != 1:
        return None
    target = _canonical_notino_product_url(destinations[0])
    if not target:
        return None
    return click_url, target


def _resolve_product_link(raw: str) -> tuple[str | None, str | None]:
    direct = _canonical_notino_product_url(raw)
    if direct:
        return direct, None
    affiliate = _cj_affiliate_link(raw)
    if affiliate:
        click_url, target = affiliate
        return target, click_url
    return None, None


def _product_url(raw: str) -> str | None:
    return _resolve_product_link(raw)[0]


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

    link, affiliate_url = _resolve_product_link(raw_link)
    if not title or not brand or price is None or currency != "EUR" or not link or availability == "unknown":
        return None
    if not external_id:
        external_id = gtin or sku or hashlib.sha256(
            f"{link}|{title}".encode("utf-8")
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
        affiliate_url=affiliate_url,
    )


class _SafeXmlReader:
    def __init__(self, stream, deadline=None):
        self.stream = stream
        self.deadline = deadline
        self.size = 0
        self.tail = b""

    def read(self, size=-1):
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise FeedImportError("notino_feed_import_timeout")
        chunk = self.stream.read(size)
        self.size += len(chunk)
        if self.size > MAX_DECOMPRESSED_BYTES:
            raise FeedImportError("notino_feed_decompressed_too_large")
        probe = self.tail + chunk
        if b"\x00" in chunk or re.search(br"<!DOCTYPE|<!ENTITY", probe, re.I):
            raise FeedImportError("notino_feed_unsafe_xml_declaration")
        self.tail = probe[-16:]
        return chunk


@contextmanager
def _xml_stream(source, deadline=None):
    source.seek(0, os.SEEK_END)
    size = source.tell()
    source.seek(0)
    if not size:
        raise FeedImportError("notino_feed_empty")
    if size > MAX_FEED_BYTES:
        raise FeedImportError("notino_feed_too_large")
    if zipfile.is_zipfile(source):
        try:
            with zipfile.ZipFile(source) as archive:
                members = [info for info in archive.infolist()
                           if not info.is_dir() and info.filename.casefold().endswith(".xml")]
                if len(members) != 1:
                    raise FeedImportError("notino_feed_zip_expected_one_xml")
                if members[0].file_size > MAX_DECOMPRESSED_BYTES:
                    raise FeedImportError("notino_feed_decompressed_too_large")
                with archive.open(members[0]) as stream:
                    yield _SafeXmlReader(stream, deadline)
        except (OSError, EOFError, zipfile.BadZipFile, RuntimeError) as exc:
            if isinstance(exc, FeedImportError):
                raise
            raise FeedImportError("notino_feed_invalid_zip") from None
    else:
        source.seek(0)
        magic = source.read(2)
        source.seek(0)
        if magic == b"\x1f\x8b":
            try:
                with gzip.GzipFile(fileobj=source) as stream:
                    yield _SafeXmlReader(stream, deadline)
            except (OSError, EOFError):
                raise FeedImportError("notino_feed_invalid_gzip") from None
        else:
            yield _SafeXmlReader(source, deadline)


def _feed_items(stream):
    root = None
    root_name = ""
    stack = []
    count = 0
    fallback_count = 0
    try:
        for event, node in ET.iterparse(stream, events=("start", "end")):
            if event == "start":
                if root is None:
                    root = node
                    root_name = _local(node.tag)
                    if root_name not in {"rss", "feed", "channel", "catalog", "products", "productfeed"}:
                        raise FeedImportError("notino_feed_unrecognized_root")
                stack.append(node)
                continue
            is_item = _local(node.tag) in {"item", "entry", "product"}
            fallback = (root_name in {"catalog", "products", "productfeed"}
                        and len(stack) == 2 and not is_item
                        and count == fallback_count and len(node))
            if is_item and fallback_count:
                raise FeedImportError("notino_feed_mixed_item_shapes")
            if is_item or fallback:
                count += 1
                fallback_count += int(bool(fallback))
                yield node
                if len(stack) > 1:
                    stack[-2].remove(node)
                node.clear()
            stack.pop()
    except ET.ParseError:
        raise FeedImportError("notino_feed_invalid_xml") from None
    if not count:
        raise FeedImportError("notino_feed_no_product_entries")


def _parsed_offers(stream, stats):
    candidate_count = 0
    valid_links = 0
    valid_items = 0
    rejected = {
        "missing_title": 0,
        "missing_brand": 0,
        "invalid_or_missing_price": 0,
        "currency_not_eur": 0,
        "invalid_or_missing_fr_product_url": 0,
        "invalid_or_missing_availability": 0,
    }
    for node in _feed_items(stream):
        candidate_count += 1
        offer = _parse_item(node)
        if offer is not None:
            valid_items += 1
            valid_links += 1
            yield offer
            continue

        # Keep diagnostics aggregate-only: never include feed values, URLs,
        # credentials, or product-level data in production error messages.
        title = _first(node, "title", "name", "productname")
        brand = _first(node, "brand", "manufacturer", "vendor")
        raw_price = _first(node, "price", "saleprice", "currentprice")
        price, currency = _money(raw_price)
        currency = currency or _first(node, "currency", "pricecurrency").upper()
        raw_link = _first(node, "link", "url", "producturl")
        if not raw_link:
            for child in list(node):
                if _local(child.tag) == "link" and child.attrib.get("href"):
                    raw_link = str(child.attrib["href"]).strip()
                    break
        if not title:
            rejected["missing_title"] += 1
        if not brand:
            rejected["missing_brand"] += 1
        if price is None:
            rejected["invalid_or_missing_price"] += 1
        if currency != "EUR":
            rejected["currency_not_eur"] += 1
        if _product_url(raw_link):
            valid_links += 1
        else:
            rejected["invalid_or_missing_fr_product_url"] += 1
        if _first(node, "availability", "stock", "availabilitystatus").lower().strip() not in {
            "in stock", "instock", "in_stock", "available", "limited availability",
            "limitedavailability", "out of stock", "outofstock", "out_of_stock",
            "sold out", "unavailable", "preorder", "pre-order",
        }:
            rejected["invalid_or_missing_availability"] += 1

    if not valid_items:
        detail = ";".join(f"{key}={value}" for key, value in rejected.items())
        raise FeedImportError(
            f"notino_feed_no_valid_priced_fr_offers:items={candidate_count};{detail}"
        )
    stats.update(products_read=candidate_count, valid_links=valid_links,
                 valid_items=valid_items, rejected_items=candidate_count - valid_items,
                 rejection_reasons=rejected)


def parse_feed(data: bytes, *, stats: dict | None = None) -> list[NotinoOffer]:
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise FeedImportError("notino_feed_empty")
    unique = {}
    counters = stats if stats is not None else {}
    with _xml_stream(io.BytesIO(data)) as stream:
        for offer in _parsed_offers(stream, counters):
            key = (offer.external_id, offer.url, offer.size_ml, offer.gtin or "", offer.sku or "")
            unique[key] = offer
    return list(unique.values())


def _download_feed(destination, deadline=None) -> int:
    feed_url = (
        os.environ.get("NOTINO_CJ_FEED_URL", "").strip()
        or DEFAULT_CJ_FEED_URL
    )
    # The review workflow already uses CJ_HTTP_*; accept the same names in
    # production so the deploy workflow can provision one credential pair.
    username = (
        os.environ.get("NOTINO_CJ_FEED_USERNAME", "").strip()
        or os.environ.get("CJ_HTTP_USERNAME", "").strip()
    )
    password = (
        os.environ.get("NOTINO_CJ_FEED_PASSWORD", "")
        or os.environ.get("CJ_HTTP_PASSWORD", "")
    )
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
            allow_redirects=True,
        )
        final_url = urllib.parse.urlparse(str(response.url or ""))
        if (
            final_url.scheme != "https"
            or not final_url.hostname
            or final_url.username is not None
            or final_url.password is not None
        ):
            raise FeedImportError("notino_feed_redirect_destination_rejected")
        if response.status_code in (401, 403):
            raise FeedImportError("notino_feed_auth_denied")
        if response.status_code >= 400:
            raise FeedImportError(f"notino_feed_http_{response.status_code}")
        content_type = str(response.headers.get("Content-Type", "")).lower()
        if "html" in content_type:
            raise FeedImportError("notino_feed_returned_html_not_xml")
        size = 0
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if deadline is not None and time.monotonic() >= deadline:
                raise FeedImportError("notino_feed_import_timeout")
            if not chunk:
                continue
            size += len(chunk)
            if size > MAX_FEED_BYTES:
                raise FeedImportError("notino_feed_too_large")
            destination.write(chunk)
        if not size:
            raise FeedImportError("notino_feed_empty")
        destination.flush()
        destination.seek(0)
        return size
    except FeedImportError:
        raise
    except requests.Timeout:
        raise FeedImportError("notino_feed_timeout") from None
    except requests.RequestException:
        raise FeedImportError("notino_feed_network_error") from None
    finally:
        if response is not None:
            response.close()


def _fetch_feed() -> bytes:
    output = io.BytesIO()
    _download_feed(output)
    return output.getvalue()


def _stable_variant_key(offer: NotinoOffer) -> str:
    return "cj:" + hashlib.sha256(offer.external_id.encode("utf-8")).hexdigest()


def _legacy_variant_key(offer) -> str | None:
    if offer["size_ml"] is None:
        return None
    identity = offer["gtin"] or offer["sku"] or offer["external_id"]
    identity = re.sub(r"[^A-Za-z0-9._:-]+", "_", identity)[:100]
    return f"{offer['size_ml']:g}ml:{identity}"


def _slug(url: str) -> str:
    path = urllib.parse.unquote(urllib.parse.urlparse(url).path)
    return re.sub(r"[-_/]+", " ", path).strip().lower()


def _persist_staged_offers(stage, count, started_at, deadline):
    from catalog_engine import DB_PATH
    from catalog_writer_lock import connect

    conn = connect(DB_PATH, timeout=45)
    if deadline is not None:
        conn.set_progress_handler(lambda: int(time.monotonic() >= deadline), 10000)
    now = time.time()
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            previous = conn.execute(
                "SELECT discovered_count, finished_at FROM sync_state WHERE store=? AND status='FEED_IMPORTED'",
                (STORE_KEY,),
            ).fetchone()
            if previous and previous[1] and float(previous[1]) >= started_at:
                raise FeedImportError("notino_feed_newer_import_already_published")
            if previous and previous[0] and count * 10 < int(previous[0]) * 9:
                raise FeedImportError("notino_feed_suspicious_offer_count")
            rows = stage.execute("SELECT * FROM offers ORDER BY url, variant_key")
            for url, variants in groupby(rows, key=lambda row: row["url"]):
                if deadline is not None and time.monotonic() >= deadline:
                    raise FeedImportError("notino_feed_import_timeout")
                conn.execute(
                    """INSERT INTO store_urls(store,url,slug,lastmod,discovered_at,active)
                       VALUES(?,?,?,?,?,1)
                       ON CONFLICT(store,url) DO UPDATE SET
                         slug=excluded.slug,discovered_at=excluded.discovered_at,active=1""",
                    (STORE_KEY, url, _slug(url), None, now),
                )
                names, brands = [], []
                name_length = brand_length = 0
                representative = None
                for offer in variants:
                    if representative is None:
                        representative = offer
                    if offer["title"] not in names and name_length < 1500:
                        names.append(offer["title"])
                        name_length += len(offer["title"]) + 3
                    if offer["brand"] not in brands and brand_length < 500:
                        brands.append(offer["brand"])
                        brand_length += len(offer["brand"]) + 3
                    legacy_key = _legacy_variant_key(offer)
                    if legacy_key:
                        conn.execute(
                            """UPDATE store_product_variants SET variant_key=?
                               WHERE store=? AND url=? AND variant_key=?
                                 AND NOT EXISTS (
                                     SELECT 1 FROM store_product_variants
                                     WHERE store=? AND url=? AND variant_key=?
                                 )""",
                            (offer["variant_key"], STORE_KEY, url, legacy_key,
                             STORE_KEY, url, offer["variant_key"]),
                        )
                    conn.execute(
                        """INSERT INTO store_product_variants(
                               store,url,variant_key,name,brand,image,sku,gtin,mpn,size_ml,
                               concentration,gender,price,currency,availability,fetched_at,variant_url)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                           ON CONFLICT(store,url,variant_key) DO UPDATE SET
                             name=excluded.name,brand=excluded.brand,image=excluded.image,
                             sku=excluded.sku,gtin=excluded.gtin,mpn=excluded.mpn,
                             size_ml=excluded.size_ml,concentration=excluded.concentration,
                             price=excluded.price,
                             currency=excluded.currency,availability=excluded.availability,
                             fetched_at=excluded.fetched_at,variant_url=excluded.variant_url""",
                        (
                            STORE_KEY, url, offer["variant_key"], offer["title"],
                            offer["brand"], offer["image"], offer["sku"], offer["gtin"], offer["mpn"],
                            offer["size_ml"], offer["concentration"], None,
                            offer["price"], offer["currency"], offer["availability"], now,
                            offer["affiliate_url"] or url,
                        ),
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
                        STORE_KEY, url, " | ".join(names)[:1500], " | ".join(brands)[:500],
                        representative["image"], None, None, None, None, None,
                        None, None, representative["currency"], 'variant_catalog', now,
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
            conn.execute(
                """INSERT INTO sync_state(store,status,started_at,finished_at,discovered_count,fetched_count,error)
                   VALUES(?,'FEED_IMPORTED',?,?,?,?,?)
                   ON CONFLICT(store) DO UPDATE SET status=excluded.status,
                       started_at=excluded.started_at,finished_at=excluded.finished_at,
                       discovered_count=excluded.discovered_count,fetched_count=excluded.fetched_count,
                       error=excluded.error""",
                (STORE_KEY, started_at, time.time(), count, count, "source=cj_viv_authorized_xml"),
            )
    finally:
        conn.close()


def _import_stream(source, started_at, deadline=None):
    stats = {}
    with tempfile.TemporaryDirectory(prefix="notino-feed-") as directory:
        stage = sqlite3.connect(os.path.join(directory, "offers.sqlite3"))
        stage.row_factory = sqlite3.Row
        try:
            stage.execute("PRAGMA journal_mode=OFF")
            stage.execute("PRAGMA synchronous=OFF")
            stage.execute("PRAGMA cache_size=-65536")
            stage.execute("""CREATE TABLE offers(
                url TEXT NOT NULL, variant_key TEXT NOT NULL, external_id TEXT,
                title TEXT, brand TEXT, gtin TEXT, sku TEXT, mpn TEXT, size_ml REAL,
                price REAL, currency TEXT, availability TEXT, image TEXT,
                concentration TEXT, affiliate_url TEXT, PRIMARY KEY(url, variant_key)) WITHOUT ROWID""")
            with _xml_stream(source, deadline) as stream:
                for offer in _parsed_offers(stream, stats):
                    if deadline is not None and time.monotonic() >= deadline:
                        raise FeedImportError("notino_feed_import_timeout")
                    stage.execute(
                        """INSERT OR REPLACE INTO offers VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (offer.url, _stable_variant_key(offer), offer.external_id, offer.title,
                         offer.brand, offer.gtin, offer.sku, offer.mpn, offer.size_ml, offer.price,
                         offer.currency, offer.availability, offer.image, offer.concentration,
                         offer.affiliate_url),
                    )
            stage.commit()
            if stage.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise FeedImportError("notino_feed_staging_integrity_error")
            count = stage.execute("SELECT COUNT(*) FROM offers").fetchone()[0]
            stats["duplicate_items"] = stats["valid_items"] - count
            _persist_staged_offers(stage, count, started_at, deadline)
        finally:
            stage.close()
    LOGGER.info("Notino authorized feed import completed: offers=%d", count)
    return {
        "ok": True,
        "store": STORE_KEY,
        "imported_offers": count,
        "feed_source": "cj_viv_authorized_xml",
        **stats,
    }


def import_feed_bytes(data: bytes) -> dict:
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise FeedImportError("notino_feed_empty")
    return _import_stream(io.BytesIO(data), time.time())


def import_configured_feed() -> dict:
    """Download and validate on temporary storage before atomic publication."""
    started_at = time.time()
    deadline = time.monotonic() + MAX_IMPORT_SECONDS
    with tempfile.TemporaryFile() as source:
        download_bytes = _download_feed(source, deadline)
        report = _import_stream(source, started_at, deadline)
    report["download_bytes"] = download_bytes
    return report


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
