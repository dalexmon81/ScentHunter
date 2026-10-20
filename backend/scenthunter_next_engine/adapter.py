from __future__ import annotations
from typing import Protocol, Iterable
from .errors import AdapterFailure, ErrorKind
from .models import RetailerOfferRecord, validate_http_url


class RetailerAdapter(Protocol):
    """Retailer acquisition only; adapters never resolve identity or persist."""

    store_key: str
    parser_version: str

    def discover(self, *, limit: int) -> Iterable[str]:
        """Yield product-page URLs, bounded by limit."""
        ...

    def fetch(self, url: str) -> bytes:
        """Fetch one URL with explicit timeouts and retailer-compliant policy."""
        ...

    def parse(self, url: str, body: bytes) -> RetailerOfferRecord:
        """Parse commercial facts without inventing canonical product IDs."""
        ...


class OfferPipeline:
    """Validate retailer data at the boundary, before identity resolution."""

    def __init__(self, adapter: RetailerAdapter):
        self.adapter = adapter

    def discover(self, *, limit: int = 1000) -> list[str]:
        if limit < 1:
            raise ValueError("limit must be positive")
        urls: list[str] = []
        seen: set[str] = set()
        for raw_url in self.adapter.discover(limit=limit):
            url = validate_http_url(raw_url)
            if url not in seen:
                seen.add(url)
                urls.append(url)
            if len(urls) >= limit:
                break
        return urls

    def observe(self, url: str) -> RetailerOfferRecord:
        safe_url = validate_http_url(url)
        try:
            body = self.adapter.fetch(safe_url)
        except AdapterFailure:
            raise
        except TimeoutError as exc:
            raise AdapterFailure(ErrorKind.TRANSIENT_NETWORK, str(exc)) from exc
        except Exception as exc:
            raise AdapterFailure(ErrorKind.UNKNOWN, f"fetch raised {type(exc).__name__}: {exc}") from exc
        if not body:
            raise AdapterFailure(ErrorKind.INVALID_DOCUMENT, "empty response body")
        try:
            record = self.adapter.parse(safe_url, body)
        except AdapterFailure:
            raise
        except Exception as exc:
            raise AdapterFailure(ErrorKind.PARSER_REGRESSION, f"parser raised {type(exc).__name__}: {exc}") from exc
        if not isinstance(record, RetailerOfferRecord):
            raise AdapterFailure(ErrorKind.INVALID_PRODUCT, "parser did not return RetailerOfferRecord")
        if record.store != self.adapter.store_key:
            raise AdapterFailure(ErrorKind.INVALID_PRODUCT, "record store does not match adapter")
        if record.source_url != safe_url:
            raise AdapterFailure(ErrorKind.INVALID_URL, "record source_url does not match fetched URL")
        if record.parser_version != self.adapter.parser_version:
            raise AdapterFailure(ErrorKind.INVALID_PRODUCT, "record parser_version does not match adapter")
        return record
