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
MAX_IMPORT_SECONDS = 35 * 60
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


def _field_map(node: ET.Element) -> dict[str, list[str]]:
    """Read each product's direct children once instead of rescanning per field."""
    fields: dict[str, list[str]] = {}
    for child in node:
        name = _local(child.tag)
        value = (child.text or "").strip()
        if not value and name == "link":
            value = str(child.attrib.get("href") or "").strip()
        if value:
            fields.setdefault(name, []).append(value)
    return fields


def _values(node: ET.Element, names: Iterable[str],
            fields: dict[str, list[str]] | None = None) -> list[str]:
    source = fields if fields is not None else _field_map(node)
    wanted = {name.lower() for name in names}
    return [value for name, values in source.items() if name in wanted for value in values]


def _first(node: ET.Element, *names: str,
           fields: dict[str, list[str]] | None = None) -> str:
    values = _values(node, names, fields)
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
    try:
        parsed = urllib.parse.urlparse(str(raw or "").strip())
        host = (parsed.hostname or "").lower().rstrip(".")
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
    first_segment = (path.strip("/").split("/", 1)[0] or "").casefold()
    reserved_segments = {
        "search", "parfums", "marques", "login", "account", "cart",
        "checkout", "customer-service", "wishlist",
    }
    # Match complete reserved route segments only. Prefix matching wrongly
    # rejects legitimate brand slugs such as "parfums-de-marly" and "carthusia".
    if not path or path == "/" or first_segment in reserved_segments:
        return None
    return urllib.parse.urlunparse(("https", MARKET_HOST, path, "", "", ""))


def _cj_affiliate_link(raw: str) -> tuple[str, str] | None:
    """Validate an allowlisted CJ click URL and return its Notino target."""
    click_url = str(raw or "").strip()
    try:
        parsed = urllib.parse.urlparse(click_url)
        host = (parsed.hostname or "").lower().rstrip(".")
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
        or parsed.params
        or parsed.fragment
        or ";" in parsed.query
        or re.search(r"%(?![0-9a-fA-F]{2})|[\x00-\x20\x7f]", click_url)
    ):
        return None
    try:
        params = urllib.parse.parse_qsl(
            parsed.query, keep_blank_values=True, strict_parsing=True, errors="strict"
        )
    except (ValueError, UnicodeDecodeError):
        return None
    if any(not re.fullmatch(r"[a-zA-Z0-9_.~-]+", key) for key, _value in params):
        return None
    if len(params) != 1 or params[0][0].lower() != "url":
        return None
    target = _canonical_notino_product_url(params[0][1])
    if not target:
        return None
    return click_url, target


def validated_cj_offer_url(raw: str, product_url: str) -> str | None:
    """Accept a CJ click only when its destination is the stored product."""
    try:
        affiliate = _cj_affiliate_link(raw)
        product = _canonical_notino_product_url(product_url)
        if not affiliate or not product or affiliate[1] != product:
            return None
        destination = next(
            value for key, value in urllib.parse.parse_qsl(
                urllib.parse.urlparse(affiliate[0]).query, keep_blank_values=True
            ) if key.lower() == "url"
        )
        parsed = urllib.parse.urlparse(destination)
        path = urllib.parse.unquote(parsed.path, errors="strict")
        # Do not let server-side path normalization or redirect parameters
        # turn a matching catalog path into a different destination.
        if (
            parsed.params or parsed.fragment
            or re.search(r"%(?![0-9a-fA-F]{2})|%2f|%5c|%25", parsed.path, re.I)
            or re.search(r"[\x00-\x20\x7f\\;?#]", path)
            or re.search(r"[\x00-\x20\x7f]", destination)
            or "//" in path
            or any(segment in {".", ".."} for segment in path.split("/"))
        ):
            return None
        if parsed.query:
            query = urllib.parse.parse_qsl(
                parsed.query, keep_blank_values=True, strict_parsing=True, errors="strict"
            )
            if re.search(r"%(?![0-9a-fA-F]{2})|[\x00-\x20\x7f]", parsed.query) or any(
                key.lower() not in {
                    "utm_source", "utm_medium", "utm_campaign", "utm_term",
                    "utm_content", "utm_id",
                } for key, _value in query
            ):
                return None
        return affiliate[0]
    except (ValueError, UnicodeDecodeError):
        return None


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


