from __future__ import annotations
import hashlib
import json
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from .models import SourceObservation


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS products (
  product_id TEXT PRIMARY KEY, brand TEXT NOT NULL, canonical_name TEXT NOT NULL,
  gtin TEXT, mpn TEXT, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS variants (
  variant_id TEXT PRIMARY KEY, product_id TEXT NOT NULL REFERENCES products(product_id),
  concentration TEXT, size_ml TEXT, pack_count INTEGER NOT NULL CHECK(pack_count >= 1),
  gender TEXT, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_variants_product ON variants(product_id);
CREATE TABLE IF NOT EXISTS offers (
  offer_id TEXT PRIMARY KEY, variant_id TEXT NOT NULL REFERENCES variants(variant_id),
  store TEXT NOT NULL, product_url TEXT NOT NULL, price_minor INTEGER NOT NULL CHECK(price_minor >= 0),
  currency TEXT NOT NULL CHECK(length(currency) = 3), availability TEXT NOT NULL, source_sku TEXT,
  first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, last_valid_at TEXT NOT NULL,
  is_current INTEGER NOT NULL DEFAULT 1 CHECK(is_current IN (0,1)),
  UNIQUE(store, product_url, variant_id)
);
CREATE INDEX IF NOT EXISTS idx_offers_variant_current ON offers(variant_id, is_current, price_minor);
CREATE INDEX IF NOT EXISTS idx_offers_store_seen ON offers(store, last_seen_at);
CREATE TABLE IF NOT EXISTS observations (
  observation_key TEXT PRIMARY KEY, offer_id TEXT NOT NULL REFERENCES offers(offer_id), store TEXT NOT NULL,
  source_url TEXT NOT NULL, observed_at TEXT NOT NULL, parser_version TEXT NOT NULL,
  trace_id TEXT NOT NULL, raw_title TEXT NOT NULL, raw_price TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS adapter_failures (
  id INTEGER PRIMARY KEY AUTOINCREMENT, store TEXT NOT NULL, source_url TEXT NOT NULL,
  kind TEXT NOT NULL, message TEXT NOT NULL, retryable INTEGER NOT NULL CHECK(retryable IN (0,1)),
  occurred_at TEXT NOT NULL, trace_id TEXT
);
"""


class SQLiteOfferRepository:
    """Isolated SQLite repository. Use a separate path from the legacy DB."""

    def __init__(self, path: str | Path, *, busy_timeout_ms: int = 5000):
        self.path = str(path)
        legacy_path = str(os.environ.get("SCENTHUNTER_LEGACY_DB") or os.environ.get("SCENTHUNTER_CATALOG_DB", "")).strip()
        if self.path != ":memory:" and legacy_path and Path(self.path).expanduser().resolve() == Path(legacy_path).expanduser().resolve():
            raise RuntimeError("next-engine repository must not use the legacy catalog database")
        self.busy_timeout_ms = int(busy_timeout_ms)
        self._memory_uri = None
        self._memory_anchor = None
        self._lock = threading.RLock()
        if self.busy_timeout_ms < 0:
            raise ValueError("busy_timeout_ms cannot be negative")
        if self.path == ":memory:":
            self._memory_uri = f"file:scenthunter_next_{uuid.uuid4().hex}?mode=memory&cache=shared"
            self._memory_anchor = sqlite3.connect(self._memory_uri, uri=True, timeout=self.busy_timeout_ms / 1000)
        else:
            Path(self.path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        target = self._memory_uri or self.path
        conn = sqlite3.connect(target, uri=bool(self._memory_uri), timeout=self.busy_timeout_ms / 1000)
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def _connection(self):
        """Own one connection and always close it, committing atomically."""
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        with self._connection() as conn:
            if not self._memory_uri:
                conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(SCHEMA)

    @staticmethod
    def _observation_key(obs: SourceObservation) -> str:
        # Timestamp resolution is only one second in some adapters. Include the
        # complete commercial observation so two different prices seen in the
        # same second cannot be mistaken for an idempotent replay.
        raw = json.dumps({
            "store": obs.store,
            "source_url": obs.source_url,
            "observed_at": obs.observed_at,
            "parser_version": obs.parser_version,
            "trace_id": obs.trace_id,
            "raw_title": obs.raw_title,
            "raw_price": obs.raw_price,
            "product": {
                "product_id": obs.product.product_id,
                "brand": obs.product.brand,
                "canonical_name": obs.product.canonical_name,
                "gtin": obs.product.gtin,
                "mpn": obs.product.mpn,
            },
            "variant": {
                "variant_id": obs.variant.variant_id,
                "product_id": obs.variant.product_id,
                "concentration": obs.variant.concentration,
                "size_ml": str(obs.variant.size_ml) if obs.variant.size_ml is not None else None,
                "pack_count": obs.variant.pack_count,
                "gender": obs.variant.gender,
            },
            "offer": {
                "offer_id": obs.offer.offer_id,
                "variant_id": obs.offer.variant_id,
                "store": obs.offer.store,
                "product_url": obs.offer.product_url,
                "price_minor": obs.offer.price_minor,
                "currency": obs.offer.currency,
                "availability": obs.offer.availability,
                "source_sku": obs.offer.source_sku,
            },
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def save_observation(self, obs: SourceObservation) -> bool:
        """Atomically upsert valid entities. Returns False for an identical replay."""
        key = self._observation_key(obs)
        payload = {
            "product": {"product_id": obs.product.product_id, "brand": obs.product.brand,
                        "canonical_name": obs.product.canonical_name, "gtin": obs.product.gtin,
                        "mpn": obs.product.mpn},
            "variant": {"variant_id": obs.variant.variant_id, "product_id": obs.variant.product_id,
                        "concentration": obs.variant.concentration,
                        "size_ml": str(obs.variant.size_ml) if obs.variant.size_ml is not None else None,
                        "pack_count": obs.variant.pack_count, "gender": obs.variant.gender},
            "offer": {"offer_id": obs.offer.offer_id, "variant_id": obs.offer.variant_id,
                      "store": obs.offer.store, "product_url": obs.offer.product_url,
                      "price_minor": obs.offer.price_minor, "currency": obs.offer.currency,
                      "availability": obs.offer.availability, "source_sku": obs.offer.source_sku},
        }
        with self._connection() as conn:
            if conn.execute("SELECT 1 FROM observations WHERE observation_key=?", (key,)).fetchone():
                return False
            conn.execute(
                """INSERT INTO products VALUES(?,?,?,?,?,?)
                   ON CONFLICT(product_id) DO UPDATE SET brand=excluded.brand,
                   canonical_name=excluded.canonical_name, gtin=COALESCE(excluded.gtin,products.gtin),
                   mpn=COALESCE(excluded.mpn,products.mpn), updated_at=excluded.updated_at
                   WHERE excluded.updated_at >= products.updated_at""",
                (obs.product.product_id, obs.product.brand, obs.product.canonical_name,
                 obs.product.gtin, obs.product.mpn, obs.observed_at))
            conn.execute(
                """INSERT INTO variants VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(variant_id) DO UPDATE SET product_id=excluded.product_id,
                   concentration=excluded.concentration, size_ml=excluded.size_ml,
                   pack_count=excluded.pack_count, gender=excluded.gender, updated_at=excluded.updated_at
                   WHERE excluded.updated_at >= variants.updated_at""",
                (obs.variant.variant_id, obs.variant.product_id, obs.variant.concentration,
                 str(obs.variant.size_ml) if obs.variant.size_ml is not None else None,
                 obs.variant.pack_count, obs.variant.gender, obs.observed_at))
            conn.execute(
                """INSERT INTO offers(offer_id,variant_id,store,product_url,price_minor,currency,
                   availability,source_sku,first_seen_at,last_seen_at,last_valid_at,is_current)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,1)
                   ON CONFLICT(store,product_url,variant_id) DO UPDATE SET price_minor=excluded.price_minor,
                   currency=excluded.currency, availability=excluded.availability,
                   source_sku=excluded.source_sku, last_seen_at=excluded.last_seen_at,
                   last_valid_at=excluded.last_valid_at, is_current=1
                   WHERE excluded.last_seen_at >= offers.last_seen_at""",
                (obs.offer.offer_id, obs.offer.variant_id, obs.offer.store, obs.offer.product_url,
                 obs.offer.price_minor, obs.offer.currency, obs.offer.availability,
                 obs.offer.source_sku, obs.observed_at, obs.observed_at, obs.observed_at))
            actual_offer = conn.execute(
                "SELECT offer_id FROM offers WHERE store=? AND product_url=? AND variant_id=?",
                (obs.offer.store, obs.offer.product_url, obs.offer.variant_id),
            ).fetchone()
            if not actual_offer:
                raise RuntimeError("offer upsert did not produce a persisted offer")
            persisted_offer_id = str(actual_offer["offer_id"])
            conn.execute(
                "INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?,?)",
                (key, persisted_offer_id, obs.store, obs.source_url, obs.observed_at,
                 obs.parser_version, obs.trace_id, obs.raw_title, obs.raw_price,
                 json.dumps(payload, ensure_ascii=False, sort_keys=True)))
            return True

    def save_observations_batch(self, observations: list[SourceObservation]) -> int:
        """Save a batch in one transaction. Returns newly inserted observation count."""
        if not observations:
            return 0
        saved = 0
        with self._connection() as conn:
            for obs in observations:
                key = self._observation_key(obs)
                if conn.execute("SELECT 1 FROM observations WHERE observation_key=?", (key,)).fetchone():
                    continue
                payload = {
                    "product": {"product_id": obs.product.product_id, "brand": obs.product.brand,
                                "canonical_name": obs.product.canonical_name, "gtin": obs.product.gtin,
                                "mpn": obs.product.mpn},
                    "variant": {"variant_id": obs.variant.variant_id, "product_id": obs.variant.product_id,
                                "concentration": obs.variant.concentration,
                                "size_ml": str(obs.variant.size_ml) if obs.variant.size_ml is not None else None,
                                "pack_count": obs.variant.pack_count, "gender": obs.variant.gender},
                    "offer": {"offer_id": obs.offer.offer_id, "variant_id": obs.offer.variant_id,
                              "store": obs.offer.store, "product_url": obs.offer.product_url,
                              "price_minor": obs.offer.price_minor, "currency": obs.offer.currency,
                              "availability": obs.offer.availability, "source_sku": obs.offer.source_sku},
                }
                conn.execute(
                    """INSERT INTO products VALUES(?,?,?,?,?,?)
                       ON CONFLICT(product_id) DO UPDATE SET brand=excluded.brand,
                       canonical_name=excluded.canonical_name, gtin=COALESCE(excluded.gtin,products.gtin),
                       mpn=COALESCE(excluded.mpn,products.mpn), updated_at=excluded.updated_at
                       WHERE excluded.updated_at >= products.updated_at""",
                    (obs.product.product_id, obs.product.brand, obs.product.canonical_name,
                     obs.product.gtin, obs.product.mpn, obs.observed_at))
                conn.execute(
                    """INSERT INTO variants VALUES(?,?,?,?,?,?,?)
                       ON CONFLICT(variant_id) DO UPDATE SET product_id=excluded.product_id,
                       concentration=excluded.concentration, size_ml=excluded.size_ml,
                       pack_count=excluded.pack_count, gender=excluded.gender, updated_at=excluded.updated_at
                       WHERE excluded.updated_at >= variants.updated_at""",
                    (obs.variant.variant_id, obs.variant.product_id, obs.variant.concentration,
                     str(obs.variant.size_ml) if obs.variant.size_ml is not None else None,
                     obs.variant.pack_count, obs.variant.gender, obs.observed_at))
                conn.execute(
                    """INSERT INTO offers(offer_id,variant_id,store,product_url,price_minor,currency,
                       availability,source_sku,first_seen_at,last_seen_at,last_valid_at,is_current)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,1)
                       ON CONFLICT(store,product_url,variant_id) DO UPDATE SET price_minor=excluded.price_minor,
                       currency=excluded.currency, availability=excluded.availability,
                       source_sku=excluded.source_sku, last_seen_at=excluded.last_seen_at,
                       last_valid_at=excluded.last_valid_at, is_current=1
                       WHERE excluded.last_seen_at >= offers.last_seen_at""",
                    (obs.offer.offer_id, obs.offer.variant_id, obs.offer.store, obs.offer.product_url,
                     obs.offer.price_minor, obs.offer.currency, obs.offer.availability,
                     obs.offer.source_sku, obs.observed_at, obs.observed_at, obs.observed_at))
                actual_offer = conn.execute(
                    "SELECT offer_id FROM offers WHERE store=? AND product_url=? AND variant_id=?",
                    (obs.offer.store, obs.offer.product_url, obs.offer.variant_id),
                ).fetchone()
                if not actual_offer:
                    raise RuntimeError("offer upsert did not produce a persisted offer")
                conn.execute(
                    "INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (key, str(actual_offer["offer_id"]), obs.store, obs.source_url, obs.observed_at,
                     obs.parser_version, obs.trace_id, obs.raw_title, obs.raw_price,
                     json.dumps(payload, ensure_ascii=False, sort_keys=True)))
                saved += 1
        return saved

    def record_failure(self, *, store: str, source_url: str, kind: str, message: str,
                       retryable: bool, occurred_at: str, trace_id: str | None = None) -> None:
        with self._connection() as conn:
            conn.execute(
                """INSERT INTO adapter_failures(store,source_url,kind,message,retryable,occurred_at,trace_id)
                   VALUES(?,?,?,?,?,?,?)""",
                (store, source_url, kind, message[:2000], int(retryable), occurred_at, trace_id))

    def current_offers(self, *, store: str | None = None) -> list[dict]:
        sql = """SELECT o.*,v.product_id,v.concentration,v.size_ml,v.pack_count,
                        p.brand,p.canonical_name
                 FROM offers o JOIN variants v USING(variant_id)
                 JOIN products p USING(product_id) WHERE o.is_current=1"""
        args: tuple = ()
        if store:
            sql += " AND o.store=?"
            args = (store,)
        sql += " ORDER BY o.currency,o.price_minor"
        with self._connection() as conn:
            return [dict(row) for row in conn.execute(sql, args).fetchall()]

    def counts(self) -> dict[str, int]:
        with self._connection() as conn:
            return {table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                    for table in ("products", "variants", "offers", "observations", "adapter_failures")}
