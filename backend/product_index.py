"""
ScentHunter - Product Index
STEP 2: local product/offers index.

Generic, store-agnostic layer between scraper output and the future
fast local search layer.

Responsibilities:
- keep canonical products separate from store offers;
- normalize product identity and searchable text;
- preserve GTIN / MPN / store identifiers;
- store price and availability per store/variant;
- build a SQLite FTS5 index for fast lookup;
- upsert data without creating product/store-specific exceptions.

This module does NOT perform web discovery and does NOT contain
product-specific seeds or rules.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


DEFAULT_DB_PATH = Path(__file__).resolve().parent / "scenthunter_index.db"


# ---------------------------------------------------------------------------
# Generic normalization
# ---------------------------------------------------------------------------

def normalize(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def compact_normalize(value: Any) -> str:
    return normalize(value).replace(" ", "")


def catalog_variant_key(value: str) -> str:
    text = str(value or "").lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(
        char for char in text
        if not unicodedata.combining(char)
    )

    text = text.replace("’", "'")
    text = re.sub(r"[^a-z0-9']+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def stable_id(*parts: Any, prefix: str = "SH") -> str:
    key = "::".join(normalize(part) for part in parts)
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def nested_value(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("value")
    return value


def first_value(item: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = item.get(key)
        value = nested_value(value)
        if value not in (None, ""):
            return value
    return None


def nested_block(item: Dict[str, Any], name: str) -> Dict[str, Any]:
    value = item.get(name)
    return value if isinstance(value, dict) else {}


def block_value(item: Dict[str, Any], block: str, *keys: str) -> Any:
    data = nested_block(item, block)
    return first_value(data, *keys)


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def parse_size_ml(*values: Any) -> Optional[float]:
    text = " ".join(clean_text(v) for v in values if v not in (None, ""))
    match = re.search(
        r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl|l)\b",
        text,
        re.I,
    )
    if not match:
        return None

    number = float(match.group(1).replace(",", "."))
    unit = match.group(2).lower()

    if unit == "cl":
        number *= 10
    elif unit == "l":
        number *= 1000

    return int(number) if number.is_integer() else number


def parse_price(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None

    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        return round(float(value), 2)

    text = clean_text(value).replace("€", " ")
    matches = re.findall(r"\d+(?:[.,]\d{1,2})?", text)
    if not matches:
        return None

    # Store scraper output normally contains one price. If a string contains
    # several numbers, the first decimal-looking value is the safest generic
    # interpretation; callers can supply a numeric offer.price directly.
    raw = matches[0]
    try:
        return round(float(raw.replace(",", ".")), 2)
    except ValueError:
        return None


def parse_concentration(*values: Any) -> Optional[str]:
    text = normalize(" ".join(clean_text(v) for v in values))
    rules = (
        ("Extrait de Parfum", r"\bextrait(?: de)? parfum\b|\bextrait\b"),
        ("Eau de Parfum", r"\beau de parfum\b|\bedp\b"),
        ("Eau de Toilette", r"\beau de toilette\b|\bedt\b"),
        ("Eau de Cologne", r"\beau de cologne\b|\bedc\b"),
        ("Parfum", r"\bparfum\b"),
    )
    for label, pattern in rules:
        if re.search(pattern, text, re.I):
            return label
    return None


def product_name(item: Dict[str, Any]) -> str:
    value = first_value(item, "canonical_name", "name", "title", "product_name")
    if value:
        return clean_text(value)

    source = nested_block(item, "source")
    return clean_text(
        first_value(source, "source_name", "name", "title") or ""
    )


def product_brand(item: Dict[str, Any]) -> str:
    value = first_value(
        item,
        "canonical_brand",
        "brand",
        "manufacturer",
        "maker",
    )
    if value:
        return clean_text(value)

    source = nested_block(item, "source")
    return clean_text(
        first_value(
            source,
            "source_brand",
            "brand",
            "manufacturer",
        ) or ""
    )


def generic_product_identity(item: Dict[str, Any]) -> Tuple[str, str, str, str]:
    return (
        "generic",
        clean_text(product_brand(item)),
        clean_text(product_name(item)),
        clean_text(offer_concentration(item)),
    )


def identity_for_product(item: Dict[str, Any]) -> Tuple[str, ...]:
    family_id = clean_text(first_value(item, "family_id"))
    canonical_name = clean_text(
        first_value(
            item,
            "canonical_name",
            "catalog_variant",
        )
        or ""
    )

    # Catalog products are identified by the catalog family and the
    # canonical variant name. family_name is metadata and must never
    # collapse distinct variants into the same identity.
    if family_id and canonical_name:
        return (
            "catalog",
            clean_text(family_id),
            catalog_variant_key(canonical_name),
        )

    return generic_product_identity(item)


def catalog_identity(item: Dict[str, Any]) -> str:
    identity = identity_for_product(item)
    if identity[0] == "catalog":
        return stable_id(*identity, prefix="CATALOG")

    value = first_value(
        item,
        "catalog_id",
        "product_identity",
        "master_id",
        "item_group_id",
    )
    if value:
        return clean_text(value)

    return ""


def identifier_value(item: Dict[str, Any], *keys: str) -> str:
    value = first_value(item, *keys)
    if value:
        return clean_text(value)

    identity = nested_block(item, "identity")
    value = first_value(identity, *keys)
    return clean_text(value or "")


def source_url(item: Dict[str, Any]) -> str:
    source = nested_block(item, "source")
    return clean_text(
        first_value(item, "url", "source_url")
        or first_value(source, "url", "source_page")
        or ""
    )


def source_image(item: Dict[str, Any]) -> str:
    source = nested_block(item, "source")
    return clean_text(
        first_value(item, "image", "image_url", "thumbnail")
        or first_value(source, "image")
        or ""
    )


def store_name(item: Dict[str, Any]) -> str:
    source = nested_block(item, "source")
    return clean_text(
        first_value(item, "store", "shop", "merchant")
        or first_value(source, "store", "source_name")
        or ""
    )


def offer_size(item: Dict[str, Any]) -> Optional[float]:
    explicit = first_value(
        item,
        "size_ml",
        "volume_ml",
        "format_ml",
    )
    if explicit not in (None, ""):
        try:
            return float(str(explicit).replace(",", "."))
        except (TypeError, ValueError):
            pass

    attributes = nested_block(item, "attributes")
    explicit = first_value(attributes, "size_ml", "volume_ml", "format_ml")
    if explicit not in (None, ""):
        try:
            return float(str(explicit).replace(",", "."))
        except (TypeError, ValueError):
            pass

    return parse_size_ml(
        product_name(item),
        first_value(item, "size", "format", "volume"),
        first_value(attributes, "size", "format", "volume"),
    )


def offer_concentration(item: Dict[str, Any]) -> Optional[str]:
    explicit = first_value(item, "concentration")
    if explicit:
        return clean_text(explicit)

    attributes = nested_block(item, "attributes")
    explicit = first_value(attributes, "concentration")
    if explicit:
        return clean_text(explicit)

    return parse_concentration(product_name(item))


def offer_price(item: Dict[str, Any]) -> Optional[float]:
    offer = nested_block(item, "offer")
    value = first_value(item, "price")
    if value in (None, ""):
        value = first_value(offer, "price")
    return parse_price(value)


def offer_availability(item: Dict[str, Any]) -> str:
    offer = nested_block(item, "offer")
    value = first_value(item, "availability", "available")
    if value in (None, ""):
        value = first_value(offer, "availability")

    if isinstance(value, bool):
        return "in_stock" if value else "out_of_stock"

    return normalize(value) or "unknown"


def searchable_text(
    brand: str,
    name: str,
    aliases: Sequence[str],
    concentration: Optional[str],
    size_ml: Optional[float],
) -> str:
    parts = [brand, name, *aliases, concentration or ""]
    if size_ml is not None:
        parts.append(f"{size_ml:g} ml")
    return normalize(" ".join(parts))


# ---------------------------------------------------------------------------
# Canonical catalog loading
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CanonicalProduct:
    product_id: str
    brand_id: str
    brand_name: str
    family_id: str
    family_name: str
    canonical_name: str
    concentration: Optional[str]
    gender: Optional[str]
    aliases: Tuple[str, ...]


def load_canonical_catalog(path: Path | str) -> List[CanonicalProduct]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))

    products = data.get("products", [])
    output: List[CanonicalProduct] = []

    for item in products:
        if not isinstance(item, dict):
            continue

        product_id = clean_text(item.get("product_id"))
        brand_id = clean_text(item.get("brand_id"))
        brand_name = clean_text(item.get("brand_name"))
        family_id = clean_text(item.get("family_id"))
        family_name = clean_text(item.get("family_name"))
        canonical_name = clean_text(
            item.get("canonical_name")
            or item.get("catalog_variant")
            or item.get("name")
            or family_name
        )

        if not product_id or not canonical_name:
            continue

        aliases = tuple(
            clean_text(value)
            for value in (item.get("aliases") or [])
            if clean_text(value)
        )

        output.append(
            CanonicalProduct(
                product_id=product_id,
                brand_id=brand_id,
                brand_name=brand_name,
                family_id=family_id,
                family_name=family_name,
                canonical_name=canonical_name,
                concentration=clean_text(item.get("concentration")) or None,
                gender=clean_text(item.get("gender")) or None,
                aliases=aliases,
            )
        )

    return output


# ---------------------------------------------------------------------------
# SQLite index
# ---------------------------------------------------------------------------

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS products (
    product_id TEXT PRIMARY KEY,
    brand_id TEXT,
    brand_name TEXT NOT NULL,
    family_id TEXT,
    family_name TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    concentration TEXT,
    gender TEXT,
    aliases_json TEXT NOT NULL DEFAULT '[]',
    searchable_text TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS offers (
    offer_id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL,
    store TEXT NOT NULL,
    store_product_id TEXT,
    store_variant_id TEXT,
    gtin TEXT,
    mpn TEXT,
    sku TEXT,
    name TEXT NOT NULL,
    size_ml REAL,
    concentration TEXT,
    price REAL,
    currency TEXT NOT NULL DEFAULT 'EUR',
    availability TEXT NOT NULL DEFAULT 'unknown',
    url TEXT,
    image TEXT,
    raw_json TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(product_id) REFERENCES products(product_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_offers_identity
ON offers (
    store,
    product_id,
    COALESCE(store_variant_id, ''),
    COALESCE(size_ml, -1),
    COALESCE(url, '')
);

CREATE INDEX IF NOT EXISTS idx_offers_product
ON offers(product_id);

CREATE INDEX IF NOT EXISTS idx_offers_store
ON offers(store);

CREATE INDEX IF NOT EXISTS idx_offers_gtin
ON offers(gtin);

CREATE INDEX IF NOT EXISTS idx_offers_price
ON offers(price);

CREATE VIRTUAL TABLE IF NOT EXISTS products_fts USING fts5(
    product_id UNINDEXED,
    brand_name,
    family_name,
    canonical_name,
    aliases,
    concentration,
    tokenize='unicode61 remove_diacritics 2'
);
"""