def _parse_item(item: ET.Element, fields: dict[str, list[str]] | None = None) -> NotinoOffer | None:
    fields = fields if fields is not None else _field_map(item)
    title = _first(item, "title", "name", "productname", fields=fields)
    brand = _first(item, "brand", "manufacturer", "vendor", fields=fields)
    external_id = _first(item, "id", "offerid", "productid", fields=fields)
    sku = _first(item, "sku", "g:id", fields=fields)
    gtin = _first(item, "gtin", "gtin13", "gtin12", "gtin14", "ean", "barcode", fields=fields)
    mpn = _first(item, "mpn", "manufacturer_part_number", fields=fields)
    raw_price = _first(item, "price", "saleprice", "currentprice", fields=fields)
    price, currency = _money(raw_price)
    currency = currency or _first(item, "currency", "pricecurrency", fields=fields).upper()
    raw_availability = _first(item, "availability", "stock", "availabilitystatus", fields=fields).lower().strip()
    if raw_availability in {"in stock", "instock", "in_stock", "available", "limited availability", "limitedavailability"}:
        availability = "in_stock"
    elif raw_availability in {"out of stock", "outofstock", "out_of_stock", "sold out", "unavailable"}:
        availability = "out_of_stock"
    elif raw_availability in {"preorder", "pre-order"}:
        availability = "preorder"
    else:
        availability = "unknown"

    raw_link = _first(item, "link", "url", "producturl", fields=fields)
    raw_size = _first(item, "size", "volume", "capacity", "product_size", "g:size", fields=fields)
    size_ml = _size_ml(raw_size, title)  # explicit field is preferred
    image = _first(item, "image_link", "image", "imageurl", "g:image_link", fields=fields)

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
        fields = _field_map(node)
        offer = _parse_item(node, fields)
        if offer is not None:
            valid_items += 1
            valid_links += 1
            yield offer
            continue

        # Keep diagnostics aggregate-only: never include feed values, URLs,
        # credentials, or product-level data in production error messages.
        title = _first(node, "title", "name", "productname", fields=fields)
        brand = _first(node, "brand", "manufacturer", "vendor", fields=fields)
        raw_price = _first(node, "price", "saleprice", "currentprice", fields=fields)
        price, currency = _money(raw_price)
        currency = currency or _first(node, "currency", "pricecurrency", fields=fields).upper()
        raw_link = _first(node, "link", "url", "producturl", fields=fields)
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
        if _first(node, "availability", "stock", "availabilitystatus", fields=fields).lower().strip() not in {
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
    """Publish a staged feed with set-based SQLite statements.

    The previous implementation issued several SQL statements for every
    variant while holding the production writer lock. At feed scale this
    exceeded the import deadline and blocked other catalog writers. The
    staging database now does the grouping and SQLite performs publication
    with a handful of bulk INSERT/UPDATE statements in one atomic transaction.
    """
    from catalog_engine import DB_PATH
    from catalog_writer_lock import connect

    profile_enabled = os.environ.get("NOTINO_PERSIST_PROFILE", "").strip() == "1"
    profile_started_wall = time.monotonic()
    profile_started_cpu = time.process_time()
    phase_wall = {}
    phase_cpu = {}
    statement_counts = {"store_urls": 0, "legacy_variant_updates": 0,
                        "store_product_variants": 0, "store_products": 0,
                        "hydration_queue": 0, "sync_state": 0, "other": 0}

    def timed_execute(table, sql, parameters=()):
        wall, cpu = time.monotonic(), time.process_time()
        try:
            return conn.execute(sql, parameters)
        finally:
            if profile_enabled:
                phase_wall[table] = phase_wall.get(table, 0.0) + time.monotonic() - wall
                phase_cpu[table] = phase_cpu.get(table, 0.0) + time.process_time() - cpu
                statement_counts[table] += 1

    connect_wall, connect_cpu = time.monotonic(), time.process_time()
    # Publishing the full CJ feed competes with the always-on hydration worker.
    # Allow a bounded wait for that worker to finish its current SQLite write;
    # the import deadline still bounds the complete operation.
    lock_wait_seconds = 15 * 60
    if deadline is not None:
        lock_wait_seconds = max(1.0, min(lock_wait_seconds, deadline - time.monotonic()))
    conn = connect(DB_PATH, timeout=lock_wait_seconds)
    connect_wall_elapsed = time.monotonic() - connect_wall
    connect_cpu_elapsed = time.process_time() - connect_cpu
    now = time.time()
    try:
        stage_path = stage.execute("PRAGMA database_list").fetchone()[2]
        conn.execute("ATTACH DATABASE ? AS notino_stage", (stage_path,))
        if deadline is not None:
            conn.set_progress_handler(lambda: int(time.monotonic() >= deadline), 10000)
        with conn:
            lock_wall, lock_cpu = time.monotonic(), time.process_time()
            conn.execute("BEGIN IMMEDIATE")
            lock_wall_elapsed = time.monotonic() - lock_wall
            lock_cpu_elapsed = time.process_time() - lock_cpu

            previous = timed_execute(
                "other",
                "SELECT discovered_count, finished_at FROM sync_state "
                "WHERE store=? AND status='FEED_IMPORTED'",
                (STORE_KEY,),
            ).fetchone()
            if previous and previous[1] and float(previous[1]) >= started_at:
                raise FeedImportError("notino_feed_newer_import_already_published")
            if previous and previous[0] and count * 10 < int(previous[0]) * 9:
                raise FeedImportError("notino_feed_suspicious_offer_count")

            if deadline is not None and time.monotonic() >= deadline:
                raise FeedImportError("notino_feed_import_timeout")

            # Migrate legacy variant identities in one indexed statement.
            # Do not overwrite a CJ identity that already exists for the URL.
            timed_execute(
                "legacy_variant_updates",
                """UPDATE store_product_variants AS current
                   SET variant_key=(
                       SELECT notino_stage.offers.variant_key FROM notino_stage.offers
                       WHERE notino_stage.offers.url=current.url
                         AND notino_stage.offers.legacy_variant_key=current.variant_key
                       LIMIT 1
                   )
                   WHERE current.store=?
                     AND EXISTS (
                         SELECT 1 FROM notino_stage.offers
                         WHERE notino_stage.offers.url=current.url
                           AND notino_stage.offers.legacy_variant_key=current.variant_key
                     )
                     AND NOT EXISTS (
                         SELECT 1 FROM store_product_variants AS existing
                         WHERE existing.store=current.store
                           AND existing.url=current.url
                           AND existing.variant_key=(
                               SELECT notino_stage.offers.variant_key FROM notino_stage.offers
                               WHERE notino_stage.offers.url=current.url
                                 AND notino_stage.offers.legacy_variant_key=current.variant_key
                               LIMIT 1
                           )
                     )""",
                (STORE_KEY,),
            )

            timed_execute(
                "store_urls",
                """INSERT INTO store_urls(store,url,slug,lastmod,discovered_at,active)
                   SELECT ?,url,MIN(slug),NULL,?,1 FROM notino_stage.offers
                   WHERE 1 GROUP BY url
                   ON CONFLICT(store,url) DO UPDATE SET
                     slug=excluded.slug,discovered_at=excluded.discovered_at,active=1""",
                (STORE_KEY, now),
            )

            timed_execute(
                "store_product_variants",
                """INSERT INTO store_product_variants(
                       store,url,variant_key,name,brand,image,sku,gtin,mpn,size_ml,
                       concentration,gender,price,currency,availability,fetched_at,variant_url)
                   SELECT ?,url,variant_key,title,brand,image,sku,gtin,mpn,size_ml,
                          concentration,NULL,price,currency,availability,?,COALESCE(affiliate_url,url)
                   FROM notino_stage.offers WHERE 1
                   ON CONFLICT(store,url,variant_key) DO UPDATE SET
                     name=excluded.name,brand=excluded.brand,image=excluded.image,
                     sku=excluded.sku,gtin=excluded.gtin,mpn=excluded.mpn,
                     size_ml=excluded.size_ml,concentration=excluded.concentration,
                     price=excluded.price,currency=excluded.currency,
                     availability=excluded.availability,fetched_at=excluded.fetched_at,
                     variant_url=excluded.variant_url""",
                (STORE_KEY, now),
            )

            timed_execute(
                "store_products",
                """INSERT INTO store_products(
                       store,url,name,brand,image,sku,gtin,mpn,size_ml,concentration,
                       gender,price,currency,availability,fetched_at,fetch_status)
                   SELECT ?,url,substr(group_concat(DISTINCT title),1,1500),
                          substr(group_concat(DISTINCT brand),1,500),MAX(image),
                          NULL,NULL,NULL,NULL,NULL,NULL,NULL,MAX(currency),
                          'variant_catalog',?,'OK'
                   FROM notino_stage.offers GROUP BY url
                   ON CONFLICT(store,url) DO UPDATE SET
                     name=excluded.name,brand=excluded.brand,image=excluded.image,
                     sku=NULL,gtin=NULL,mpn=NULL,size_ml=NULL,concentration=NULL,
                     gender=NULL,price=NULL,currency=excluded.currency,
                     availability='variant_catalog',fetched_at=excluded.fetched_at,
                     fetch_status='OK'""",
                (STORE_KEY, now),
            )

            timed_execute(
                "hydration_queue",
                """INSERT INTO hydration_queue(
                       store,url,state,priority,attempts,available_at,first_seen_at)
                   SELECT ?,url,'DONE',0,0,?,? FROM notino_stage.offers WHERE 1 GROUP BY url
                   ON CONFLICT(store,url) DO UPDATE SET
                     state='DONE',priority=0,attempts=0,available_at=excluded.available_at,
                     leased_until=NULL,lease_token=NULL,last_error=NULL""",
                (STORE_KEY, now, now),
            )

            timed_execute(
                "sync_state",
                """INSERT INTO sync_state(store,status,started_at,finished_at,discovered_count,fetched_count,error)
                   VALUES(?,'FEED_IMPORTED',?,?,?,?,?)
                   ON CONFLICT(store) DO UPDATE SET status=excluded.status,
                       started_at=excluded.started_at,finished_at=excluded.finished_at,
                       discovered_count=excluded.discovered_count,fetched_count=excluded.fetched_count,
                       error=excluded.error""",
                (STORE_KEY, started_at, time.time(), count, count, "source=cj_viv_authorized_xml"),
            )
            if deadline is not None and time.monotonic() >= deadline:
                raise FeedImportError("notino_feed_import_timeout")
            commit_wall, commit_cpu = time.monotonic(), time.process_time()
            conn.commit()
            if profile_enabled:
                phase_wall["commit"] = time.monotonic() - commit_wall
                phase_cpu["commit"] = time.process_time() - commit_cpu
    finally:
        conn.close()
        if profile_enabled:
            LOGGER.info(
                "Notino persistence profile: variants=%d connect_wall=%.3fs connect_cpu=%.3fs "
                "begin_immediate_wall=%.3fs begin_immediate_cpu=%.3fs phase_wall=%s phase_cpu=%s "
                "statement_counts=%s total_wall=%.3fs total_cpu=%.3fs",
                count, connect_wall_elapsed, connect_cpu_elapsed,
                locals().get("lock_wall_elapsed", 0.0), locals().get("lock_cpu_elapsed", 0.0),
                phase_wall, phase_cpu, statement_counts,
                time.monotonic() - profile_started_wall, time.process_time() - profile_started_cpu,
            )

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
                concentration TEXT, affiliate_url TEXT, legacy_variant_key TEXT, slug TEXT,
                PRIMARY KEY(url, variant_key)) WITHOUT ROWID""")
            with _xml_stream(source, deadline) as stream:
                for offer in _parsed_offers(stream, stats):
                    if deadline is not None and time.monotonic() >= deadline:
                        raise FeedImportError("notino_feed_import_timeout")
                    stage.execute(
                        """INSERT OR REPLACE INTO offers VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (offer.url, _stable_variant_key(offer), offer.external_id, offer.title,
                         offer.brand, offer.gtin, offer.sku, offer.mpn, offer.size_ml, offer.price,
                         offer.currency, offer.availability, offer.image, offer.concentration,
                         offer.affiliate_url, _legacy_variant_key({
                             "size_ml": offer.size_ml, "gtin": offer.gtin,
                             "sku": offer.sku, "external_id": offer.external_id,
                         }), _slug(offer.url)),
                    )
            stage.commit()
            # The legacy-key migration probes by (url, legacy_variant_key).
            # The table primary key is (url, variant_key), so add the missing
            # lookup index before publication to avoid repeated staging scans.
            stage.execute(
                "CREATE INDEX idx_notino_offers_legacy_url "
                "ON offers(url, legacy_variant_key) "
                "WHERE legacy_variant_key IS NOT NULL"
            )
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
        from catalog_engine import db, _notino_variant_url
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
        offer_url = _notino_variant_url(row["variant_url"], row["url"])
        if not offer_url:
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
            "url": offer_url,
            "product_url": row["url"],
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