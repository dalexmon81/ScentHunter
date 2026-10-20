from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from urllib.parse import urlparse


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ISO 4217 currency codes (active and commonly used in retail feeds).
# Keep this allow-list explicit: a three-letter string alone is not a currency.
ISO_4217_CODES = frozenset("""
AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB
BOV BRL BSD BTN BWP BYN BZD CAD CDF CHE CHF CHW CLF CLP CNY COP COU CRC CUP
CVE CZK DJF DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD GNF GTQ
GYD HKD HNL HTG HUF IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR KMF KPW
KRW KWD KYD KZT LAK LBP LKR LRD LSL LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR
MVR MWK MXN MXV MYR MZN NAD NGN NIO NOK NPR NZD OMR PAB PEN PGK PHP PKR PLN
PYG QAR RON RSD RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE SLL SOS SRD SSP STN
SVC SYP SZL THB TJS TMT TND TOP TRY TTD TWD TZS UAH UGX USD USN UYI UYU UYW
UZS VED VES VND VUV WST XAF XAG XAU XBA XBB XBC XBD XCD XCG XDR XOF XPD XPF
XPT XSU XTS XUA XXX YER ZAR ZMW ZWG
""".split())

def normalize_currency(value: str) -> str:
    currency = str(value or "").strip().upper()
    if currency not in ISO_4217_CODES:
        raise ValueError("currency must be a recognized ISO 4217 code")
    return currency

def validate_timestamp(value: str, field: str = "timestamp") -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError(f"{field} is required")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from None
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    # Canonical UTC strings make timestamp comparisons safe across adapters
    # that emit different offsets for the same instant.
    return parsed.astimezone(timezone.utc).isoformat()


def price_to_minor_units(value: str | int | Decimal, currency: str) -> int:
    """Convert decimal major units to minor units without binary float arithmetic."""
    normalize_currency(currency)
    try:
        amount = Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        raise ValueError("price is not a valid decimal") from None
    if not amount.is_finite() or amount <= 0:
        raise ValueError("price must be finite and positive")
    return int((amount * Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def validate_http_url(url: str) -> str:
    value = str(url or "").strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("product URL must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        raise ValueError("credentials are not allowed in product URLs")
    return value


@dataclass(frozen=True)
class RetailerOfferRecord:
    """Raw, validated commercial facts from one retailer page.

    This type deliberately has no canonical product_id or variant_id. Those
    belong to the identity resolver, not the scraper/parser.
    """
    store: str
    source_url: str
    product_url: str
    title: str
    brand: str
    price_minor: int
    currency: str
    observed_at: str
    parser_version: str
    trace_id: str
    raw_price: str
    availability: str = "unknown"
    size_ml: Decimal | None = None
    concentration: str | None = None
    gender: str | None = None
    sku: str | None = None
    gtin: str | None = None
    mpn: str | None = None
    pack_count: int = 1

    def __post_init__(self):
        for field_name in ("store", "title", "brand", "parser_version", "trace_id", "raw_price"):
            if not str(getattr(self, field_name) or "").strip():
                raise ValueError(f"{field_name} is required")
        validate_http_url(self.source_url)
        validate_http_url(self.product_url)
        object.__setattr__(self, "observed_at", validate_timestamp(self.observed_at, "record.observed_at"))
        normalize_currency(self.currency)
        if isinstance(self.price_minor, bool) or not isinstance(self.price_minor, int) or self.price_minor <= 0:
            raise ValueError("price_minor must be a positive integer")
        if self.size_ml is not None:
            size = Decimal(str(self.size_ml))
            if not size.is_finite() or size <= 0:
                raise ValueError("size_ml must be finite and positive")
        if self.gtin and not re.fullmatch(r"\d{8,14}", self.gtin.strip()):
            raise ValueError("GTIN must contain 8–14 digits")
        if isinstance(self.pack_count, bool) or not isinstance(self.pack_count, int) or self.pack_count < 1:
            raise ValueError("pack_count must be a positive integer")


@dataclass(frozen=True)
class Product:
    product_id: str
    brand: str
    canonical_name: str
    gtin: str | None = None
    mpn: str | None = None

    def __post_init__(self):
        for name in ("product_id", "brand", "canonical_name"):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"{name} is required")
        if self.gtin and not re.fullmatch(r"\d{8,14}", self.gtin.strip()):
            raise ValueError("GTIN must contain 8–14 digits")


@dataclass(frozen=True)
class Variant:
    variant_id: str
    product_id: str
    concentration: str | None = None
    size_ml: Decimal | None = None
    pack_count: int = 1
    gender: str | None = None

    def __post_init__(self):
        if not self.variant_id or not self.product_id:
            raise ValueError("variant_id and product_id are required")
        if self.size_ml is not None and (not Decimal(str(self.size_ml)).is_finite() or Decimal(str(self.size_ml)) <= 0):
            raise ValueError("size_ml must be finite and positive")
        if self.pack_count < 1:
            raise ValueError("pack_count must be >= 1")


@dataclass(frozen=True)
class Offer:
    offer_id: str
    variant_id: str
    store: str
    product_url: str
    price_minor: int
    currency: str
    availability: str = "unknown"
    observed_at: str = ""
    source_sku: str | None = None

    def __post_init__(self):
        for name in ("offer_id", "variant_id", "store"):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"{name} is required")
        validate_http_url(self.product_url)
        normalize_currency(self.currency)
        if isinstance(self.price_minor, bool) or not isinstance(self.price_minor, int) or self.price_minor <= 0:
            raise ValueError("price_minor must be a positive integer")
        if not self.observed_at:
            object.__setattr__(self, "observed_at", utc_now_iso())
        else:
            object.__setattr__(self, "observed_at", validate_timestamp(self.observed_at, "offer.observed_at"))


@dataclass(frozen=True)
class SourceObservation:
    store: str
    source_url: str
    observed_at: str
    product: Product
    variant: Variant
    offer: Offer
    raw_title: str
    raw_price: str
    parser_version: str
    trace_id: str

    def __post_init__(self):
        validate_http_url(self.source_url)
        object.__setattr__(self, "observed_at", validate_timestamp(self.observed_at, "observation.observed_at"))
        if self.offer.observed_at != self.observed_at:
            raise ValueError("offer.observed_at must match observation.observed_at")
        if self.variant.product_id != self.product.product_id:
            raise ValueError("variant.product_id must match product.product_id")
        if self.offer.variant_id != self.variant.variant_id:
            raise ValueError("offer.variant_id must match variant.variant_id")
        if self.offer.store != self.store:
            raise ValueError("offer.store must match observation.store")
        if not self.raw_title.strip():
            raise ValueError("raw_title is required")
        if not self.parser_version.strip() or not self.trace_id.strip():
            raise ValueError("parser_version and trace_id are required")