class ProductIndex:
    """
    Local product/offer index.

    The class is intentionally independent from individual stores.
    Scrapers only provide dictionaries; this layer normalizes and stores them.
    """

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript(SCHEMA)
        self._migrate_product_columns()
        self._ensure_fts()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "ProductIndex":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _migrate_product_columns(self) -> None:
        """Add catalog identity columns to indexes created by older versions."""
        columns = {
            row[1]
            for row in self.connection.execute(
                "PRAGMA table_info(products)"
            ).fetchall()
        }

        if "family_id" not in columns:
            self.connection.execute(
                "ALTER TABLE products ADD COLUMN family_id TEXT"
            )

        if "canonical_name" not in columns:
            self.connection.execute(
                "ALTER TABLE products ADD COLUMN canonical_name TEXT"
            )
            self.connection.execute(
                "UPDATE products SET canonical_name = family_name "
                "WHERE canonical_name IS NULL OR canonical_name = ''"
            )

        self.connection.commit()

    def _ensure_fts(self) -> None:
        # FTS is maintained explicitly by the upsert path. Recreate legacy
        # external-content indexes when encountered so old schemas cannot
        # collapse or misread family/canonical fields.
        columns = [
            row[1]
            for row in self.connection.execute(
                "PRAGMA table_info(products_fts)"
            ).fetchall()
        ]

        required = {
            "product_id",
            "brand_name",
            "family_name",
            "canonical_name",
            "aliases",
            "concentration",
        }

        if not required.issubset(columns):
            self.connection.execute("DROP TABLE IF EXISTS products_fts")
            self.connection.execute(
                """
                CREATE VIRTUAL TABLE products_fts USING fts5(
                    product_id UNINDEXED,
                    brand_name,
                    family_name,
                    canonical_name,
                    aliases,
                    concentration,
                    tokenize='unicode61 remove_diacritics 2'
                )
                """
            )

        count = self.connection.execute(
            "SELECT COUNT(*) FROM products_fts"
        ).fetchone()[0]

        if count == 0:
            rows = self.connection.execute(
                """
                SELECT
                    product_id,
                    brand_name,
                    family_name,
                    canonical_name,
                    aliases_json,
                    concentration
                FROM products
                """
            ).fetchall()

            for row in rows:
                aliases = json.loads(row[4] or "[]")
                self.connection.execute(
                    """
                    INSERT INTO products_fts (
                        product_id,
                        brand_name,
                        family_name,
                        canonical_name,
                        aliases,
                        concentration
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row[0],
                        row[1],
                        row[2],
                        row[3],
                        " ".join(aliases),
                        row[5] or "",
                    ),
                )

            self.connection.commit()

    def _upsert_product(
        self,
        product_id: str,
        brand_id: str,
        brand_name: str,
        family_id: str,
        family_name: str,
        canonical_name: str,
        concentration: Optional[str],
        gender: Optional[str],
        aliases: Sequence[str],
    ) -> None:
        now = datetime_utc()

        alias_json = json.dumps(
            list(dict.fromkeys(aliases)),
            ensure_ascii=False,
        )

        text = searchable_text(
            brand_name,
            canonical_name,
            aliases,
            concentration,
            None,
        )

        self.connection.execute(
            """
            INSERT INTO products (
                product_id,
                brand_id,
                brand_name,
                family_id,
                family_name,
                canonical_name,
                concentration,
                gender,
                aliases_json,
                searchable_text,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(product_id) DO UPDATE SET
                brand_id=excluded.brand_id,
                brand_name=excluded.brand_name,
                family_id=excluded.family_id,
                family_name=excluded.family_name,
                canonical_name=excluded.canonical_name,
                concentration=excluded.concentration,
                gender=excluded.gender,
                aliases_json=excluded.aliases_json,
                searchable_text=excluded.searchable_text,
                updated_at=excluded.updated_at
            """,
            (
                product_id,
                brand_id,
                brand_name,
                family_id,
                family_name,
                canonical_name,
                concentration,
                gender,
                alias_json,
                text,
                now,
            ),
        )

        self.connection.execute(
            "DELETE FROM products_fts WHERE product_id = ?",
            (product_id,),
        )

        self.connection.execute(
            """
            INSERT INTO products_fts (
                product_id,
                brand_name,
                family_name,
                canonical_name,
                aliases,
                concentration
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                product_id,
                brand_name,
                family_name,
                canonical_name,
                " ".join(aliases),
                concentration or "",
            ),
        )

    def upsert_canonical_catalog(
        self,
        catalog: Iterable[CanonicalProduct | Dict[str, Any]],
    ) -> int:
        count = 0

        for item in catalog:
            if isinstance(item, CanonicalProduct):
                product = item
            else:
                product = CanonicalProduct(
                    product_id=clean_text(
                        item.get("product_id") or item.get("id")
                    ),
                    brand_id=clean_text(item.get("brand_id")),
                    brand_name=clean_text(item.get("brand_name") or item.get("brand")),
                    family_id=clean_text(item.get("family_id")),
                    family_name=clean_text(item.get("family_name")),
                    canonical_name=clean_text(
                        item.get("canonical_name")
                        or item.get("catalog_variant")
                        or item.get("name")
                        or item.get("family_name")
                    ),
                    concentration=clean_text(item.get("concentration")) or None,
                    gender=clean_text(item.get("gender")) or None,
                    aliases=tuple(
                        clean_text(x)
                        for x in (item.get("aliases") or [])
                        if clean_text(x)
                    ),
                )

            if not product.product_id or not product.canonical_name:
                continue

            self._upsert_product(
                product.product_id,
                product.brand_id,
                product.brand_name,
                product.family_id,
                product.family_name or product.canonical_name,
                product.canonical_name,
                product.concentration,
                product.gender,
                product.aliases,
            )
            count += 1

        self.connection.commit()
        return count

    def _resolve_product_id(self, item: Dict[str, Any]) -> str:
        explicit = catalog_identity(item)
        if explicit:
            return explicit

        # Generic deterministic fallback. It is intentionally based only on
        # normalized brand + product name and never on a specific product.
        identity = identity_for_product(item)
        return stable_id(*identity, prefix="SH-AUTO")

    def _ensure_product_for_offer(self, item: Dict[str, Any]) -> str:
        product_id = self._resolve_product_id(item)

        existing = self.connection.execute(
            "SELECT product_id FROM products WHERE product_id = ?",
            (product_id,),
        ).fetchone()

        if existing:
            return product_id

        brand = product_brand(item)
        name = product_name(item)
        concentration = offer_concentration(item)
        aliases = tuple(
            value
            for value in (
                clean_text(first_value(item, "canonical_name")),
                clean_text(first_value(item, "name")),
                clean_text(
                    block_value(item, "source", "source_name")
                ),
            )
            if value and normalize(value) != normalize(name)
        )

        family_id = clean_text(first_value(item, "family_id"))
        family_name = clean_text(first_value(item, "family_name"))
        canonical_name = clean_text(
            first_value(item, "canonical_name", "catalog_variant")
        )

        # A catalog-family product must carry its canonical variant explicitly.
        # Never promote family_name (or the raw offer name) into canonical_name.
        if family_id and not canonical_name:
            return ""

        if not canonical_name:
            canonical_name = name

        self._upsert_product(
            product_id=product_id,
            brand_id="",
            brand_name=brand or "Unknown",
            family_id=family_id,
            family_name=family_name or canonical_name or "Unknown",
            canonical_name=canonical_name or "Unknown",
            concentration=concentration,
            gender=None,
            aliases=aliases,
        )

        return product_id

    def upsert_offer(self, item: Dict[str, Any]) -> Optional[str]:
        if not isinstance(item, dict):
            return None

        store = store_name(item)
        name = product_name(item)

        if not store or not name:
            return None

        product_id = self._ensure_product_for_offer(item)
        if not product_id:
            return None

        size_ml = offer_size(item)
        concentration = offer_concentration(item)
        price = offer_price(item)
        availability = offer_availability(item)

        store_product_id = identifier_value(
            item,
            "store_product_id",
            "product_id",
            "store_id",
        )
        store_variant_id = identifier_value(
            item,
            "store_variant_id",
            "variant_id",
        )
        gtin = identifier_value(
            item,
            "gtin",
            "ean",
            "ean13",
            "barcode",
            "upc",
        )
        mpn = identifier_value(
            item,
            "mpn",
            "manufacturer_part_number",
            "manufacturerNumber",
        )
        sku = identifier_value(item, "sku")
        url = source_url(item)
        image = source_image(item)
        currency = clean_text(
            first_value(
                item,
                "currency",
            )
            or block_value(item, "offer", "currency")
            or "EUR"
        )

        offer_id = stable_id(
            store,
            product_id,
            store_variant_id,
            size_ml,
            url,
            prefix="OFFER",
        )

        raw_json = json.dumps(
            item,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )

        now = datetime_utc()

        self.connection.execute(
            """
            INSERT INTO offers (
                offer_id,
                product_id,
                store,
                store_product_id,
                store_variant_id,
                gtin,
                mpn,
                sku,
                name,
                size_ml,
                concentration,
                price,
                currency,
                availability,
                url,
                image,
                raw_json,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(offer_id) DO UPDATE SET
                product_id=excluded.product_id,
                store=excluded.store,
                store_product_id=excluded.store_product_id,
                store_variant_id=excluded.store_variant_id,
                gtin=excluded.gtin,
                mpn=excluded.mpn,
                sku=excluded.sku,
                name=excluded.name,
                size_ml=excluded.size_ml,
                concentration=excluded.concentration,
                price=excluded.price,
                currency=excluded.currency,
                availability=excluded.availability,
                url=excluded.url,
                image=excluded.image,
                raw_json=excluded.raw_json,
                updated_at=excluded.updated_at
            """,
            (
                offer_id,
                product_id,
                store,
                store_product_id or None,
                store_variant_id or None,
                gtin or None,
                mpn or None,
                sku or None,
                name,
                size_ml,
                concentration,
                price,
                currency,
                availability,
                url or None,
                image or None,
                raw_json,
                now,
            ),
        )

        return offer_id

    def upsert_offers(self, offers: Iterable[Dict[str, Any]]) -> int:
        count = 0

        for item in offers:
            if self.upsert_offer(item):
                count += 1

        self.connection.commit()
        return count

    def search_products(
        self,
        query: str,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Fast local product search.

        FTS5 handles the first-pass lookup. Results are then returned in
        canonical form and can be joined to offers without contacting stores.
        """
        tokens = [
            token
            for token in normalize(query).split()
            if token
        ]

        if not tokens:
            return []

        # Prefix matching makes autocomplete useful while remaining generic.
        match_expression = " ".join(
            f"{token}*" for token in tokens
        )

        rows = self.connection.execute(
            """
            SELECT
                p.product_id,
                p.brand_id,
                p.brand_name,
                p.family_id,
                p.family_name,
                p.canonical_name,
                p.concentration,
                p.gender,
                p.aliases_json,
                bm25(products_fts) AS rank
            FROM products_fts
            JOIN products p
              ON p.product_id = products_fts.product_id
            WHERE products_fts MATCH ?
            ORDER BY rank, p.brand_name, p.canonical_name
            LIMIT ?
            """,
            (match_expression, max(1, int(limit))),
        ).fetchall()

        output = []

        for row in rows:
            item = dict(row)
            item["aliases"] = json.loads(item.pop("aliases_json") or "[]")
            item.pop("rank", None)
            output.append(item)

        return output

    def autocomplete(
        self,
        query: str,
        limit: int = 8,
    ) -> List[Dict[str, Any]]:
        return self.search_products(query, limit=limit)

    def get_offers(
        self,
        product_id: str,
        size_ml: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        sql = """
            SELECT
                offer_id,
                product_id,
                store,
                store_product_id,
                store_variant_id,
                gtin,
                mpn,
                sku,
                name,
                size_ml,
                concentration,
                price,
                currency,
                availability,
                url,
                image,
                updated_at
            FROM offers
            WHERE product_id = ?
        """
        params: List[Any] = [product_id]

        if size_ml is not None:
            sql += " AND size_ml = ?"
            params.append(size_ml)

        sql += """
            ORDER BY
                CASE WHEN price IS NULL THEN 1 ELSE 0 END,
                price ASC,
                store ASC
        """

        rows = self.connection.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def get_product_with_offers(
        self,
        product_id: str,
        size_ml: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        row = self.connection.execute(
            """
            SELECT
                product_id,
                brand_id,
                brand_name,
                family_id,
                family_name,
                canonical_name,
                concentration,
                gender,
                aliases_json,
                updated_at
            FROM products
            WHERE product_id = ?
            """,
            (product_id,),
        ).fetchone()

        if not row:
            return None

        product = dict(row)
        product["aliases"] = json.loads(
            product.pop("aliases_json") or "[]"
        )
        product["offers"] = self.get_offers(
            product_id,
            size_ml=size_ml,
        )
        return product

    def stats(self) -> Dict[str, int]:
        products = self.connection.execute(
            "SELECT COUNT(*) FROM products"
        ).fetchone()[0]

        offers = self.connection.execute(
            "SELECT COUNT(*) FROM offers"
        ).fetchone()[0]

        stores = self.connection.execute(
            "SELECT COUNT(DISTINCT store) FROM offers"
        ).fetchone()[0]

        return {
            "products": int(products),
            "offers": int(offers),
            "stores": int(stores),
        }

    def rebuild_fts(self) -> None:
        self.connection.execute(
            "INSERT INTO products_fts(products_fts) VALUES('rebuild')"
        )
        self.connection.commit()


def datetime_utc() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Convenience functions for indexer.py / tests
# ---------------------------------------------------------------------------

def build_index(
    catalog_path: Path | str,
    offers: Iterable[Dict[str, Any]],
    db_path: Path | str = DEFAULT_DB_PATH,
) -> Dict[str, int]:
    """
    Build/update the local index from the existing canonical catalog and
    already-collected scraper offers.

    This function does not call the internet.
    """
    with ProductIndex(db_path) as index:
        catalog = load_canonical_catalog(catalog_path)
        index.upsert_canonical_catalog(catalog)
        index.upsert_offers(offers)
        return index.stats()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="ScentHunter local product index"
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help="SQLite database path",
    )
    parser.add_argument(
        "--catalog",
        default=str(Path(__file__).resolve().parent / "product_catalog.json"),
        help="Canonical product catalog JSON",
    )
    parser.add_argument(
        "--query",
        default="",
        help="Run a local product search",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of search results",
    )

    args = parser.parse_args()

    with ProductIndex(args.db) as index:
        if Path(args.catalog).exists():
            catalog = load_canonical_catalog(args.catalog)
            index.upsert_canonical_catalog(catalog)

        if args.query:
            print(
                json.dumps(
                    index.search_products(args.query, args.limit),
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(
                json.dumps(
                    index.stats(),
                    ensure_ascii=False,
                    indent=2,
                )
            )
